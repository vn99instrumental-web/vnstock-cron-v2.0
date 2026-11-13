"""Independent generation-6 SSI OHLC, technical scoring, ledger and outcomes.

Historical generation-4/5 ledgers remain immutable. New records are written only
under output/history/vnstock6 and carry explicit generation/source provenance.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pandas as pd
from vnstock import Fundamental, Market, Reference, sources
from vnstock.errors import VnstockError

from vnstock6_scoring import availability_score
from vnstock6_quant import fundamental_factors, technical_indicators
from vnstock6_market_factors import fetch_symbol as fetch_market_factors
from vnstock6_v4_scoring import (
    PROFILES, classify_regime, factor_values, indicator_snapshot, score_profile, signal_values,
)

ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / "config" / "vnstock6.json"
PRED_ROOT = ROOT / "output" / "history" / "vnstock6" / "predictions"
OUTCOME_ROOT = ROOT / "output" / "history" / "vnstock6" / "outcomes"
OHLC_ROOT = ROOT / "output" / "ohlc"
FUNDAMENTAL_CACHE = ROOT / "output" / "vnstock6" / "fundamental-factors.json"
MARKET_FACTOR_CACHE = ROOT / "output" / "vnstock6" / "market-factors.json"
VNINDEX_PATH = ROOT / "output" / "market" / "vnindex.json"
ICT = timezone(timedelta(hours=7))

def load_config() -> dict[str, Any]:
    value = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    sources_config = value.get("sources") or {}
    if sources_config.get("reference") != "ssi" or sources_config.get("fundamental") != "fhsc" or not value.get("universe"):
        raise ValueError("VNStock6 config must declare SSI reference/market and FHSC fundamental sources")
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
    }
    for route, source in route_sources.items():
        readers = {str(item).lower() for item in sources.readers(route)}
        if source not in readers:
            raise ValueError(f"VNStock6 source {source} cannot read {route}")
    return value


def finite(value: Any) -> float | None:
    try:
        number = float(value)
        return number if math.isfinite(number) else None
    except (TypeError, ValueError):
        return None


def load_fundamental_cache(source: str) -> dict[str, Any]:
    if not FUNDAMENTAL_CACHE.exists():
        return {}
    value = json.loads(FUNDAMENTAL_CACHE.read_text(encoding="utf-8"))
    if str(value.get("source", "")).lower() != source.lower():
        return {}
    return dict(value.get("symbols") or {})


def save_fundamental_cache(source: str, factors: dict[str, Any]) -> None:
    FUNDAMENTAL_CACHE.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": 1, "generated_at": datetime.now(timezone.utc).isoformat(),
        "source": source.upper(), "calculation_engine": "vnstock_quant",
        "calculation_version": "1.1.0", "symbols": dict(sorted(factors.items())),
    }
    FUNDAMENTAL_CACHE.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
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
    refreshed_at = entry.get("refreshed_at")
    if not refreshed_at:
        return False
    try:
        refreshed = datetime.fromisoformat(str(refreshed_at).replace("Z", "+00:00"))
        if refreshed.tzinfo is None:
            refreshed = refreshed.replace(tzinfo=timezone.utc)
        return datetime.now(timezone.utc) - refreshed <= timedelta(days=max_age_days)
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
    config: dict[str, Any], limit: int | None = None, stale_only: bool = False
) -> dict[str, Any]:
    """Refresh all FHSC statements, or only stale/missing symbols for daily maintenance."""
    source_config = config["sources"]
    reference_source = source_config["reference"]
    fundamental_source = source_config["fundamental"]
    factor_cache = load_fundamental_cache(fundamental_source)
    ttl_days = fundamental_ttl_days(config)
    configured = (
        stale_fundamental_symbols(config, factor_cache)
        if stale_only else list(config["universe"])
    )

    reference = Reference(reference_source).equity.list() if configured else pd.DataFrame()
    symbol_column = next((column for column in reference.columns if str(column).lower() == "symbol"), None)
    industry_column = next((column for column in reference.columns if str(column).lower() in {"industry", "industry_name", "icb_name3", "icb_name2"}), None)
    industry_map = {str(row[symbol_column]).upper(): str(row[industry_column]) for _, row in reference.iterrows()} if symbol_column and industry_column else {}
    if stale_only:
        universe = list(config["universe"])
        selected = configured if limit is None else configured[:limit]
    else:
        if symbol_column is None: raise ValueError("SSI reference schema missing symbol column")
        available = {str(value).upper() for value in reference[symbol_column].dropna()}
        universe = [symbol for symbol in config["universe"] if symbol in available]
        selected = universe if limit is None else universe[:limit]

    results: dict[str, Any] = {}
    for symbol in selected:
        previous = factor_cache.get(symbol)
        last_result: dict[str, Any] | None = None
        for attempt in range(1, 4):
            last_result = fundamental_factors(symbol, fundamental_source, industry_map.get(symbol))
            if not last_result.get("error"):
                last_result["refreshed_at"] = datetime.now(timezone.utc).isoformat()
                factor_cache[symbol] = last_result
                results[symbol] = {"status": "success", "attempt": attempt}
                break
            if attempt < 3:
                time.sleep(attempt)
        else:
            results[symbol] = {
                "status": "failed_preserved" if previous else "failed",
                "attempt": 3,
                "type": (last_result or {}).get("error", {}).get("type"),
                "code": (last_result or {}).get("error", {}).get("code"),
            }

    if selected:
        save_fundamental_cache(fundamental_source, factor_cache)
    counts = {
        "success": sum(item["status"] == "success" for item in results.values()),
        "failed": sum(item["status"] == "failed" for item in results.values()),
        "failed_preserved": sum(item["status"] == "failed_preserved" for item in results.values()),
        "skipped_fresh": len(config["universe"]) - len(configured) if stale_only else 0,
    }
    status = {
        "schema_version": 1, "generated_at": datetime.now(timezone.utc).isoformat(),
        "reference_source": reference_source.upper(), "fundamental_source": fundamental_source.upper(),
        "configured_symbols": len(config["universe"]), "reference_symbols_available": len(universe),
        "symbols_requested": len(selected), "cache_symbols": len(factor_cache),
        "stale_only": stale_only, "ttl_days": ttl_days,
        "counts": counts, "symbols": results,
    }
    status_path = ROOT / "output" / "vnstock6" / "fundamental-status.json"
    status_path.parent.mkdir(parents=True, exist_ok=True)
    status_path.write_text(json.dumps(status, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(
        f"VNStock6 fundamentals: {counts['success']}/{len(selected)} refreshed, "
        f"{counts['failed']} failed, {counts['failed_preserved']} preserved, ttl={ttl_days}d"
    )
    return status

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
    path.write_text(json.dumps(result, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
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
    fundamentals: dict[str, Any], index_rows: list[dict[str, Any]], market_factors: dict[str, Any] | None = None,
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
    signals = signal_values(indicators, fundamentals, regime_info["regime"], market_factors)
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
            "scoring_version": version, "price": current,
            "pipeline_generation": 6, "reference_source": "SSI",
            "market_source": str(latest.get("market_source") or "UNKNOWN"),
            "fundamental_source": "FHSC", "data_origin": "native",
            "flow": "vnstock6_native_v4_profiles", "universe_variant": "vn100-hose",
            "registry_version": 3, "gate_version": 7,
            "regime_as_of": regime_info.get("as_of"), "regime_method": regime_info.get("reason"),
            **indicators, **levels, **signals, **scored,
            "market_factor_provenance": {key: (market_factors or {}).get(key) for key in ("source", "refreshed_at", "errors", "raw")},
            "fundamental_score": signals.get("s_fund_core"), "growth_score": signals.get("s_growth_core"),
            "ratio_roe": ratios.get("RT_PRT_ROE"), "ratio_roa": ratios.get("RT_PRT_ROA"),
            "ratio_gross_margin": ratios.get("RT_PRT_GROSS_MARGIN"), "ratio_net_margin": ratios.get("RT_PRT_NET_MARGIN"),
            "ratio_current": ratios.get("RT_LQD_CR"), "ratio_debt_equity": ratios.get("RT_LEV_DE"),
            "fundamental_status": "scored" if fundamentals.get("fundamental") is not None else "excluded",
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
    VNINDEX_PATH.write_text(json.dumps(rows, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
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
    body = "".join(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n" for row in existing.values())
    path.write_text(body, encoding="utf-8")
    return len(existing) - before


def run_native(config: dict[str, Any], force: bool, intraday: bool = False) -> None:
    now = datetime.now(ICT)
    today = now.date()
    if today.isoformat() < config["cutover_date"] and not force:
        raise RuntimeError("VNStock6 cutover date has not been reached")
    source_config = config["sources"]
    reference_source = source_config["reference"]
    market_sources = [source_config["market"]["primary"], source_config["market"]["fallback"]]
    fundamental_source = source_config["fundamental"]
    universe = list(config["universe"])
    predictions: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    source_counts: dict[str, int] = {source.upper(): 0 for source in market_sources}
    factor_cache = load_fundamental_cache(fundamental_source)
    market_factor_cache = json.loads(MARKET_FACTOR_CACHE.read_text(encoding="utf-8")).get("symbols", {}) if MARKET_FACTOR_CACHE.exists() else {}
    versions = list(config.get("scoring_versions") or [config["scoring_version"]])
    unknown_versions = [version for version in versions if version not in PROFILES]
    if unknown_versions:
        raise ValueError(f"Unsupported Gen6 scoring profiles: {unknown_versions}")
    index_rows = update_vnindex(reference_source, today)
    max_age_days = fundamental_ttl_days(config, now)
    for symbol in universe:
        attempts = []
        cached = factor_cache.get(symbol)
        factors = cached if cached and cache_entry_is_fresh(cached, max_age_days) else {
            "fundamental": None, "growth": None, "cash_flow": None, "ratios": {}, "statements": {},
            "fundamental_reason": "fundamental_cache_stale" if cached else "fundamental_cache_unavailable",
            "growth_reason": "fundamental_cache_stale" if cached else "fundamental_cache_unavailable",
            "cash_flow_reason": "fundamental_cache_stale" if cached else "fundamental_cache_unavailable",
            "engine": "vnstock_quant.fa", "version": "1.0.0",
        }
        previous_market = market_factor_cache.get(symbol) or {}
        try:
            current_market = fetch_market_factors(symbol, today, intraday)
            for key in ("s_ff_net", "s_of_phasefix", "s_prop_5d", "s_insider"):
                if current_market.get(key) is None and previous_market.get(key) is not None: current_market[key] = previous_market[key]
            market_factor_cache[symbol] = current_market
        except Exception as exc:
            current_market = dict(previous_market)
            current_market.setdefault("errors", {})["collector"] = {"type": type(exc).__name__, "code": getattr(exc, "code", None), "action": getattr(exc, "action", None)}
        for market_source in market_sources:
            try:
                start = market_fetch_start(symbol, today, int(config["history_days"]))
                equity = Market(market_source).equity(symbol)
                frame = equity.ohlcv(start=start, interval="1D", compat="v6")
                incoming = normalize_ohlcv(frame, symbol, market_source)
                if intraday:
                    live = equity.ohlcv(
                        start=today.isoformat(), end=now.isoformat(), interval="5m", compat="v6"
                    )
                    live_rows = normalize_ohlcv(live, symbol, market_source)
                    if not any(row["date"] == today.isoformat() for row in live_rows):
                        raise ValueError(f"No current-session intraday OHLC for {symbol} from {market_source}")
                    incoming.extend(live_rows)
                merged = merge_ohlcv(symbol, incoming)
                predictions.extend(score_v4_profiles(symbol, merged, versions, now.strftime("%H:%M"), factors, index_rows, current_market))
                source_counts[market_source.upper()] += 1
                break
            except Exception as exc:
                attempts.append({"source": market_source.upper(), "type": type(exc).__name__, "code": getattr(exc, "code", None)})
        else:
            errors.append({"symbol": symbol, "attempts": attempts})
    MARKET_FACTOR_CACHE.parent.mkdir(parents=True, exist_ok=True)
    MARKET_FACTOR_CACHE.write_text(json.dumps({"schema_version": 1, "generated_at": datetime.now(timezone.utc).isoformat(), "symbols": market_factor_cache}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    successful_symbols = len({row["symbol"] for row in predictions})
    if successful_symbols < int(config["minimum_coverage"]):
        raise RuntimeError(f"VNStock6 coverage {successful_symbols}/{len(universe)} below minimum; errors={errors[:10]}")
    partition = PRED_ROOT / f"{predictions[0]['signal_date']}.jsonl"
    added = append_jsonl(partition, predictions, "pred_id")
    status = {
        "schema_version": 1, "generated_at": datetime.now(timezone.utc).isoformat(),
        "scoring_version": config["scoring_version"], "scoring_versions": versions, "universe_size": len(universe),
        "sources": {"reference": reference_source.upper(), "market_counts": source_counts, "fundamental": fundamental_source.upper()},
        "fundamental_status": "cache_scored", "fundamental_cache_max_age_days": max_age_days,
        "fundamental_cache_symbols": len(factor_cache),
        "fundamental_symbols_refreshed": 0,
        "successful_symbols": successful_symbols, "prediction_rows": len(predictions),
        "vnindex_rows": len(index_rows), "failed_symbols": errors, "records_added": added,
    }
    status_path = ROOT / "output" / "vnstock6" / "native-status.json"
    status_path.parent.mkdir(parents=True, exist_ok=True)
    status_path.write_text(json.dumps(status, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"VNStock6 native: {len(predictions)}/{len(universe)} symbols, {added} new predictions")


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
    parser.add_argument("--fundamental-limit", type=int)
    parser.add_argument("--stale-only", action="store_true")
    args = parser.parse_args()
    config = load_config()
    if args.command == "run":
        run_native(config, args.force, args.intraday)
    elif args.command == "fundamentals":
        refresh_fundamental_cache(config, args.fundamental_limit, args.stale_only)
    else:
        evaluate(config)


if __name__ == "__main__":
    main()
