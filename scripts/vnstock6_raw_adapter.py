"""Gen6 adapters for immutable SSI/FHSC provider-raw releases.

This module never imports SSI scoring. It exposes raw provider rows to Gen6,
which continues to calculate its own vnstock_quant and profile factors.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

import pandas as pd

try:
    from shared_raw_collector import ENDPOINTS, RAW_ROOT, RELEASE_RE, read_dataset, verify_release
    from vnstock6_market_factors import (
        average_trade_size, foreign_score, insider_score, proprietary_score,
        rows_for_date, session_turnover_value,
    )
except ModuleNotFoundError:  # package import used by unit tests
    from scripts.shared_raw_collector import ENDPOINTS, RAW_ROOT, RELEASE_RE, read_dataset, verify_release
    from scripts.vnstock6_market_factors import (
        average_trade_size, foreign_score, insider_score, proprietary_score,
        rows_for_date, session_turnover_value,
    )


@dataclass(frozen=True)
class RawRelease:
    release_id: str
    release_dir: Path
    manifest: dict[str, Any]
    datasets: dict[str, dict[str, dict[str, Any]]]

    @classmethod
    def load(cls, release_id: str, raw_root: Path = RAW_ROOT) -> "RawRelease":
        if not RELEASE_RE.fullmatch(str(release_id)):
            raise ValueError("INVALID_SHARED_RAW_RELEASE_ID")
        release_dir = raw_root / "releases" / release_id
        manifest = verify_release(release_dir)
        datasets: dict[str, dict[str, dict[str, Any]]] = {}
        for metadata in manifest["datasets"]:
            for envelope in read_dataset(release_dir, str(metadata["path"])):
                endpoint = str(envelope.get("endpoint") or "")
                symbol = str(envelope.get("symbol") or "__all__").upper()
                datasets.setdefault(endpoint, {})[symbol] = envelope
        return cls(release_id, release_dir, manifest, datasets)

    def envelope(self, endpoint: str, symbol: str | None = None) -> dict[str, Any]:
        key = str(symbol or "__all__").upper()
        return dict((self.datasets.get(endpoint) or {}).get(key) or {})

    def rows(self, endpoint: str, symbol: str | None = None) -> list[dict[str, Any]]:
        envelope = self.envelope(endpoint, symbol)
        return [dict(row) for row in envelope.get("rows") or [] if isinstance(row, dict)]

    def frame(self, endpoint: str, symbol: str | None = None) -> pd.DataFrame:
        return pd.DataFrame(self.rows(endpoint, symbol))


def reference_industries(raw: RawRelease) -> dict[str, str]:
    rows = raw.rows("reference")
    if not rows:
        return {}
    data = pd.DataFrame(rows)
    lowered = {str(column).lower(): column for column in data.columns}
    symbol_column = lowered.get("symbol")
    industry_column = next((lowered[key] for key in (
        "industry", "industry_name", "icb_name", "icb_name3", "icb_name2"
    ) if key in lowered), None)
    if symbol_column is None or industry_column is None:
        return {}
    return {
        str(row[symbol_column]).upper(): str(row[industry_column])
        for _, row in data.iterrows()
        if row.get(symbol_column) not in (None, "") and row.get(industry_column) not in (None, "")
    }


def _normalize_statement(frame: pd.DataFrame) -> pd.DataFrame:
    """Map provider aliases to the long-frame contract expected by fa.Dataset."""
    data = frame.copy()
    lowered = {str(column).lower(): column for column in data.columns}
    rename: dict[Any, str] = {}
    for target, aliases in {
        "period": ("period", "report_period"),
        "id": ("id", "item_id", "line_code"),
        "value": ("value", "item_value"),
    }.items():
        source = next((lowered[alias] for alias in aliases if alias in lowered), None)
        if source is not None and source != target:
            rename[source] = target
    return data.rename(columns=rename)


def fundamental_frames(raw: RawRelease, symbol: str) -> list[pd.DataFrame]:
    return [_normalize_statement(raw.frame(endpoint, symbol)) for endpoint in (
        "balance_sheet", "income_statement", "cash_flow"
    )]


def _cached_base(cached: dict[str, Any] | None) -> dict[str, Any]:
    cached = cached or {}
    cached_raw = dict(cached.get("raw") or {})
    result = {
        "refreshed_at": raw_time(cached), "errors": {}, "endpoint_sources": {}, "raw": {},
        "s_ff_net": None, "s_depth_wall": None,
        "depth_signal_date": None, "depth_snap_time": None, "depth_captured_at": None,
        "depth_status": "not_available",
        "s_prop_5d": cached.get("s_prop_5d"), "s_insider": cached.get("s_insider"),
        "proprietary_flow_status": cached.get("proprietary_flow_status") or "not_available",
        "proprietary_flow_checked_at": cached.get("proprietary_flow_checked_at"),
        "proprietary_flow_refreshed_at": cached.get("proprietary_flow_refreshed_at"),
        "insider_deal_status": cached.get("insider_deal_status") or "not_available",
        "insider_deal_checked_at": cached.get("insider_deal_checked_at"),
        "insider_deal_refreshed_at": cached.get("insider_deal_refreshed_at"),
    }
    for key in (
        "proprietary_net_5d", "proprietary_net_20d", "proprietary_row_count",
        "proprietary_usable_rows", "proprietary_as_of", "insider_buy_count",
        "insider_sell_count", "insider_row_count", "insider_unclassified_count", "insider_as_of",
    ):
        if cached_raw.get(key) is not None:
            result["raw"][key] = cached_raw[key]
    return result


def raw_time(value: dict[str, Any]) -> str | None:
    return value.get("refreshed_at") or value.get("generated_at")


def market_factors_from_raw(
    raw: RawRelease, symbols: list[str], signal_date: date,
    slow_cache: dict[str, dict[str, Any]] | None = None,
    refresh_slow: bool = False, fetch_depth: bool = True,
) -> dict[str, dict[str, Any]]:
    """Apply Gen6 factor formulas to raw endpoint rows without provider calls."""
    slow_cache = slow_cache or {}
    checked_at = str(raw.manifest.get("created_at") or "")
    output: dict[str, dict[str, Any]] = {}
    for symbol in symbols:
        cached = slow_cache.get(symbol) or {}
        result = _cached_base(cached)
        result["refreshed_at"] = checked_at
        result["raw_release_id"] = raw.release_id

        ssi_foreign = raw.rows("foreign_flow", symbol)
        fhsc_foreign = raw.rows("foreign_flow_fhsc", symbol)
        foreign_rows: list[dict[str, Any]] = []
        for source, rows in (("SSI", ssi_foreign), ("FHSC", fhsc_foreign)):
            score, metrics = foreign_score(rows)
            current = rows_for_date(rows, signal_date)
            if score is not None and current:
                result["s_ff_net"] = score
                result["raw"].update(metrics)
                result["raw"]["foreign_as_of"] = signal_date.isoformat()
                result["endpoint_sources"]["foreign_flow"] = source
                foreign_rows = rows
                break
            result["errors"][f"foreign_flow_{source.lower()}"] = {
                "type": "StaleOrEmptyData", "required_date": signal_date.isoformat(),
            }

        stats_rows = rows_for_date(raw.rows("session_stats", symbol), signal_date)
        active_rows = raw.rows("active_session", symbol)
        average = average_trade_size(stats_rows)
        if stats_rows:
            turnover = session_turnover_value(stats_rows)
            if turnover is not None:
                result["raw"].update({
                    "session_turnover_value": turnover,
                    "session_turnover_as_of": signal_date.isoformat(),
                    "session_turnover_checked_at": checked_at,
                })
                result["endpoint_sources"]["session_turnover"] = "SSI_SESSION_STATS"
            if average:
                result["endpoint_sources"]["trade_size"] = "SSI"
        if not average:
            average = average_trade_size(active_rows)
            if average:
                result["endpoint_sources"]["trade_size"] = "FHSC"

        proprietary_rows = raw.rows("proprietary_flow", symbol)
        insider_rows = raw.rows("insider_deal", symbol)
        if refresh_slow and "proprietary_flow" in raw.datasets:
            score, metrics = proprietary_score(proprietary_rows)
            result["proprietary_flow_checked_at"] = checked_at
            result["raw"].update(metrics)
            if score is not None:
                result["s_prop_5d"] = score
                result["endpoint_sources"]["proprietary_flow"] = "FHSC"
                result["proprietary_flow_status"] = "available"
                result["proprietary_flow_refreshed_at"] = checked_at
        elif result.get("s_prop_5d") is not None:
            result["endpoint_sources"]["proprietary_flow"] = "FHSC_CACHE"

        if refresh_slow and "insider_deal" in raw.datasets:
            score, metrics = insider_score(insider_rows)
            result["insider_deal_checked_at"] = checked_at
            result["raw"].update(metrics)
            if score is not None:
                result["s_insider"] = score
                result["endpoint_sources"]["insider_deal"] = "FHSC"
                result["insider_deal_status"] = "available"
                result["insider_deal_refreshed_at"] = checked_at
        elif result.get("s_insider") is not None:
            result["endpoint_sources"]["insider_deal"] = "FHSC_CACHE"

        live_order_book = raw.rows("order_book", symbol) if fetch_depth else []
        cached_raw = dict(cached.get("raw") or {})
        cached_same_day = cached.get("depth_signal_date") == signal_date.isoformat()
        cached_order_book = cached_raw.get("order_book") or [] if cached_same_day else []
        cached_average = cached_raw.get("average_trade_size") if cached_same_day else None
        if live_order_book:
            result["endpoint_sources"]["observed_order_book"] = "FHSC"
            result["raw"]["observed_order_book"] = live_order_book
        if live_order_book and average:
            order_book = live_order_book
            result["endpoint_sources"]["order_book"] = "FHSC"
            result["depth_status"] = "live_ready"
        elif cached_order_book and cached_average:
            order_book, average = cached_order_book, cached_average
            result["endpoint_sources"]["order_book"] = "FHSC_SESSION_CACHE"
            result["depth_status"] = "same_session_cache"
            result["depth_signal_date"] = signal_date.isoformat()
        else:
            order_book = live_order_book
            result["depth_status"] = "missing_trade_size" if live_order_book else "missing_order_book"
        result["raw"].update({"average_trade_size": average, "order_book": order_book})
        result["endpoint_rows"] = {
            "foreign_flow": len(foreign_rows), "session_stats": len(stats_rows),
            "order_book": len(order_book), "proprietary_flow": len(proprietary_rows),
            "insider_deal": len(insider_rows),
        }
        result["session_stats_probe"] = {
            "status": "raw_release", "release_id": raw.release_id,
        }
        output[symbol] = result
    return output