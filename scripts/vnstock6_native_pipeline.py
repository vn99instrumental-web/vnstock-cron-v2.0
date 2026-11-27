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
        probe: dict[str, Any×M}ÞÚ$z{-®éÜj×&öG’Ò""æ¦ö–â†GV×5ö§6öâ‡&÷rÂVç7W&Uö66–“ÔfÇ6RÂ6W&F÷'3Ò‚"Â"Â#¢"’’²%Æâ"f÷"&÷r–âW†—7F–ærçfÇVW2‚’Ð¢F‚çw&—FU÷FW‡B†&öG’ÂVæ6öF–æsÒ'WFbÓ‚"Ð¢&WGW&âÆVâ†W†—7F–ær’Ò&Vf÷&PÐ Ð Ð¦FVbFVfW%÷Væf–æÆ—¦VEöF–Ç•ö6Æ÷6R€¢W‡V7FVEöFFS¢FFRÀ¢Ö&¶WEöFFS¢FFRÀ¢&u÷&VÆV6Uö–C¢7G"ÂæöæRÒæöæRÀ¢’ÓâæöæS ¢""$¶VWF†RÆ7BfÆ–B6æ6†÷Bv†Vâ54’F–Ç’&'2&Ræ÷Bf–æÆ—¦VB–WBâ"" ¢7FGW5÷F‚Ò$ôõBò&÷WGWB"ò'fç7Fö6³b"ò&æF—fR×7FGW2æ§6öâ ¢–bæ÷B7FGW5÷F‚æW†—7G2‚“ ¢&—6R'VçF–ÖTW'&÷"€¢%då5Dô4³eôD”Å•õ4õU$4UôäõEôd”äÄ•¤TEôäEôäõõdÄ”Eõ4ä4„õC¢ ¢b'¶Ö&¶WEöFFRæ—6öf÷&ÖB‚—Ó§¶W‡V7FVEöFFRæ—6öf÷&ÖB‚—Ò ¢ ¢7FGW2Ò§6öâæÆöG2‡7FGW5÷F‚ç&VE÷FW‡B†Væ6öF–æsÒ'WFbÓ‚"’¢7FGW5²&F–Ç•ö6Æ÷6R%ÒÒ°¢'7FGW2#¢&FVfW'&VE÷6÷W&6Uöæ÷Eöf–æÆ—¦VB"À¢&W‡V7FVEöFFR#¢W‡V7FVEöFFRæ—6öf÷&ÖB‚’À¢&Ö&¶WEöFFR#¢Ö&¶WEöFFRæ—6öf÷&ÖB‚’À¢'&u÷&VÆV6Uö–B#¢&u÷&VÆV6Uö–BÀ¢&6†V6¶VEöB#¢FFWF–ÖRææ÷r‡F–ÖW¦öæRçWF2’æ—6öf÷&ÖB‚’À¢Ð¢7FGW5÷F‚çw&—FU÷FW‡B€¢GV×5ö§6öâ‡7FGW2ÂVç7W&Uö66–“ÔfÇ6RÂ–æFVçCÓ"’²%Æâ"À¢Væ6öF–æsÒ'WFbÓ‚"À¢¢&–çB€¢%då7Fö6³bF–Ç’6Æ÷6RFVfW'&VC¢ ¢b%dä”äDU‚F–Ç’ÆFW7C×¶Ö&¶WEöFFRæ—6öf÷&ÖB‚—ÒÂ ¢b&W‡V7FVC×¶W‡V7FVEöFFRæ—6öf÷&ÖB‚—Ó²¶VW–ærÆ7BfÆ–B6æ6†÷B ¢Ð Ð Ð¦FVb'VåöæF—fR€Ð¢6öæf–s¢F–7E·7G"Âç•ÒÂf÷&6S¢&ööÂÂ–çG&F“¢&ööÂÒfÇ6RÀÐ¢&Vg&W6…÷6Æ÷uöÖ&¶WC¢&ööÂÒfÇ6RÂ&u÷&VÆV6Uö–C¢7G"ÂæöæRÒæöæRÀÐ¢’ÓâæöæS Ð¢æ÷rÒFFWF–ÖRææ÷r„”5BÐ¢FöF’Òæ÷ræFFR‚Ð¢–bFöF’æ—6öf÷&ÖB‚’Â6öæf–u²&7WF÷fW%öFFR%ÒæBæ÷Bf÷&6S Ð¢&—6R'VçF–ÖTW'&÷"‚%då7Fö6³b7WF÷fW"FFR†2æ÷B&VVâ&V6†VB"Ð¢6÷W&6Uö6öæf–rÒ6öæf–u²'6÷W&6W2%ÐÐ¢&VfW&Væ6U÷6÷W&6RÒ6÷W&6Uö6öæf–u²'&VfW&Væ6R%ÐÐ¢254’&VÖ–ç2F†RöæÇ’ô„Ä5b6÷W&6Râ6Æ÷rd…42&÷&–WF'’ö–ç6–FW"6ÆÇ0Ð¢2&RF–Ç’ÖöæÇ“²–çG&F’6öç7VÖW2F†V—"Æ7BÖ¶æ÷vâÖvööB66†RàÐ¢Ö&¶WE÷6÷W&6W2Ò·6÷W&6Uö6öæf–u²&Ö&¶WB%Õ²'&–Ö'’%ÕÐÐ¢gVæFÖVçFÅ÷6÷W&6RÒ6÷W&6Uö6öæf–u²&gVæFÖVçFÂ%ÐÐ¢Væ—fW'6RÒÆ—7B†6öæf–u²'Væ—fW'6R%ÒÐ¢&VF–7F–öç3¢Æ—7E¶F–7E·7G"Âç•ÕÒÒµÐÐ¢W'&÷'3¢Æ—7E¶F–7E·7G"Âç•ÕÒÒµÐÐ¢6÷W&6Uö6÷VçG3¢F–7E·7G"Â–çEÒÒ·6÷W&6RçWW"‚“¢f÷"6÷W&6R–âÖ&¶WE÷6÷W&6W7ÐÐ¢f7F÷%ö66†RÒÆöEögVæFÖVçFÅö66†R†gVæFÖVçFÅ÷6÷W&6RÐ¢f7F÷%ö66†RÂ&W7F÷&VEö66…öfÆ÷rÒ÷fW&Æ•öÆVv7•ö66…öfÆ÷r†f7F÷%ö66†RÂVæ—fW'6RÐ¢Ö&¶WEö66†RÒÆöEöÖ&¶WEöf7F÷%ö66†R‚Ð¢&rÒ&u&VÆV6RæÆöB‡&u÷&VÆV6Uö–B’–b&u÷&VÆV6Uö–BVÇ6RæöæPÐ¢–b&s Ð¢–æFW…ög&ÖRÒ&ræg&ÖR‚&–æFW…öö†Æ7b"Â%dä”äDU‚"Ð¢–æFW…ö–æ6öÖ–ærÒæ÷&ÖÆ—¦Uöö†Æ7b†–æFW…ög&ÖRÂ%dä”äDU‚"Â&VfW&Væ6U÷6÷W&6RÐ¢W†—7F–æuö–æFW‚Ò§6öâæÆöG2…dä”äDU…õD‚ç&VE÷FW‡B†Væ6öF–æsÒ'WFbÓ‚"’’–bdä”äDU…õD‚æW†—7G2‚’VÇ6RµÐÐ¢ÖW&vVEö–æFW‚Ò·7G"‡&÷u²&FFR%Ò“¢&÷rf÷"&÷r–âW†—7F–æuö–æFW‚–b&÷rævWB‚&FFR"—ÐÐ¢ÖW&vVEö–æFW‚çWFFR‡·&÷u²&FFR%Ó¢&÷rf÷"&÷r–â–æFW…ö–æ6öÖ–æwÒÐ¢–æFW…÷&÷w2Ò¶ÖW&vVEö–æFW…¶¶W•Òf÷"¶W’–â6÷'FVB†ÖW&vVEö–æFW‚•Õ²Ó“¥ÐÐ¢dä”äDU…õD‚ç&VçBæÖ¶F—"‡&VçG3ÕG'VRÂW†—7Eöö³ÕG'VRÐ¢dä”äDU…õD‚çw&—FU÷FW‡B†GV×5ö§6öâ†–æFW…÷&÷w2ÂVç7W&Uö66–“ÔfÇ6RÂ6W&F÷'3Ò‚"Â"Â#¢"’’ÂVæ6öF–æsÒ'WFbÓ‚"Ð¢VÇ6S Ð¢–æFW…÷&÷w2ÒWFFU÷fæ–æFW‚‡&VfW&Væ6U÷6÷W&6RÂFöF’Ð¢Ö&¶WEöFFRÒFöF’–b–çG&F’VÇ6RFFRæg&öÖ—6öf÷&ÖB‡7G"†–æFW…÷&÷w5²ÓÕ²&FFR%Ò•³£ÒÐ¢–bæ÷B–çG&F’æBÖ&¶WEöFFRÂFöF’æBæ÷Bf÷&6S ¢FVfW%÷Væf–æÆ—¦VEöF–Ç•ö6Æ÷6R€¢FöF’À¢Ö&¶WEöFFRÀ¢&rç&VÆV6Uö–B–b&rVÇ6RæöæRÀ¢¢&WGW&àÐ¢–b&s Ð¢Ö&¶WEöf7F÷'2ÒÖ&¶WEöf7F÷'5ög&öÕ÷&r€Ð¢&rÂVæ—fW'6RÂÖ&¶WEöFFRÂ6Æ÷uö66†SÖÖ&¶WEö66†RÀÐ¢&Vg&W6…÷6Æ÷s×&Vg&W6…÷6Æ÷uöÖ&¶WBÂfWF6…öFWFƒÖ–çG&F’ÀÐ¢Ð¢VÇ6S Ð¢Ö&¶WEöf7F÷'2Ò6öÆÆV7EöÖ&¶WEöf7F÷'2€Ð¢Væ—fW'6RÂÖ&¶WEöFFRÂ–çB‚†6öæf–rævWB‚&Ö&¶WEö–æF–6F÷'2"’÷"·Ò’ævWB‚&Ö…÷v÷&¶W'2"ÂB’’ÀÐ¢6Æ÷uö66†SÖÖ&¶WEö66†RÂ&Vg&W6…÷6Æ÷s×&Vg&W6…÷6Æ÷uöÖ&¶WBÀÐ¢fWF6…öFWFƒÖ–çG&F’ÀÐ¢¢6æ6†÷EöBÒFFWF–ÖRææ÷r„”5B¢6æ÷F–ÖRÒ66÷&–æu÷6æ÷F–ÖR‡6æ6†÷EöBÂ–çG&F’¢–b–çG&F“ ¢7F×öÆ—fUöFWF…öÖWFFF€¢Ö&¶WEöf7F÷'2ÂÖ&¶WEöFFRÂ6æ÷F–ÖRÂ6æ6†÷EöBæ7F–ÖW¦öæR‡F–ÖW¦öæRçWF2’æ—6öf÷&ÖB‚’À¢¢'Våö¶–æBÒ&–çG&F’"–b–çG&F’VÇ6R'÷7FÖ&¶WB ¢fW'6–öç2ÒÆ—7B†6öæf–rævWB‚'66÷&–æu÷fW'6–öç2"’÷"¶6öæf–u²'66÷&–æu÷fW'6–öâ%ÕÒÐ¢Væ¶æ÷vå÷fW'6–öç2Ò·fW'6–öâf÷"fW'6–öâ–âfW'6–öç2–bfW'6–öâæ÷B–â$ôd”ÄU5ÐÐ¢–bVæ¶æ÷vå÷fW'6–öç3 Ð¢&—6RfÇVTW'&÷"†b%Vç7W÷'FVBvVãb66÷&–ær&öf–ÆW3¢·Væ¶æ÷vå÷fW'6–öç7Ò"Ð¢Ö…övUöF—2ÒgVæFÖVçFÅ÷GFÅöF—2†6öæf–rÂæ÷r¢f÷"7–Ö&öÂ–âVæ—fW'6S Ð¢GFV×G2ÒµÐÐ¢66†VBÒf7F÷%ö66†RævWB‡7–Ö&öÂÐ¢–b66†VC Ð¢f7F÷'2ÒF–7B†66†VBÐ¢f7F÷'5²&66†U÷7FÆR%ÒÒæ÷B66†UöVçG'•ö—5ög&W6‚†66†VBÂÖ…övUöF—2Ð¢VÇ6S Ð¢f7F÷'2Ò°Ð¢&gVæFÖVçFÂ#¢æöæRÂ&w&÷wF‚#¢æöæRÂ&66…öfÆ÷r#¢æöæRÀÐ¢'&F–÷2#¢·ÒÂ'7FFVÖVçG2#¢·ÒÂ&66†U÷7FÆR#¢fÇ6RÀÐ¢&gVæFÖVçFÅ÷&V6öâ#¢&gVæFÖVçFÅö66†U÷Væf–Æ&ÆR"ÀÐ¢&w&÷wF…÷&V6öâ#¢&gVæFÖVçFÅö66†U÷Væf–Æ&ÆR"ÀÐ¢&66…öfÆ÷u÷&V6öâ#¢&gVæFÖVçFÅö66†U÷Væf–Æ&ÆR"ÀÐ¢&Væv–æR#¢'fç7Fö6µ÷VçBæf"Â'fW'6–öâ#¢#ãã"ÀÐ¢ÐÐ Ð¢f÷"Ö&¶WE÷6÷W&6R–âÖ&¶WE÷6÷W&6W3 Ð¢G'“ Ð¢–b&s Ð¢g&ÖRÒ&ræg&ÖR‚&ö†Æ7b"Â7–Ö&öÂÐ¢–æ6öÖ–ærÒæ÷&ÖÆ—¦Uöö†Æ7b†g&ÖRÂ7–Ö&öÂÂÖ&¶WE÷6÷W&6RÐ¢–çG&F•÷GW&æ÷fW"ÒæöæPÐ¢–b–çG&F“ Ð¢Æ—fUög&ÖRÒ&ræg&ÖR‚&ö†Æ7eö–çG&F’"Â7–Ö&öÂÐ¢Æ—fU÷&÷w2Òæ÷&ÖÆ—¦Uöö†Æ7b†Æ—fUög&ÖRÂ7–Ö&öÂÂÖ&¶WE÷6÷W&6RÐ¢–bæ÷Bç’‡&÷u²&FFR%ÒÓÒFöF’æ—6öf÷&ÖB‚’f÷"&÷r–âÆ—fU÷&÷w2“ Ð¢&—6RfÇVTW'&÷"†b$æò7W'&VçB×6W76–öâ&r–çG&F’ô„Ä2f÷"·7–Ö&öÇÒ"Ð¢–çG&F•÷GW&æ÷fW"Ò–çG&F•÷GW&æ÷fW%÷fÇVR†Æ—fUög&ÖRÂFöF’Ð¢–æ6öÖ–æræW‡FVæB†Æ—fU÷&÷w2Ð¢VÇ6S Ð¢7F'BÒÖ&¶WEöfWF6…÷7F'B‡7–Ö&öÂÂFöF’Â–çB†6öæf–u²&†—7F÷'•öF—2%Ò’Ð¢WV—G’ÒÖ&¶WB†Ö&¶WE÷6÷W&6R’æWV—G’‡7–Ö&öÂÐ¢g&ÖRÒWV—G’æö†Æ7b‡7F'C×7F'BÂ–çFW'fÃÒ#B"Â6ö×CÒ'cb"Ð¢–æ6öÖ–ærÒæ÷&ÖÆ—¦Uöö†Æ7b†g&ÖRÂ7–Ö&öÂÂÖ&¶WE÷6÷W&6RÐ¢–çG&F•÷GW&æ÷fW"ÒæöæPÐ¢–b–çG&F“ Ð¢Æ—fU÷&÷w2Â–çG&F•÷GW&æ÷fW"ÒfWF6…ö–çG&F•öö†Æ7b€Ð¢WV—G’Â7–Ö&öÂÂÖ&¶WE÷6÷W&6RÂFöF’Âæ÷rÀÐ¢Ð¢–æ6öÖ–æræW‡FVæB†Æ—fU÷&÷w2¢ÖW&vVBÒÖW&vUöö†Æ7b‡7–Ö&öÂÂ–æ6öÖ–ær¢7–Ö&öÅöÖ&¶WBÒF–7B†Ö&¶WEöf7F÷'2ævWB‡7–Ö&öÂ’÷"·Ò¢–b–çG&F•÷GW&æ÷fW"—2æ÷BæöæS ¢Ö&¶WE÷&rÒF–7B‡7–Ö&öÅöÖ&¶WBævWB‚'&r"’÷"·Ò¢Ö&¶WE÷&rçWFFR‡°¢&–çG&F•÷GW&æ÷fW%÷fÇVUöW7F–ÖFR#¢–çG&F•÷GW&æ÷fW"À¢&–çG&F•÷GW&æ÷fW%ö5ööb#¢FöF’æ—6öf÷&ÖB‚’À¢&–çG&F•÷GW&æ÷fW%öÖWF†öB#¢'7VÕóVÕö6Æ÷6U÷…÷föÇVÖR"À¢&–çG&F•÷GW&æ÷fW%ö6†V6¶VEöB#¢6æ6†÷EöBæ7F–ÖW¦öæR‡F–ÖW¦öæRçWF2’æ—6öf÷&ÖB‚’À¢Ò¢7–Ö&öÅöÖ&¶WE²'&r%ÒÒÖ&¶WE÷&p¢–b7G"‡7–Ö&öÅöÖ&¶WBævWB‚&FWF…÷6–væÅöFFR"’÷"""’Ò7G"†ÖW&vVE²ÓÕ²&FFR%Ò“ ¢7–Ö&öÅöÖ&¶WE²'5öFWF…÷vÆÂ%ÒÒæöæP¢66÷&VE÷&÷w2Ò66÷&U÷cE÷&öf–ÆW2€Ð¢7–Ö&öÂÂÖW&vVBÂfW'6–öç2Â6æ÷F–ÖRÂf7F÷'2Â–æFW…÷&÷w2ÀÐ¢7–Ö&öÅöÖ&¶WBÂ6æ6†÷EöBæ—6öf÷&ÖB‚’Â'Våö¶–æBÀÐ¢Ð¢–b&s Ð¢f÷"66÷&VE÷&÷r–â66÷&VE÷&÷w3 Ð¢66÷&VE÷&÷u²'&u÷&VÆV6Uö–B%ÒÒ&rç&VÆV6Uö–@Ð¢66÷&VE÷&÷u²&–çWEöÆ–W"%ÒÒ'6†&VE÷&÷f–FW%÷&r Ð¢&VF–7F–öç2æW‡FVæB‡66÷&VE÷&÷w2¢6÷W&6Uö6÷VçG5¶Ö&¶WE÷6÷W&6RçWW"‚•Ò³ÒÐ¢'&V°Ð¢W†6WBW†6WF–öâ2W†3 Ð¢GFV×G2æVæB‡²'6÷W&6R#¢Ö&¶WE÷6÷W&6RçWW"‚’Â'G—R#¢G—R†W†2’åõöæÖUõòÂ&6öFR#¢vWFGG"†W†2Â&6öFR"ÂæöæR—ÒÐ¢VÇ6S Ð¢W'&÷'2æVæB‡²'7–Ö&öÂ#¢7–Ö&öÂÂ&GFV×G2#¢GFV×G7ÒÐ Ð¢7V66W76gVÅ÷7–Ö&öÇ2ÒÆVâ‡·&÷u²'7–Ö&öÂ%Òf÷"&÷r–â&VF–7F–öç7ÒÐ¢–b7V66W76gVÅ÷7–Ö&öÇ2Â–çB†6öæf–u²&Ö–æ–×VÕö6÷fW&vR%Ò“ Ð¢&—6R'VçF–ÖTW'&÷"†b%då7Fö6³b6÷fW&vR·7V66W76gVÅ÷7–Ö&öÇ7Ò÷¶ÆVâ‡Væ—fW'6R—Ò&VÆ÷rÖ–æ–×VÓ²W'&÷'3×¶W'&÷'5³£×Ò"Ð¢'F—F–öâÒ$TEõ$ôõBòb'·&VF–7F–öç5³Õ²w6–væÅöFFRu×Òæ§6öæÂ Ð¢FFVBÒVæEö§6öæÂ‡'F—F–öâÂ&VF–7F–öç2Â'&VEö–B"Ð¢&–Ö'•÷&÷w2Ò·&÷rf÷"&÷r–â&VF–7F–öç2–b&÷rævWB‚'66÷&–æu÷fW'6–öâ"’ÓÒ6öæf–u²'66÷&–æu÷fW'6–öâ%ÕÐ¢–b–çG&F“ ¢f÷"&÷r–â&–Ö'•÷&÷w3 ¢FWF‚Òf–æ—FR‡&÷rævWB‚'5öFWF…÷vÆÂ"’¢–bFWF‚—2æöæS ¢6öçF–çVP¢F&vWBÒÖ&¶WEöf7F÷'2ç6WFFVfVÇB‡7G"‡&÷u²'7–Ö&öÂ%Ò’Â·Ò¢F&vWE²'5öFWF…÷vÆÂ%ÒÒFWF€¢–b–çG&F’÷"&Vg&W6…÷6Æ÷uöÖ&¶WC ¢6fUöÖ&¶WEöf7F÷%ö66†R†Ö&¶WEöf7F÷'2¢–æF–6F÷%ö6÷fW&vRÒ°Ð¢¶W“¢7VÒ‡&÷rævWB†¶W’’—2æ÷BæöæRf÷"&÷r–â&–Ö'•÷&÷w2Ð¢f÷"¶W’–â‚'5öfeöæWB"Â'5ööe÷†6Vf—‚"Â'5÷&÷óVB"Â'5ö–ç6–FW""Â'5öFWF…÷vÆÂ"Â'5ö6eö6÷&R"Ð¢ÐÐ¢7FGW2Ò°Ð¢'66†VÖ÷fW'6–öâ#¢Â&vVæW&FVEöB#¢FFWF–ÖRææ÷r‡F–ÖW¦öæRçWF2’æ—6öf÷&ÖB‚’ÀÐ¢'&u÷&VÆV6Uö–B#¢&rç&VÆV6Uö–B–b&rVÇ6RæöæRÀÐ¢&–çWEöÆ–W"#¢'6†&VE÷&÷f–FW%÷&r"–b&rVÇ6R&F—&V7E÷&÷f–FW""ÀÐ¢'&uö6FVæ6R#¢&ræÖæ–fW7BævWB‚&6FVæ6R"’–b&rVÇ6RæöæRÀÐ¢'66÷&–æu÷fW'6–öâ#¢6öæf–u²'66÷&–æu÷fW'6–öâ%ÒÂ'66÷&–æu÷fW'6–öç2#¢fW'6–öç2Â'Væ—fW'6U÷6—¦R#¢ÆVâ‡Væ—fW'6R’ÀÐ¢'6÷W&6W2#¢²'&VfW&Væ6R#¢&VfW&Væ6U÷6÷W&6RçWW"‚’Â&Ö&¶WEö6÷VçG2#¢6÷W&6Uö6÷VçG2Â&gVæFÖVçFÂ#¢gVæFÖVçFÅ÷6÷W&6RçWW"‚—ÒÀÐ¢&gVæFÖVçFÅ÷7FGW2#¢&66†U÷66÷&VB"Â&gVæFÖVçFÅö66†UöÖ…övUöF—2#¢Ö…övUöF—2ÀÐ¢&gVæFÖVçFÅö66†U÷7–Ö&öÇ2#¢ÆVâ†f7F÷%ö66†R’ÀÐ¢&66…öfÆ÷uö÷fW&Æ•÷7–Ö&öÇ2#¢&W7F÷&VEö66…öfÆ÷rÀÐ¢'6Æ÷uöÖ&¶WEö66†U÷7–Ö&öÇ2#¢ÆVâ†Ö&¶WEö66†R’Â'6Æ÷uöÖ&¶WE÷&Vg&W6†VB#¢&Vg&W6…÷6Æ÷uöÖ&¶WBÀ¢&Ö&¶WEöf7F÷%öFFR#¢Ö&¶WEöFFRæ—6öf÷&ÖB‚’À¢&gVæFÖVçFÅ÷7FÆUö66†U÷W6VB#¢7VÒ€Ð¢&ööÂ‡fÇVR’æBæ÷B66†UöVçG'•ö—5ög&W6‚‡fÇVRÂÖ…övUöF—2Ð¢f÷"fÇVR–âf7F÷%ö66†RçfÇVW2‚Ð¢’ÀÐ¢&gVæFÖVçFÅ÷7–Ö&öÇ5÷&Vg&W6†VB#¢ÀÐ¢&Ö&¶WEö–æF–6F÷%ö6÷fW&vR#¢–æF–6F÷%ö6÷fW&vRÀÐ¢'6W76–öå÷7FG5÷&ö&R#¢æW‡B‚€Ð¢fÇVRævWB‚'6W76–öå÷7FG5÷&ö&R"’f÷"fÇVR–âÖ&¶WEöf7F÷'2çfÇVW2‚Ð¢–bfÇVRævWB‚'6W76–öå÷7FG5÷&ö&R"Ð¢’ÂæöæR’À¢&FWF…ö–çWEö6÷fW&vR#¢7VÒ€¢&ööÂ‚‡fÇVRævWB‚'&r"’÷"·Ò’ævWB‚&÷&FW%ö&öö²"’¢æBf–æ—FR‚‡fÇVRævWB‚'&r"’÷"·Ò’ævWB‚&fW&vU÷G&FU÷6—¦R"’’—2æ÷BæöæP¢f÷"fÇVR–âÖ&¶WEöf7F÷'2çfÇVW2‚¢’À¢'7V66W76gVÅ÷7–Ö&öÇ2#¢7V66W76gVÅ÷7–Ö&öÇ2Â'&VF–7F–öå÷&÷w2#¢ÆVâ‡&VF–7F–öç2’ÀÐ¢'fæ–æFW…÷&÷w2#¢ÆVâ†–æFW…÷&÷w2’Â&f–ÆVE÷7–Ö&öÇ2#¢W'&÷'2Â'&V6÷&G5öFFVB#¢FFVBÀÐ¢ÐÐ¢–bæ÷B–çG&F“ ¢7FGW5²&F–Ç•ö6Æ÷6R%ÒÒ°¢'7FGW2#¢&f–æÆ—¦VB"À¢&W‡V7FVEöFFR#¢FöF’æ—6öf÷&ÖB‚’À¢&Ö&¶WEöFFR#¢Ö&¶WEöFFRæ—6öf÷&ÖB‚’À¢'&u÷&VÆV6Uö–B#¢&rç&VÆV6Uö–B–b&rVÇ6RæöæRÀ¢&6†V6¶VEöB#¢FFWF–ÖRææ÷r‡F–ÖW¦öæRçWF2’æ—6öf÷&ÖB‚’À¢ÐÐ¢7FGW5÷F‚Ò$ôõBò&÷WGWB"ò'fç7Fö6³b"ò&æF—fR×7FGW2æ§6öâ Ð¢7FGW5÷F‚ç&VçBæÖ¶F—"‡&VçG3ÕG'VRÂW†—7Eöö³ÕG'VRÐ¢7FGW5÷F‚çw&—FU÷FW‡B†GV×5ö§6öâ‡7FGW2ÂVç7W&Uö66–“ÔfÇ6RÂ–æFVçCÓ"’²%Æâ"ÂVæ6öF–æsÒ'WFbÓ‚"Ð¢&–çB€Ð¢b%då7Fö6³bæF—fS¢·7V66W76gVÅ÷7–Ö&öÇ7Ò÷¶ÆVâ‡Væ—fW'6R—Ò7–Ö&öÇ2Â Ð¢b'¶ÆVâ‡&VF–7F–öç2—Ò&VF–7F–öâ&÷w2Â¶FFVGÒæWr&VF–7F–öç2 Ð¢Ð Ð Ð¦FVbWfÇVFR†6öæf–s¢F–7E·7G"Âç•Ò’ÓâæöæS Ð¢&VF–7F–öç2ÒµÐÐ¢f÷"F‚–â6÷'FVB…$TEõ$ôõBævÆö"‚"¢æ§6öæÂ"’“ Ð¢&VF–7F–öç2æW‡FVæB†§6öâæÆöG2†Æ–æR’f÷"Æ–æR–âF‚ç&VE÷FW‡B†Væ6öF–æsÒ'WFbÓ‚"’ç7Æ—FÆ–æW2‚’–bÆ–æRç7G&—‚’Ð¢÷WF6öÖW3¢Æ—7E¶F–7E·7G"Âç•ÕÒÒµÐÐ¢f÷"&VF–7F–öâ–â&VF–7F–öç3 Ð¢&'2Ò§6öâæÆöG2‚„ô„Ä5õ$ôõBòb'·&VF–7F–öå²w7–Ö&öÂu×Òæ§6öâ"’ç&VE÷FW‡B†Væ6öF–æsÒ'WFbÓ‚"’Ð¢ÆFW"Ò·&÷rf÷"&÷r–â&'2–b7G"‡&÷rævWB‚&FFR"’’â&VF–7F–öå²'6–væÅöFFR%ÕÐÐ¢VçG'’Òf–æ—FR‡&VF–7F–öâævWB‚'&–6R"’Ð¢–bæ÷BVçG'’÷"æ÷BÆFW# Ð¢6öçF–çVPÐ¢&÷rÒ²'&VEö–B#¢&VF–7F–öå²'&VEö–B%ÒÂ'7–Ö&öÂ#¢&VF–7F–öå²'7–Ö&öÂ%ÒÂ'66÷&–æu÷fW'6–öâ#¢6öæf–u²'66÷&–æu÷fW'6–öâ%ÒÂ&ÆVç2#¢'G&FR"Â'—VÆ–æUövVæW&F–öâ#¢bÂ&Ö&¶WE÷6÷W&6R#¢&VF–7F–öâævWB‚&Ö&¶WE÷6÷W&6R"’Â&åö&'2#¢ÆVâ†ÆFW"’Â&WfÅöFFR#¢ÆFW%²ÓÕ²&FFR%×ÐÐ¢&÷u²'66÷&–æu÷fW'6–öâ%ÒÒ&VF–7F–öå²'66÷&–æu÷fW'6–öâ%ÐÐ¢f÷"†÷&—¦öâ–âƒÂ2ÂRÂ“ Ð¢&÷u¶b'&WE÷¶†÷&—¦öçÖB%ÒÒ&÷VæB‚†fÆöB†ÆFW%¶†÷&—¦öâÒÕ²&6Æ÷6R%Ò’òVçG'’Ò’¢Âb’–bÆVâ†ÆFW"’ãÒ†÷&—¦öâVÇ6RæöæPÐ¢÷WF6öÖW2æVæB‡&÷rÐ¢–b÷WF6öÖW3 Ð¢'•öÖöçFƒ¢F–7E·7G"ÂÆ—7E¶F–7E·7G"Âç•ÕÕÒÒ·ÐÐ¢f÷"&÷r–â÷WF6öÖW3 Ð¢'•öÖöçF‚ç6WFFVfVÇB‡7G"‡&÷u²&WfÅöFFR%Ò•³£uÒÂµÒ’æVæB‡&÷rÐ¢f÷"ÖöçF‚Â&÷w2–â'•öÖöçF‚æ—FV×2‚“ Ð¢VæEö§6öæÂ„õUD4ôÔUõ$ôõBòb'¶ÖöçF‡Òæ§6öæÂ"Â&÷w2Â'&VEö–B"Ð¢&–çB†b%då7Fö6³b÷WF6öÖW2WFFVC¢¶ÆVâ†÷WF6öÖW2—Ò"Ð Ð Ð¦FVbÖ–â‚’ÓâæöæS Ð¢'6W"Ò&w'6Rä&wVÖVçE'6W"‚Ð¢'6W"æFEö&wVÖVçB‚&6öÖÖæB"Â6†ö–6W3Ò‚''Vâ"Â&WfÇVFR"Â&gVæFÖVçFÇ2"’Ð¢'6W"æFEö&wVÖVçB‚"ÒÖf÷&6R"Â7F–öãÒ'7F÷&U÷G'VR"Ð¢'6W"æFEö&wVÖVçB‚"ÒÖ–çG&F’"Â7F–öãÒ'7F÷&U÷G'VR"Ð¢'6W"æFEö&wVÖVçB‚"Ò×&Vg&W6‚×6Æ÷rÖÖ&¶WB"Â7F–öãÒ'7F÷&U÷G'VR"Ð¢'6W"æFEö&wVÖVçB‚"Ò×&r×&VÆV6RÖ–B"Ð¢'6W"æFEö&wVÖVçB‚"ÒÖgVæFÖVçFÂÖÆ–Ö—B"ÂG—SÖ–çBÐ¢'6W"æFEö&wVÖVçB‚"Ò×7FÆRÖöæÇ’"Â7F–öãÒ'7F÷&U÷G'VR"Ð¢'6W"æFEö&wVÖVçB‚"ÒÖ6†V6²×WFFW2"Â7F–öãÒ'7F÷&U÷G'VR"Ð¢&w2Ò'6W"ç'6Uö&w2‚Ð¢6öæf–rÒÆöEö6öæf–r‚Ð¢–b&w2æ6öÖÖæBÓÒ''Vâ# Ð¢'VåöæF—fR†6öæf–rÂ&w2æf÷&6RÂ&w2æ–çG&F’Â&w2ç&Vg&W6…÷6Æ÷uöÖ&¶WBÂ&w2ç&u÷&VÆV6Uö–BÐ¢VÆ–b&w2æ6öÖÖæBÓÒ&gVæFÖVçFÇ2# Ð¢–b&w2ç&u÷&VÆV6Uö–C Ð¢&Vg&W6…ögVæFÖVçFÅö66†Uög&öÕ÷&r€Ð¢6öæf–rÂ&u&VÆV6RæÆöB†&w2ç&u÷&VÆV6Uö–B’Â&w2ægVæFÖVçFÅöÆ–Ö—@Ð¢Ð¢VÇ6S Ð¢&Vg&W6…ögVæFÖVçFÅö66†R€Ð¢6öæf–rÂ&w2ægVæFÖVçFÅöÆ–Ö—BÂ&w2ç7FÆUööæÇ’Â&w2æ6†V6µ÷WFFW0Ð¢Ð¢VÇ6S Ð¢WfÇVFR†6öæf–rÐ Ð Ð¦–bõöæÖUõòÓÒ%õöÖ–åõò# Ð¢Ö–â‚Ð 