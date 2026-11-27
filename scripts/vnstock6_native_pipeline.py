"""Independent generation-6 SSI OHLC, technical scoring, ledger and outcomes.

Historical generation-4/5 ledgers remain immutable. New records are written only
under output/history/vnstock6 and carry explicit generation/source provenance.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pandas as pd
from vnstock import Fundamental, Market, Reference, sources
from vnstock.errors import VnstockError

from vnstock6_scoring import availability_score
from vnstock6_quant import fundamental_factors, fundamental_factors_from_frames, technical_indicators
from vnstock6_fundamental_probe import STATEMENT_TYPES, latest_statement_probe
from vnstock6_market_factors import collect_market_factors
from vnstock6_raw_adapter import RawRelease, fundamental_frames, market_factors_from_raw, reference_industries
from vnstock6_json_safe import dumps_json
from vnstock6_v4_scoring import (
    PROFILES, classify_regime, depth_wall_metrics, factor_values, indicator_snapshot, score_profile, signal_values,
)

ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / "config" / "vnstock6.json"
PRED_ROOT = ROOT / "output" / "history" / "vnstock6" / "predictions"
OUTCOME_ROOT = ROOT / "output" / "history" / "vnstock6" / "outcomes"
OHLC_ROOT = ROOT / "output" / "ohlc"
FUNDAMENTAL_CACHE = ROOT / "output" / "vnstock6" / "fundamental-factors.json"
LEGACY_FINANCE_CACHE = ROOT / "output" / "finance" / "cache.json"
MARKET_FACTOR_CACHE = ROOT / "output" / "vnstock6" / "market-factors.json"
VNINDEX_PATH = ROOT / "output" / "market" / "vnindex.json"
ICT = timezone(timedelta(hours=7))


def scoring_snap_time(now: datetime, intraday: bool) -> str:
    """Record the real collection time for both intraday and post-market runs."""
    return now.strftime("%H:%M")

def load_config() -> dict[str, Any]:
    value = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    sources_config = value.get("sources") or {}
    market_config = sources_config.get("market") or {}
    indicator_config = value.get("market_indicators") or {}
    if (
        sources_config.get("reference") != "ssi"
        or market_config.get("primary") != "ssi"
        or market_config.get("fallback") is not None
        or sources_config.get("fundamental") != "fhsc"
        or (indicator_config.get("foreign_flow") or {}).get("primary") != "ssi"
        or (indicator_config.get("foreign_flow") or {}).get("fallback") != "fhsc"
        or (indicator_config.get("trade_size") or {}).get("primary") != "ssi"
        or (indicator_config.get("trade_size") or {}).get("fallback") != "fhsc"
        or (indicator_config.get("order_book") or {}).get("primary") != "fhsc"
        or (indicator_config.get("proprietary_flow") or {}).get("primary") != "fhsc"
        or (indicator_config.get("insider_deal") or {}).get("primary") != "fhsc"
        or not value.get("universe")
    ):
        raise ValueError("VNStock6 config violates the approved SSI/FHSC endpoint contract")
    weights = (value.get("scoring") or {}).get("weights") or {}
    required = {"trend", "momentum", "breakout", "liquidity", "fundamental", "growth"}
    if set(weights) != required or abs(sum(float(item) for item in weights.values()) - 1.0) > 1e-9:
        raise ValueError("VNStock6 scoring weights must contain the six production-reference factors and sum to 1")
    route_sources = {
        "reference.equity.list": sources_config["reference"],
        "market.equity.ohlcv": sources_config["market"]["primary"],
        "fundamental.equity.balance_sheet": sources_config["fundamental"],
        "fundamental.equity.income_statement": sources_config["fundamental"],
        "fundamental.equity.cash_flow": sources_config["fundamental"],
        "market.equity.foreign_flow": "ssi",
        "market.equity.session_stats": "ssi",
        "market.equity.active_session": "fhsc",
        "market.equity.order_book": "fhsc",
        "market.equity.proprietary_flow": "fhsc",
        "market.equity.insider_deal": "fhsc",
    }
    # vnstock 6.0.0 exposes/documents this FHSC method but omits it from the
    # sources.readers registry. Keep all other route checks strict.
    documented_registry_gap = {"market.equity.insider_deal"}
    for route, source in route_sources.items():
        readers = {str(item).lower() for item in sources.readers(route)}
        if source not in readers and route not in documented_registry_gap:
            raise ValueError(f"VNStock6 source {source} cannot read {route}")
    return value


def finite(value: Any) -> float | None:
    try:
        number = float(value)
        return number if math.isfinite(number) else None
    except (TypeError, ValueError):
        return None

_FUNDAMENTAL_VOLATILE_KEYS = frozenset({
    "checked_at", "refreshed_at", "fetched_at", "generated_at", "cache_stale",
    "latest_income_signature", "latest_income_period", "latest_statement_signature",
    "latest_statement_signatures", "latest_statement_periods", "cash_flow_period",
})

# Reporting-period corrections are metadata, not new scoring inputs.
_FUNDAMENTAL_PERIOD_KEYS = ("latest_income_period", "cash_flow_period", "latest_statement_periods")


def fundamental_period_metadata(value: dict[str, Any] | None) -> dict[str, Any]:
    record = value or {}
    return {key: record.get(key) for key in _FUNDAMENTAL_PERIOD_KEYS}



def fundamental_material_value(value: Any) -> Any:
    """Strip refresh metadata before deciding whether weekly BCTC changed."""
    if isinstance(value, dict):
        return {
            key: fundamental_material_value(item)
            for key, item in sorted(value.items())
            if key not in _FUNDAMENTAL_VOLATILE_KEYS
        }
    if isinstance(value, list):
        return [fundamental_material_value(item) for item in value]
    return value


def load_fundamental_cache(source: str) -> dict[str, Any]:
    if not FUNDAMENTAL_CACHE.exists():
        return {}
    value = json.loads(FUNDAMENTAL_CACHE.read_text(encoding="utf-8"))
    if str(value.get("source", "")).lower() != source.lower():
        return {}
    return dict(value.get("symbols") or {})


def overlay_legacy_cash_flow(factors: dict[str, Any], symbols: list[str]) -> tuple[dict[str, Any], int]:
    """Fill only missing cash-flow factors from the current audited BCTC cache."""
    output = {symbol: dict(value) for symbol, value in factors.items()}
    if not LEGACY_FINANCE_CACHE.exists():
        return output, 0
    try:
        payload = json.loads(LEGACY_FINANCE_CACHE.read_text(encoding="utf-8"))
        legacy_symbols = payload.get("symbols") or {}
    except (OSError, TypeError, json.JSONDecodeError):
        return output, 0
    restored = 0
    for symbol in symbols:
        target = dict(output.get(symbol) or {})
        if finite(target.get("cash_flow_score")) is not None:
            continue
        legacy = legacy_symbols.get(symbol) or {}
        score = finite((legacy.get("finance_score") or {}).get("cashflow"))
        if score is None:
            continue
        score = max(-10.0, min(10.0, score))
        cashflow = legacy.get("cashflow") or {}
        cfo = finite(cashflow.get("cf_operating"))
        quality = finite(cashflow.get("cf_quality"))
        if quality is None:
            profit = finite((legacy.get("income") or {}).get("net_profit_year"))
            quality = cfo / profit if cfo is not None and profit else None
        target.update({
            "cash_flow": score / 10,
            "cash_flow_score": int(score) if score.is_integer() else score,
            "cash_flow_operating": cfo,
            "cash_flow_quality": quality,
            "cash_flow_reason": None,
            "cash_flow_source": "legacy_finance_cache",
            "cash_flow_period": legacy.get("period"),
            "cash_flow_refreshed_at": legacy.get("fetched_at") or payload.get("generated_at"),
        })
        if not target.get("refreshed_at"):
            target["refreshed_at"] = legacy.get("fetched_at") or payload.get("generated_at")
        output[symbol] = target
        restored += 1
    return output, restored


def load_market_factor_cache() -> dict[str, dict[str, Any]]:
    if not MARKET_FACTOR_CACHE.exists():
        return {}
    try:
        payload = json.loads(MARKET_FACTOR_CACHE.read_text(encoding="utf-8"))
        return dict(payload.get("symbols") or {})
    except (OSError, TypeError, json.JSONDecodeError):
        return {}


def stamp_live_depth_metadata(
    factors: dict[str, dict[str, Any]], signal_date: date, snap_time: str, captured_at: str,
) -> None:
    """Align live FHSC order-book provenance before scoring and validation."""
    for value in factors.values():
        source = str((value.get("endpoint_sources") or {}).get("order_book") or "")
        raw = value.get("raw") or {}
        if (
            source != "FHSC" or value.get("depth_status") != "live_ready"
            or not raw.get("order_book") or finite(raw.get("average_trade_size")) is None
        ):
            continue
        value.update({
            "depth_signal_date": signal_date.isoformat(),
            "depth_snap_time": snap_time,
            "depth_captured_at": captured_at,
            "depth_status": "live_scored",
        })

def save_market_factor_cache(factors: dict[str, Any]) -> None:
    MARKET_FACTOR_CACHE.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": 2,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source": "SSI_FAST+FHSC_SLOW",
        "symbols": dict(sorted(factors.items())),
    }
    MARKET_FACTOR_CACHE.write_text(
        dumps_json(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def save_fundamental_cache(source: str, factors: dict[str, Any]) -> None:
    FUNDAMENTAL_CACHE.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": 1, "generated_at": datetime.now(timezone.utc).isoformat(),
        "source": source.upper(), "calculation_engine": "vnstock_quant",
        "calculation_version": "1.1.0", "symbols": dict(sorted(factors.items())),
    }
    FUNDAMENTAL_CACHE.write_text(
        dumps_json(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def market_fetch_start(symbol: str, today: date, history_days: int) -> str:
    """Bootstrap full history once, then refetch only a correction window."""
    path = OHLC_ROOT / f"{symbol}.json"
    if path.exists():
        try:
            rows = json.loads(path.read_text(encoding="utf-8"))
            latest = max(date.fromisoformat(str(row["date"])[:10]) for row in rows if row.get("date"))
            return (latest - timedelta(days=14)).isoformat()
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            pass
    return (today - timedelta(days=history_days)).isoformat()


def cache_entry_is_fresh(entry: dict[str, Any], max_age_days: int) -> bool:
    """Accept last-known-good values after a successful daily source check.

    ``checked_at`` advances when FHSC statements are unchanged; ``refreshed_at``
    advances only when statement content changes and factors are recalculated.
    Version 1.0 entries stay usable during the cash-flow migration so intraday
    does not discard otherwise valid fundamental and growth scores.
    """
    checked_at = entry.get("checked_at") or entry.get("refreshed_at")
    if not checked_at:
        return False
    try:
        checked = datetime.fromisoformat(str(checked_at).replace("Z", "+00:00"))
        if checked.tzinfo is None:
            checked = checked.replace(tzinfo=timezone.utc)
        return datetime.now(timezone.utc) - checked <= timedelta(days=max_age_days)
    except (TypeError, ValueError):
        return False


def fundamental_ttl_days(config: dict[str, Any], now: datetime | None = None) -> int:
    """Match the legacy cron v2.0 finance cadence: 3d in earnings months, else 30d."""
    refresh = config.get("fundamental_refresh") or {}
    current = now or datetime.now(ICT)
    earnings_months = {int(value) for value in refresh.get("earnings_months", [])}
    if current.month in earnings_months:
        return int(refresh.get("earnings_max_age_days", 3))
    return int(refresh.get("max_age_days", 30))


def stale_fundamental_symbols(
    config: dict[str, Any], cache: dict[str, Any], now: datetime | None = None
) -> list[str]:
    ttl_days = fundamental_ttl_days(config, now)
    return [
        symbol for symbol in config["universe"]
        if not cache_entry_is_fresh(cache.get(symbol) or {}, ttl_days)
    ]


def refresh_fundamental_cache(
    config: dict[str, Any], limit: int | None = None, stale_only: bool = False,
    check_updates: bool = False,
) -> dict[str, Any]:
    """Refresh FHSC statements or check the universe for changed reports.

    Daily maintenance reads statements after market close, but recalculates only
    changed content. Weekly refresh deliberately recalculates the full universe.
    """
    source_config = config["sources"]
    reference_source = source_config["reference"]
    fundamental_source = source_config["fundamental"]
    factor_cache = load_fundamental_cache(fundamental_source)
    ttl_days = fundamental_ttl_days(config)
    configured = list(config["universe"]) if check_updates else (
        stale_fundamental_symbols(config, factor_cache)
        if stale_only else list(config["universe"])
    )

    reference = Reference(reference_source).equity.list() if configured else pd.DataFrame()
    symbol_column = next((column for column in reference.columns if str(column).lower() == "symbol"), None)
    industry_column = next((column for column in reference.columns if str(column).lower() in {"industry", "industry_name", "icb_name", "icb_name3", "icb_name2"}), None)
    industry_map = {str(row[symbol_column]).upper(): str(row[industry_column]) for _, row in reference.iterrows()} if symbol_column and industry_column else {}
    if stale_only:
        universe = list(config["universe"])
        selected = configured if limit is None else configured[:limit]
    else:
        if symbol_column is None: raise ValueError("SSI reference schema missing symbol column")
        available = {str(value).upper() for value in reference[symbol_column].dropna()}
        universe = [symbol for symbol in config["universe"] if symbol in available]
        selected = universe if limit is None else universe[:limit]

    def fetch_one(symbol: str) -> tuple[str, dict[str, Any], dict[str, Any] | None]:
        previous = factor_cache.get(symbol)
        probe: dict[str, Any] | None = None
        probe_attempt = 0
        probe_request_count = 0
        if check_updates:
            for probe_attempt in range(1, 4):
                probe = latest_statement_probe(symbol, fundamental_source)
                probe_request_count += int(probe.get("request_count", 0))
                if not probe.get("error"):
                    break
                if probe_attempt < 3:
                    time.sleep(probe_attempt)
            if probe and probe.get("error") and previous:
                return symbol, {
                    "status": "failed_preserved",
                    "attempt": probe_attempt,
                    "phase": "probe",
                    "probe_request_count": probe_request_count,
                    "type": probe["error"].get("type"),
                    "code": probe["error"].get("code"),
                }, previous

            if probe and not probe.get("error") and previous:
                previous_probe = previous.get("latest_statement_signature")
                has_growth_inputs = all(
                    key in previous for key in ("growth_revenue_yoy", "growth_profit_yoy")
                )
                if previous_probe == probe["signature"] and has_growth_inputs:
                    value = dict(previous)
                    value["checked_at"] = datetime.now(timezone.utc).isoformat()
                    value["latest_statement_signature"] = probe["signature"]
                    value["latest_statement_signatures"] = probe["statement_signatures"]
                    value["latest_statement_periods"] = probe["periods"]
                    value["latest_income_signature"] = probe["statement_signatures"]["income-statement"]
                    value["latest_income_period"] = probe["periods"]["income-statement"]
                    value["cash_flow_period"] = probe["periods"]["cash-flow"]
                    return symbol, {
                        "status": "unchanged",
                        "attempt": probe_attempt,
                        "phase": "probe",
                        "probe_request_count": probe_request_count,
                        "material_changed": False,
                        "metadata_changed": (
                            fundamental_period_metadata(previous) != fundamental_period_metadata(value)
                        ),
                    }, value

        last_result: dict[str, Any] | None = None
        for attempt in range(1, 4):
            last_result = fundamental_factors(
                symbol,
                fundamental_source,
                industry_map.get(symbol),
            )
            if not last_result.get("error"):
                checked_at = datetime.now(timezone.utc).isoformat()
                last_result["checked_at"] = checked_at
                last_result["refreshed_at"] = checked_at
                if probe and not probe.get("error"):
                    last_result["latest_statement_signature"] = probe["signature"]
                    last_result["latest_statement_signatures"] = probe["statement_signatures"]
                    # Full normalized statements are the primary period evidence.
                    # The source probe only fills fields the full reader lacks.
                    normalized_periods = last_result.get("latest_statement_periods") or {}
                    last_result["latest_statement_periods"] = {
                        kind: normalized_periods.get(kind) or period
                        for kind, period in probe["periods"].items()
                    }
                    last_result["latest_income_signature"] = probe["statement_signatures"]["income-statement"]
                    last_result["latest_income_period"] = (
                        last_result.get("latest_income_period")
                        or probe["periods"]["income-statement"]
                    )
                    last_result["cash_flow_period"] = (
                        last_result.get("cash_flow_period")
                        or probe["periods"]["cash-flow"]
                    )
                material_changed = (
                    fundamental_material_value(previous) != fundamental_material_value(last_result)
                )
                metadata_changed = (
                    fundamental_period_metadata(previous) != fundamental_period_metadata(last_result)
                )
                return symbol, {
                    "status": "updated",
                    "attempt": attempt,
                    "phase": "materialize",
                    "probe_attempt": probe_attempt if check_updates else 0,
                    "probe_request_count": probe_request_count,
                    "material_changed": material_changed,
                    "metadata_changed": metadata_changed,
                }, last_result
            if attempt < 3:
                time.sleep(attempt)
        return symbol, {
            "status": "failed_preserved" if previous else "failed",
            "attempt": 3,
            "type": (last_result or {}).get("error", {}).get("type"),
            "code": (last_result or {}).get("error", {}).get("code"),
            "material_changed": False,
            "metadata_changed": False,
            "probe_request_count": probe_request_count,
        }, previous

    results: dict[str, Any] = {}
    workers = max(1, min(
        int((config.get("fundamental_refresh") or {}).get("max_workers", 1)),
        len(selected) or 1,
    ))
    with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="vnstock6-fundamental") as executor:
        fetched = list(executor.map(fetch_one, selected))
    for symbol, result, value in fetched:
        results[symbol] = result
        if value is not None:
            factor_cache[symbol] = value

    if selected:
        save_fundamental_cache(fundamental_source, factor_cache)
    counts = {
        "updated": sum(item["status"] == "updated" for item in results.values()),
        "unchanged": sum(item["status"] == "unchanged" for item in results.values()),
        "failed": sum(item["status"] == "failed" for item in results.values()),
        "failed_preserved": sum(item["status"] == "failed_preserved" for item in results.values()),
        "material_changed": sum(bool(item.get("material_changed")) for item in results.values()),
        "metadata_changed": sum(bool(item.get("metadata_changed")) for item in results.values()),
        "skipped_fresh": len(config["universe"]) - len(configured) if stale_only else 0,
    }
    status = {
        "schema_version": 1, "generated_at": datetime.now(timezone.utc).isoformat(),
        "reference_source": reference_source.upper(), "fundamental_source": fundamental_source.upper(),
        "configured_symbols": len(config["universe"]), "reference_symbols_available": len(universe),
        "symbols_requested": len(selected), "cache_symbols": len(factor_cache),
        "stale_only": stale_only, "check_updates": check_updates, "ttl_days": ttl_days,
        "run_id": os.environ.get("GITHUB_RUN_ID"),
        "update_detection": "fhsc_latest_statements_limit_1" if check_updates else "full_materialize",
        "probe_statement_types": list(STATEMENT_TYPES) if check_updates else [],
        "probe_request_count": sum(
            int(item.get("probe_request_count", 0)) for item in results.values()
        ),
        "max_workers": workers,
        "counts": counts, "symbols": results,
    }
    status_path = ROOT / "output" / "vnstock6" / "fundamental-status.json"
    status_path.parent.mkdir(parents=True, exist_ok=True)
    status_path.write_text(dumps_json(status, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(
        f"VNStock6 fundamentals: {counts['updated']} updated, {counts['unchanged']} unchanged, "
        f"{counts['failed']} failed, {counts['failed_preserved']} preserved, "
        f"{counts['material_changed']} materially changed"
    )
    return status

def refresh_fundamental_cache_from_raw(
    config: dict[str, Any], raw: RawRelease, limit: int | None = None,
) -> dict[str, Any]:
    """Recalculate Gen6 fundamentals from one verified raw release."""
    source = config["sources"]["fundamental"]
    factor_cache = load_fundamental_cache(source)
    industries = reference_industries(raw)
    selected = list(config["universe"])
    if limit is not None:
        selected = selected[:limit]
    checked_at = str(raw.manifest.get("created_at") or datetime.now(timezone.utc).isoformat())
    results: dict[str, Any] = {}
    for symbol in selected:
        previous = factor_cache.get(symbol)
        value = fundamental_factors_from_frames(
            symbol, fundamental_frames(raw, symbol), industries.get(symbol),
            (previous or {}).get("statement_signature"),
        )
        if value.get("unchanged") and previous:
            retained = dict(previous)
            retained["checked_at"] = checked_at
            retained["raw_release_id"] = raw.release_id
            factor_cache[symbol] = retained
            results[symbol] = {
                "status": "unchanged", "phase": "raw_release",
                "material_changed": False, "raw_release_id": raw.release_id,
            }
            continue
        if value.get("error"):
            results[symbol] = {
                "status": "failed_preserved" if previous else "failed",
                "phase": "raw_release", "raw_release_id": raw.release_id,
                "type": value["error"].get("type"), "code": value["error"].get("code"),
                "material_changed": False,
            }
            continue
        value.update({
            "checked_at": checked_at, "refreshed_at": checked_at,
            "raw_release_id": raw.release_id, "input_layer": "shared_provider_raw",
        })
        changed = fundamental_material_value(previous) != fundamental_material_value(value)
        factor_cache[symbol] = value
        results[symbol] = {
            "status": "updated", "phase": "raw_release",
            "material_changed": changed, "raw_release_id": raw.release_id,
        }
    save_fundamental_cache(source, factor_cache)
    counts = {
        status: sum(item["status"] == status for item in results.values())
        for status in ("updated", "unchanged", "failed", "failed_preserved")
    }
    counts["material_changed"] = sum(bool(item.get("material_changed")) for item in results.values())
    status = {
        "schema_version": 1, "generated_at": datetime.now(timezone.utc).isoformat(),
        "reference_source": "SSI", "fundamental_source": "FHSC",
        "input_layer": "shared_provider_raw", "raw_release_id": raw.release_id,
        "raw_cadence": raw.manifest.get("cadence"),
        "configured_symbols": len(config["universe"]), "reference_symbols_available": len(industries),
        "symbols_requested": len(selected), "cache_symbols": len(factor_cache),
        "run_id": os.environ.get("GITHUB_RUN_ID"), "counts": counts, "symbols": results,
    }
    status_path = ROOT / "output" / "vnstock6" / "fundamental-status.json"
    status_path.parent.mkdir(parents=True, exist_ok=True)
    status_path.write_text(dumps_json(status, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(
        f"VNStock6 raw fundamentals {raw.release_id}: {counts['updated']} updated, "
        f"{counts['unchanged']} unchanged, {counts['failed']} failed"
    )
    return status

def intraday_turnover_value(frame: pd.DataFrame, trading_day: date) -> float | None:
    """Estimate matched value as sum of each intraday bar close times volume."""
    data = frame.reset_index()
    lowered = {str(column).lower(): column for column in data.columns}
    time_column = next((lowered[key] for key in ("time", "date", "datetime", "index") if key in lowered), None)
    close_column, volume_column = lowered.get("close"), lowered.get("volume")
    if time_column is None or close_column is None or volume_column is None:
        return None
    parsed = pd.to_datetime(data[time_column], errors="coerce")
    close = pd.to_numeric(data[close_column], errors="coerce")
    volume = pd.to_numeric(data[volume_column], errors="coerce")
    mask = parsed.dt.date == trading_day
    values = (close[mask] * volume[mask]).dropna()
    if values.empty:
        return None
    return finite(values.sum() * 1_000)


def fetch_intraday_ohlcv(
    equity: Any, symbol: str, market_source: str, trading_day: date, now: datetime,
    retries: int = 2,
) -> tuple[list[dict[str, Any]], float | None]:
    """Fetch current-session bars with two bounded retries for transient empties."""
    for attempt in range(max(0, retries) + 1):
        live = equity.ohlcv(
            start=trading_day.isoformat(), end=now.isoformat(), interval="5m", compat="v6"
        )
        live_rows = normalize_ohlcv(live, symbol, market_source)
        if any(row["date"] == trading_day.isoformat() for row in live_rows):
            return live_rows, intraday_turnover_value(live, trading_day)
        if attempt < max(0, retries):
            time.sleep(0.5 * (attempt + 1))
    raise ValueError(f"No current-session intraday OHLC for {symbol} from {market_source}")

def normalize_ohlcv(frame: pd.DataFrame, symbol: str, market_source: str) -> list[dict[str, Any]]:
    data = frame.reset_index()
    lowered = {str(column).lower(): column for column in data.columns}
    time_column = next((lowered[key] for key in ("time", "date", "datetime", "index") if key in lowered), None)
    required = {name: lowered.get(name) for name in ("open", "high", "low", "close", "volume")}
    if time_column is None or any(column is None for column in required.values()):
        raise ValueError(f"SSI OHLC schema unsupported for {symbol}: {list(data.columns)}")
    data["_parsed_time"] = pd.to_datetime(data[time_column], errors="coerce")
    data = data.dropna(subset=["_parsed_time"]).sort_values("_parsed_time")
    rows: dict[str, dict[str, Any]] = {}
    for _, source in data.iterrows():
        parsed = source["_parsed_time"]
        day = parsed.date().isoformat()
        values = {name: finite(source[column]) for name, column in required.items()}
        if any(values[name] is None for name in ("open", "high", "low", "close")):
            continue
        row = rows.get(day)
        if row is None:
            rows[day] = {
                "symbol": symbol, "date": day, "market_source": market_source.upper(),
                "pipeline_generation": 6, **values,
            }
            continue
        row["high"] = max(float(row["high"]), float(values["high"]))
        row["low"] = min(float(row["low"]), float(values["low"]))
        row["close"] = values["close"]
        if values["volume"] is not None:
            row["volume"] = float(row.get("volume") or 0) + float(values["volume"])
    return [rows[key] for key in sorted(rows)]


def merge_ohlcv(symbol: str, incoming: list[dict[str, Any]]) -> list[dict[str, Any]]:
    path = OHLC_ROOT / f"{symbol}.json"
    existing = json.loads(path.read_text(encoding="utf-8")) if path.exists() else []
    merged = {str(row.get("date")): row for row in existing if row.get("date")}
    merged.update({row["date"]: row for row in incoming})
    result = [merged[key] for key in sorted(merged)][-900:]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(dumps_json(result, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    return result


def rsi(series: pd.Series, periods: int = 14) -> float | None:
    delta = series.diff()
    gain = delta.clip(lower=0).rolling(periods).mean()
    loss = -delta.clip(upper=0).rolling(periods).mean()
    denominator = loss.iloc[-1]
    if pd.isna(denominator):
        return None
    if denominator == 0:
        return 100.0
    return finite(100 - (100 / (1 + gain.iloc[-1] / denominator)))


def score(symbol: str, rows: list[dict[str, Any]], version: str, snap_time: str, factors: dict[str, Any], weights: dict[str, float]) -> dict[str, Any]:
    frame = pd.DataFrame(rows).sort_values("date")
    if len(frame) < 50:
        raise ValueError(f"Insufficient OHLC history for {symbol}: {len(frame)}")
    close = pd.to_numeric(frame["close"], errors="coerce")
    volume = pd.to_numeric(frame["volume"], errors="coerce")
    latest = frame.iloc[-1]
    indicators = technical_indicators(frame)
    ema20, ema50, ema200 = indicators.get("ema20"), indicators.get("ema50"), indicators.get("ema200")
    rsi14 = indicators.get("rsi14")
    current = finite(latest["close"])
    return20 = finite((current / close.iloc[-21] - 1) * 100) if len(frame) >= 21 and current else None
    vol_ratio = finite(volume.iloc[-1] / volume.tail(20).mean())
    high52 = finite(pd.to_numeric(frame["high"], errors="coerce").tail(252).max())
    low52 = finite(pd.to_numeric(frame["low"], errors="coerce").tail(252).min())
    trend = (20 if current and ema20 and current > ema20 else -20) + (15 if ema20 and ema50 and ema20 > ema50 else -15)
    momentum = 0 if rsi14 is None else (15 if 45 <= rsi14 <= 70 else -12 if rsi14 > 75 else 10 if rsi14 < 30 else 0)
    breakout = 15 if return20 is not None and return20 > 5 else -15 if return20 is not None and return20 < -5 else 0
    liquidity = 5 if vol_ratio is not None and vol_ratio >= 1.2 else -5 if vol_ratio is not None and vol_ratio < 0.5 else 0
    availability = availability_score({
        "price": current, "ema20": ema20, "ema50": ema50, "rsi14": rsi14,
        "return20": return20, "volume_ratio": vol_ratio,
        "fundamental": factors.get("fundamental"), "growth": factors.get("growth"),
        "fundamental_reason": factors.get("fundamental_reason"),
        "growth_reason": factors.get("growth_reason"),
    }, weights)
    total, decision = availability["score"], availability["decision"]
    signal_date = str(latest["date"])
    raw_id = f"6|{latest.get('market_source')}|{symbol}|{signal_date}|{snap_time}|{version}"
    pred_id = f"v6_{hashlib.sha256(raw_id.encode()).hexdigest()[:24]}"
    return {
        "pred_id": pred_id, "symbol": symbol, "signal_date": signal_date, "snap_time": snap_time,
        "scoring_version": version, "decision": decision, "score_trade": total, "total_score": total,
        "price": current, "confidence": "HIGH" if abs(total) >= 55 else "MEDIUM" if abs(total) >= 25 else "LOW",
        "pipeline_generation": 6, "reference_source": "SSI", "market_source": str(latest.get("market_source") or "UNKNOWN"),
        "fundamental_source": "FHSC", "data_origin": "native",
        "flow": "vnstock6_native", "universe_variant": "vn100-cutover", "registry_version": 2,
        "ema20": ema20, "ema50": ema50, "ema200": ema200, "rsi_14": rsi14,
        "return_20d": return20, "vol_ma_ratio": vol_ratio, "high_52w": high52, "low_52w": low52,
        "s_trend_st": trend, "s_momentum_native": momentum, "s_breakout_native": breakout,
        "s_volume_native": liquidity,
        "fundamental_status": "scored" if factors.get("fundamental") is not None else "excluded",
        "quant_indicators": indicators, "fundamental_metrics": factors,
        "calculation_engine": "vnstock_quant", "calculation_version": "1.0.0",
        "scoring_reference": "vnstock-production-factor-contract",
        **availability,
    }


def score_v4_profiles(
    symbol: str, rows: list[dict[str, Any]], versions: list[str], snap_time: str,
    fundamentals: dict[str, Any], index_rows: list[dict[str, Any]],
    market: dict[str, Any] | None = None, snapshot_at: str | None = None,
    run_kind: str = "intraday",
) -> list[dict[str, Any]]:
    frame = pd.DataFrame(rows).sort_values("date")
    if len(frame) < 50:
        raise ValueError(f"Insufficient OHLC history for {symbol}: {len(frame)}")
    latest = frame.iloc[-1]
    quant = technical_indicators(frame)
    current = finite(latest["close"])
    signal_date = str(latest["date"])
    regime_info = classify_regime(index_rows, signal_date)
    indicators = indicator_snapshot(frame, quant, regime_info.get("return_20d"))
    market = market or {}
    market_raw = market.get("raw") or {}
    turnover_as_of = str(market_raw.get("session_turnover_as_of") or "")
    exact_turnover = finite(market_raw.get("session_turnover_value"))
    estimate_as_of = str(market_raw.get("intraday_turnover_as_of") or "")
    intraday_turnover = finite(market_raw.get("intraday_turnover_value_estimate"))
    if exact_turnover is not None and turnover_as_of == signal_date:
        indicators["adtv_bil"] = exact_turnover / 1_000_000_000
        indicators["session_turnover_bil"] = exact_turnover / 1_000_000_000
        indicators["liquidity_source"] = "SSI_SESSION_STATS"
        indicators["turnover_quality"] = "exact"
        indicators["turnover_as_of"] = turnover_as_of
        indicators["turnover_checked_at"] = market_raw.get("session_turnover_checked_at")
    elif intraday_turnover is not None and estimate_as_of == signal_date:
        indicators["adtv_bil"] = intraday_turnover / 1_000_000_000
        indicators["session_turnover_bil"] = intraday_turnover / 1_000_000_000
        indicators["liquidity_source"] = "SSI_OHLCV_ESTIMATE"
        indicators["turnover_quality"] = "estimated"
        indicators["turnover_as_of"] = estimate_as_of
        indicators["turnover_checked_at"] = market_raw.get("intraday_turnover_checked_at")
    else:
        indicators["liquidity_source"] = "SSI_OHLCV_ESTIMATE"
        indicators["turnover_quality"] = "estimated"
        indicators["turnover_as_of"] = signal_date
        indicators["turnover_checked_at"] = None
    foreign_as_of = str(market_raw.get("foreign_as_of") or "")
    foreign_net_1d = (
        finite(market_raw.get("foreign_net_1d"))
        if foreign_as_of == signal_date else None
    )
    turnover_bil = finite(indicators.get("session_turnover_bil"))
    foreign_ratio = (
        foreign_net_1d / (turnover_bil * 1_000_000_000)
        if foreign_net_1d is not None and turnover_bil and turnover_bil > 0 else None
    )
    if foreign_ratio is not None and abs(foreign_ratio) > 1:
        foreign_ratio = None
    signals = signal_values(indicators, fundamentals, regime_info["regime"], market, snap_time)
    depth_metrics = depth_wall_metrics(market, finite(indicators.get("entry")))
    output: list[dict[str, Any]] = []
    for version in versions:
        factors = factor_values(signals, PROFILES[version]["extras"], "trade")
        hold_factors = factor_values(signals, PROFILES[version]["extras"], "hold")
        scored = score_profile(version, factors, regime_info["regime"], hold_factors)
        raw_id = f"6|{latest.get('market_source')}|{symbol}|{signal_date}|{snap_time}|{version}"
        is_buy = scored["decision"] in {"BUY", "STRONG BUY"}
        levels = {key: indicators.get(key) if is_buy else None for key in ("entry", "stop", "tp1", "tp2")}
        ratios = fundamentals.get("ratios") or {}
        output.append({
            "pred_id": f"v6_{hashlib.sha256(raw_id.encode()).hexdigest()[:24]}",
            "symbol": symbol, "signal_date": signal_date, "snap_time": snap_time,
            "snapshot_at": snapshot_at, "run_kind": run_kind,
            "data_as_of": snap_time if run_kind == "intraday" else "15:00",
            "scoring_version": version, "price": current,
            "pipeline_generation": 6, "reference_source": "SSI",
            "market_source": str(latest.get("market_source") or "UNKNOWN"),
            "fundamental_source": "FHSC", "data_origin": "native",
            "flow": "vnstock6_native_v4_profiles", "universe_variant": "vn100-hose",
            "registry_version": 3, "gate_version": 7,
            "regime_as_of": regime_info.get("as_of"), "regime_method": regime_info.get("reason"),
            "market_regime": regime_info.get("regime"),
            "vnindex_close": finite(regime_info.get("close")),
            "vnindex_ema20": finite(regime_info.get("ema20")),
            "vnindex_ema50": finite(regime_info.get("ema50")),
            "vnindex_ema200": finite(regime_info.get("ema200")),
            **indicators, **levels, **signals, **scored,
            **{key: value for key, value in depth_metrics.items() if key != "score"},
            "ff_intra_net": foreign_net_1d, "ff_intra_ratio": foreign_ratio,
            "foreign_net_1d": foreign_net_1d,
            "foreign_net_5d": finite(market_raw.get("foreign_net_5d")),
            "foreign_net_20d": finite(market_raw.get("foreign_net_20d")),
            "foreign_as_of": foreign_as_of or None,
            "foreign_source": (market.get("endpoint_sources") or {}).get("foreign_flow"),
            "proprietary_net_5d": finite(market_raw.get("proprietary_net_5d")),
            "proprietary_net_20d": finite(market_raw.get("proprietary_net_20d")),
            "proprietary_row_count": finite(market_raw.get("proprietary_row_count")),
            "proprietary_usable_rows": finite(market_raw.get("proprietary_usable_rows")),
            "proprietary_as_of": market_raw.get("proprietary_as_of"),
            "proprietary_source": (market.get("endpoint_sources") or {}).get("proprietary_flow"),
            "proprietary_flow_status": market.get("proprietary_flow_status"),
            "proprietary_flow_checked_at": market.get("proprietary_flow_checked_at"),
            "proprietary_flow_refreshed_at": market.get("proprietary_flow_refreshed_at"),
            "insider_buy_count": finite(market_raw.get("insider_buy_count")),
            "insider_sell_count": finite(market_raw.get("insider_sell_count")),
            "insider_row_count": finite(market_raw.get("insider_row_count")),
            "insider_unclassified_count": finite(market_raw.get("insider_unclassified_count")),
            "insider_as_of": market_raw.get("insider_as_of"),
            "insider_source": (market.get("endpoint_sources") or {}).get("insider_deal"),
            "insider_deal_status": market.get("insider_deal_status"),
            "insider_deal_checked_at": market.get("insider_deal_checked_at"),
            "insider_deal_refreshed_at": market.get("insider_deal_refreshed_at"),
            "order_book_source": (market.get("endpoint_sources") or {}).get("order_book"),
            "order_book_observed_source": (market.get("endpoint_sources") or {}).get("observed_order_book")
            or (market.get("endpoint_sources") or {}).get("order_book"),
            "depth_status": market.get("depth_status"),
            "depth_signal_date": market.get("depth_signal_date"),
            "depth_snap_time": market.get("depth_snap_time"),
            "depth_captured_at": market.get("depth_captured_at"),
            "order_flow_source": "SSI_OHLCV_PHASE_VOLUME",
            "order_flow_as_of": f"{signal_date} {snap_time}",
            "fundamental_score": signals.get("s_fund_core"), "growth_score": signals.get("s_growth_core"),
            "growth_revenue_yoy": finite(fundamentals.get("growth_revenue_yoy")),
            "growth_profit_yoy": finite(fundamentals.get("growth_profit_yoy")),
            "growth_effective_yoy": (
                finite(fundamentals.get("growth")) * 0.25
                if finite(fundamentals.get("growth")) is not None else None
            ),
            "growth_input_count": sum(
                finite(fundamentals.get(key)) is not None
                for key in ("growth_revenue_yoy", "growth_profit_yoy")
            ),
            "growth_period": fundamentals.get("latest_income_period")
            or (fundamentals.get("latest_statement_periods") or {}).get("income-statement"),
            "ratio_roe": ratios.get("RT_PRT_ROE"), "ratio_roa": ratios.get("RT_PRT_ROA"),
            "ratio_gross_margin": ratios.get("RT_PRT_GROSS_MARGIN"), "ratio_net_margin": ratios.get("RT_PRT_NET_MARGIN"),
            "ratio_current": ratios.get("RT_LQD_CR"), "ratio_debt_equity": ratios.get("RT_LEV_DE"),
            "cash_flow_operating": fundamentals.get("cash_flow_operating"),
            "cash_flow_quality": fundamentals.get("cash_flow_quality"),
            "cash_flow_score": fundamentals.get("cash_flow_score"),
            "cash_flow_source": fundamentals.get("cash_flow_source") or "FHSC",
            "cash_flow_period": fundamentals.get("cash_flow_period")
            or (fundamentals.get("latest_statement_periods") or {}).get("cash-flow"),
            "cash_flow_refreshed_at": fundamentals.get("cash_flow_refreshed_at") or fundamentals.get("refreshed_at"),
            "market_indicator_sources": market.get("endpoint_sources") or {},
            "fundamental_status": ("stale_cache_scored" if fundamentals.get("cache_stale") else "scored") if fundamentals.get("fundamental") is not None else "excluded",
            "quant_indicators": quant, "fundamental_metrics": fundamentals,
            "calculation_engine": "vnstock_quant+gen6_v4_profiles", "calculation_version": "1.1.0",
            "scoring_reference": "vnstock-v4.17-v4.18-v4.19-factor-architecture",
        })
    return output


def update_vnindex(market_source: str, today: date) -> list[dict[str, Any]]:
    existing = json.loads(VNINDEX_PATH.read_text(encoding="utf-8")) if VNINDEX_PATH.exists() else []
    start = (today - timedelta(days=550)).isoformat()
    if existing:
        start = (date.fromisoformat(str(existing[-1]["date"])[:10]) - timedelta(days=14)).isoformat()
    frame = Market(market_source).index("VNINDEX").ohlcv(start=start, interval="1D", compat="v6")
    incoming = normalize_ohlcv(frame, "VNINDEX", market_source)
    merged = {str(row["date"]): row for row in existing if row.get("date")}
    merged.update({row["date"]: row for row in incoming})
    rows = [merged[key] for key in sorted(merged)][-900:]
    VNINDEX_PATH.parent.mkdir(parents=True, exist_ok=True)
    VNINDEX_PATH.write_text(dumps_json(rows, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    return rows


def append_jsonl(path: Path, rows: list[dict[str, Any]], key: str) -> int:
    existing: dict[str, dict[str, Any]] = {}
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                item = json.loads(line)
                existing[str(item.get(key))] = item
    before = len(existing)
    existing.update({str(row[key]): row for row in rows})
    path.parent.mkdir(parents=True, exist_ok=True)
    body = "".join(dumps_json(row, ensure_ascii=False, separators=(",", ":")) + "\n" for row in existing.values())
    path.write_text(body, encoding="utf-8")
    return len(existing) - before


def defer_unfinalized_daily_close(
    expected_date: date,
    market_date: date,
    raw_release_id: str | None = None,
) -> None:
    """Keep the last valid snapshot when SSI daily bars are not finalized yet."""
    status_path = ROOT / "output" / "vnstock6" / "native-status.json"
    if not status_path.exists():
        raise RuntimeError(
            "VNSTOCK6_DAILY_SOURCE_NOT_FINALIZED_AND_NO_VALID_SNAPSHOT:"
            f"{market_date.isoformat()}:{expected_date.isoformat()}"
        )

    status = json.loads(status_path.read_text(encoding="utf-8"))
    status["daily_close"] = {
        "status": "deferred_source_not_finalized",
        "expected_date": expected_date.isoformat(),
        "market_date": market_date.isoformat(),
        "raw_release_id": raw_release_id,
        "checked_at": datetime.now(timezone.utc).isoformat(),
    }
    status_path.write_text(
        dumps_json(status, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(
        "VNStock6 daily close deferred: "
        f"VNINDEX daily latest={market_date.isoformat()}, "
        f"expected={expected_date.isoformat()}; keeping last valid snapshot"
    )


def run_native(
    config: dict[str, Any], force: bool, intraday: bool = False,
    refresh_slow_market: bool = False, raw_release_id: str | None = None,
) -> None:
    now = datetime.now(ICT)
    today = now.date()
    if today.isoformat() < config["cutover_date"] and not force:
        raise RuntimeError("VNStock6 cutover date has not been reached")
    source_config = config["sources"]
    reference_source = source_config["reference"]
    # SSI remains the only OHLCV source. Slow FHSC proprietary/insider calls
    # are daily-only; intraday consumes their last-known-good cache.
    market_sources = [source_config["market"]["primary"]]
    fundamental_source = source_config["fundamental"]
    universe = list(config["universe"])
    predictions: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    source_counts: dict[str, int] = {source.upper(): 0 for source in market_sources}
    factor_cache = load_fundamental_cache(fundamental_source)
    factor_cache, restored_cash_flow = overlay_legacy_cash_flow(factor_cache, universe)
    market_cache = load_market_factor_cache()
    raw = RawRelease.load(raw_release_id) if raw_release_id else None
    if raw:
        index_frame = raw.frame("index_ohlcv", "VNINDEX")
        index_incoming = normalize_ohlcv(index_frame, "VNINDEX", reference_source)
        existing_index = json.loads(VNINDEX_PATH.read_text(encoding="utf-8")) if VNINDEX_PATH.exists() else []
        merged_index = {str(row["date"]): row for row in existing_index if row.get("date")}
        merged_index.update({row["date"]: row for row in index_incoming})
        index_rows = [merged_index[key] for key in sorted(merged_index)][-900:]
        VNINDEX_PATH.parent.mkdir(parents=True, exist_ok=True)
        VNINDEX_PATH.write_text(dumps_json(index_rows, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    else:
        index_rows = update_vnindex(reference_source, today)
    market_date = today if intraday else date.fromisoformat(str(index_rows[-1]["date"])[:10])
    if not intraday and market_date < today and not force:
        defer_unfinalized_daily_close(
            today,
            market_date,
            raw.release_id if raw else None,
        )
        return
    if raw:
        market_factors = market_factors_from_raw(
            raw, universe, market_date, slow_cache=market_cache,
            refresh_slow=refresh_slow_market, fetch_depth=intraday,
        )
    else:
        market_factors = collect_market_factors(
            universe, market_date, int((config.get("market_indicators") or {}).get("max_workers", 4)),
            slow_cache=market_cache, refresh_slow=refresh_slow_market,
            fetch_depth=intraday,
        )
    snapshot_at = datetime.now(ICT)
    snap_time = scoring_snap_time(snapshot_at, intraday)
    if intraday:
        stamp_live_depth_metadata(
            market_factors, market_date, snap_time, snapshot_at.astimezone(timezone.utc).isoformat(),
        )
    run_kind = "intraday" if intraday else "postmarket"
    versions = list(config.get("scoring_versions") or [config["scoring_version"]])
    unknown_versions = [version for version in versions if version not in PROFILES]
    if unknown_versions:
        raise ValueError(f"Unsupported Gen6 scoring profiles: {unknown_versions}")
    max_age_days = fundamental_ttl_days(config, now)
    for symbol in universe:
        attempts = []
        cached = factor_cache.get(symbol)
        if cached:
            factors = dict(cached)
            factors["cache_stale"] = not cache_entry_is_fresh(cached, max_age_days)
        else:
            factors = {
                "fundamental": None, "growth": None, "cash_flow": None,
                "ratios": {}, "statements": {}, "cache_stale": False,
                "fundamental_reason": "fundamental_cache_unavailable",
                "growth_reason": "fundamental_cache_unavailable",
                "cash_flow_reason": "fundamental_cache_unavailable",
                "engine": "vnstock_quant.fa", "version": "1.0.0",
            }

        for market_source in market_sources:
            try:
                if raw:
                    frame = raw.frame("ohlcv", symbol)
                    incoming = normalize_ohlcv(frame, symbol, market_source)
                    intraday_turnover = None
                    if intraday:
                        live_frame = raw.frame("ohlcv_intraday", symbol)
                        live_rows = normalize_ohlcv(live_frame, symbol, market_source)
                        if not any(row["date"] == today.isoformat() for row in live_rows):
                            raise ValueError(f"No current-session raw intraday OHLC for {symbol}")
                        intraday_turnover = intraday_turnover_value(live_frame, today)
                        incoming.extend(live_rows)
                else:
                    start = market_fetch_start(symbol, today, int(config["history_days"]))
                    equity = Market(market_source).equity(symbol)
                    frame = equity.ohlcv(start=start, interval="1D", compat="v6")
                    incoming = normalize_ohlcv(frame, symbol, market_source)
                    intraday_turnover = None
                    if intraday:
                        live_rows, intraday_turnover = fetch_intraday_ohlcv(
                            equity, symbol, market_source, today, now,
                        )
                        incoming.extend(live_rows)
                merged = merge_ohlcv(symbol, incoming)
                symbol_market = dict(market_factors.get(symbol) or {})
                if intraday_turnover is not None:
                    market_raw = dict(symbol_market.get("raw") or {})
                    market_raw.update({
                        "intraday_turnover_value_estimate": intraday_turnover,
                        "intraday_turnover_as_of": today.isoformat(),
                        "intraday_turnover_method": "sum_5m_close_x_volume",
                        "intraday_turnover_checked_at": snapshot_at.astimezone(timezone.utc).isoformat(),
                    })
                    symbol_market["raw"] = market_raw
                if str(symbol_market.get("depth_signal_date") or "") != str(merged[-1]["date"]):
                    symbol_market["s_depth_wall"] = None
                scored_rows = score_v4_profiles(
                    symbol, merged, versions, snap_time, factors, index_rows,
                    symbol_market, snapshot_at.isoformat(), run_kind,
                )
                if raw:
                    for scored_row in scored_rows:
                        scored_row["raw_release_id"] = raw.release_id
                        scored_row["input_layer"] = "shared_provider_raw"
                predictions.extend(scored_rows)
                source_counts[market_source.upper()] += 1
                break
            except Exception as exc:
                attempts.append({"source": market_source.upper(), "type": type(exc).__name__, "code": getattr(exc, "code", None)})
        else:
            errors.append({"symbol": symbol, "attempts": attempts})

    successful_symbols = len({row["symbol"] for row in predictions})
    if successful_symbols < int(config["minimum_coverage"]):
        raise RuntimeError(f"VNStock6 coverage {successful_symbols}/{len(universe)} below minimum; errors={errors[:10]}")
    partition = PRED_ROOT / f"{predictions[0]['signal_date']}.jsonl"
    added = append_jsonl(partition, predictions, "pred_id")
    primary_rows = [row for row in predictions if row.get("scoring_version") == config["scoring_version"]]
    if intraday:
        for row in primary_rows:
            depth = finite(row.get("s_depth_wall"))
            if depth is None:
                continue
            target = market_factors.setdefault(str(row["symbol"]), {})
            target["s_depth_wall"] = depth
    if intraday or refresh_slow_market:
        save_market_factor_cache(market_factors)
    indicator_coverage = {
        key: sum(row.get(key) is not None for row in primary_rows)
        for key in ("s_ff_net", "s_of_phasefix", "s_prop_5d", "s_insider", "s_depth_wall", "s_cf_core")
    }
    status = {
        "schema_version": 1, "generated_at": datetime.now(timezone.utc).isoformat(),
        "raw_release_id": raw.release_id if raw else None,
        "input_layer": "shared_provider_raw" if raw else "direct_provider",
        "raw_cadence": raw.manifest.get("cadence") if raw else None,
        "scoring_version": config["scoring_version"], "scoring_versions": versions, "universe_size": len(universe),
        "sources": {"reference": reference_source.upper(), "market_counts": source_counts, "fundamental": fundamental_source.upper()},
        "fundamental_status": "cache_scored", "fundamental_cache_max_age_days": max_age_days,
        "fundamental_cache_symbols": len(factor_cache),
        "cash_flow_overlay_symbols": restored_cash_flow,
        "slow_market_cache_symbols": len(market_cache), "slow_market_refreshed": refresh_slow_market,
        "market_factor_date": market_date.isoformat(),
        "fundamental_stale_cache_used": sum(
            bool(value) and not cache_entry_is_fresh(value, max_age_days)
            for value in factor_cache.values()
        ),
        "fundamental_symbols_refreshed": 0,
        "market_indicator_coverage": indicator_coverage,
        "session_stats_probe": next((
            value.get("session_stats_probe") for value in market_factors.values()
            if value.get("session_stats_probe")
        ), None),
        "depth_input_coverage": sum(
            bool((value.get("raw") or {}).get("order_book"))
            and finite((value.get("raw") or {}).get("average_trade_size")) is not None
            for value in market_factors.values()
        ),
        "successful_symbols": successful_symbols, "prediction_rows": len(predictions),
        "vnindex_rows": len(index_rows), "failed_symbols": errors, "records_added": added,
    }
    if not intraday:
        status["daily_close"] = {
            "status": "finalized",
            "expected_date": today.isoformat(),
            "market_date": market_date.isoformat(),
            "raw_release_id": raw.release_id if raw else None,
            "checked_at": datetime.now(timezone.utc).isoformat(),
        }
    status_path = ROOT / "output" / "vnstock6" / "native-status.json"
    status_path.parent.mkdir(parents=True, exist_ok=True)
    status_path.write_text(dumps_json(status, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(
        f"VNStock6 native: {successful_symbols}/{len(universe)} symbols, "
        f"{len(predictions)} prediction rows, {added} new predictions"
    )


def evaluate(config: dict[str, Any]) -> None:
    predictions = []
    for path in sorted(PRED_ROOT.glob("*.jsonl")):
        predictions.extend(json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip())
    outcomes: list[dict[str, Any]] = []
    for prediction in predictions:
        bars = json.loads((OHLC_ROOT / f"{prediction['symbol']}.json").read_text(encoding="utf-8"))
        later = [row for row in bars if str(row.get("date")) > prediction["signal_date"]]
        entry = finite(prediction.get("price"))
        if not entry or not later:
            continue
        row = {"pred_id": prediction["pred_id"], "symbol": prediction["symbol"], "scoring_version": config["scoring_version"], "lens": "trade", "pipeline_generation": 6, "market_source": prediction.get("market_source"), "n_bars": len(later), "eval_date": later[-1]["date"]}
        row["scoring_version"] = prediction["scoring_version"]
        for horizon in (1, 3, 5, 10):
            row[f"ret_{horizon}d"] = round((float(later[horizon - 1]["close"]) / entry - 1) * 100, 6) if len(later) >= horizon else None
        outcomes.append(row)
    if outcomes:
        by_month: dict[str, list[dict[str, Any]]] = {}
        for row in outcomes:
            by_month.setdefault(str(row["eval_date"])[:7], []).append(row)
        for month, rows in by_month.items():
            append_jsonl(OUTCOME_ROOT / f"{month}.jsonl", rows, "pred_id")
    print(f"VNStock6 outcomes updated: {len(outcomes)}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("run", "evaluate", "fundamentals"))
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--intraday", action="store_true")
    parser.add_argument("--refresh-slow-market", action="store_true")
    parser.add_argument("--raw-release-id")
    parser.add_argument("--fundamental-limit", type=int)
    parser.add_argument("--stale-only", action="store_true")
    parser.add_argument("--check-updates", action="store_true")
    args = parser.parse_args()
    config = load_config()
    if args.command == "run":
        run_native(config, args.force, args.intraday, args.refresh_slow_market, args.raw_release_id)
    elif args.command == "fundamentals":
        if args.raw_release_id:
            refresh_fundamental_cache_from_raw(
                config, RawRelease.load(args.raw_release_id), args.fundamental_limit
            )
        else:
            refresh_fundamental_cache(
                config, args.fundamental_limit, args.stale_only, args.check_updates
            )
    else:
        evaluate(config)


if __name__ == "__main__":
    main()
