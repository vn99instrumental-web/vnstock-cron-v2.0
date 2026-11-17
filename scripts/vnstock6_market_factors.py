"""Approved Gen6 foreign-flow and bid/ask factors with endpoint provenance."""
from __future__ import annotations

import math
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
from typing import Any

import pandas as pd
from vnstock import Market

UTC = timezone.utc


def finite(value: Any) -> float | None:
    try:
        number = float(value)
        return number if math.isfinite(number) else None
    except (TypeError, ValueError):
        return None


def _records(frame: Any) -> list[dict[str, Any]]:
    if frame is None:
        return []
    if isinstance(frame, pd.DataFrame):
        return frame.reset_index().to_dict("records")
    if isinstance(frame, dict):
        return [frame]
    return list(frame) if isinstance(frame, list) else []


def _value(row: dict[str, Any], *names: str) -> Any:
    normalized = {str(key).lower().replace(" ", "_"): value for key, value in row.items()}
    for name in names:
        if name in normalized:
            return normalized[name]
    return None


def _sum(rows: list[dict[str, Any]], *names: str) -> float | None:
    values = [finite(_value(row, *names)) for row in rows]
    values = [value for value in values if value is not None]
    return sum(values) if values else None


def _net_value(row: dict[str, Any]) -> float | None:
    net = finite(_value(row, "foreign_net_value", "net_val", "net_value"))
    if net is not None:
        return net
    buy = finite(_value(row, "foreign_buy_value", "buy_val", "buy_value"))
    sell = finite(_value(row, "foreign_sell_value", "sell_val", "sell_value"))
    return buy - sell if buy is not None and sell is not None else None


def _as_of(rows: list[dict[str, Any]]) -> str | None:
    """Return source-provided date text without guessing endpoint semantics."""
    if not rows:
        return None
    value = _value(
        rows[-1], "time", "date", "trading_date", "deal_date",
        "transaction_date", "public_date", "report_date",
    )
    return str(value)[:10] if value not in (None, "") else None


def _row_date(row: dict[str, Any]) -> str | None:
    value = _value(
        row, "time", "date", "trading_date", "deal_date",
        "transaction_date", "public_date", "report_date",
    )
    return str(value)[:10] if value not in (None, "") else None


def rows_for_date(rows: list[dict[str, Any]], target: date) -> list[dict[str, Any]]:
    """Keep only source rows that explicitly belong to the requested session."""
    wanted = target.isoformat()
    return [row for row in rows if _row_date(row) == wanted]


def _sort_by_date(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(rows, key=lambda row: _row_date(row) or "")


def foreign_score(rows: list[dict[str, Any]]) -> tuple[float | None, dict[str, Any]]:
    """Match the v4 foreign 5/20-session bands, using actual daily values."""
    if not rows:
        return None, {}
    rows = _sort_by_date(rows)
    latest, recent = rows[-20:], rows[-5:]
    buy5 = _sum(recent, "foreign_buy_value", "buy_val", "buy_value")
    sell5 = _sum(recent, "foreign_sell_value", "sell_val", "sell_value")
    net5 = _sum(recent, "foreign_net_value", "net_val", "net_value")
    if net5 is None and buy5 is not None and sell5 is not None:
        net5 = buy5 - sell5
    net20 = _sum(latest, "foreign_net_value", "net_val", "net_value")
    if net20 is None:
        buy20 = _sum(latest, "foreign_buy_value", "buy_val", "buy_value")
        sell20 = _sum(latest, "foreign_sell_value", "sell_val", "sell_value")
        if buy20 is not None and sell20 is not None:
            net20 = buy20 - sell20
    if net5 is None:
        return None, {}
    turnover = abs(buy5 or 0) + abs(sell5 or 0)
    intensity = net5 / turnover if turnover else 0.0
    raw = 0
    if abs(intensity) >= 0.10:
        aligned = net20 is not None and (net20 > 0) == (net5 > 0)
        raw = (10 if abs(intensity) >= 0.30 and aligned else 5) * (1 if net5 > 0 else -1)
    return round(max(-15, min(15, raw)) / 15 * 6), {
        "foreign_net_1d": _net_value(rows[-1]),
        "foreign_as_of": str(_value(rows[-1], "time", "date", "trading_date") or "")[:10] or None,
        "foreign_net_5d": net5, "foreign_net_20d": net20, "foreign_intensity": intensity,
    }


def proprietary_score(rows: list[dict[str, Any]]) -> tuple[float | None, dict[str, Any]]:
    if not rows:
        return None, {}
    nets: list[float] = []
    for row in rows[-20:]:
        net = finite(_value(row, "net_value", "proprietary_net_value", "net_val"))
        if net is None:
            buy = finite(_value(row, "buy_value", "proprietary_buy_value"))
            sell = finite(_value(row, "sell_value", "proprietary_sell_value"))
            net = buy - sell if buy is not None and sell is not None else None
        if net is not None:
            nets.append(net)
    metadata: dict[str, Any] = {
        "proprietary_row_count": len(rows),
        "proprietary_usable_rows": len(nets),
        "proprietary_as_of": _as_of(rows),
    }
    if not nets:
        return None, metadata
    net5, net20 = sum(nets[-5:]) / 1e9, sum(nets) / 1e9
    trend = (sum(nets[-5:]) / 5) - (sum(nets[-10:-5]) / 5) if len(nets) >= 10 else 0
    raw = 10 if net5 > 5 and net20 > 0 and trend > 0 else 5 if net5 > 2 else 2 if net5 > .5 else 0 if net5 > -.5 else -2 if net5 > -2 else -5 if net5 > -5 else -10
    return round(raw / 10 * 3), {
        "proprietary_net_5d": sum(nets[-5:]), "proprietary_net_20d": sum(nets), **metadata,
    }


def insider_score(rows: list[dict[str, Any]]) -> tuple[float | None, dict[str, Any]]:
    if not rows:
        return None, {}
    buy = sell = unclassified = 0
    for row in rows:
        kind = str(_value(row, "transaction_type", "deal_type", "type") or "").lower()
        if any(word in kind for word in ("mua", "buy", "purchase", "acqui")):
            buy += 1
        elif any(word in kind for word in ("b\u00e1n", "ban", "sell", "dispos")):
            sell += 1
        else:
            unclassified += 1
    metadata = {
        "insider_buy_count": buy, "insider_sell_count": sell,
        "insider_row_count": len(rows), "insider_unclassified_count": unclassified,
        "insider_as_of": _as_of(rows),
    }
    if buy + sell == 0:
        return None, metadata
    net = buy - sell
    score = 5 if net >= 3 else 3 if net >= 1 else 0 if net == 0 else -3 if net >= -2 else -5
    return round(score / 5 * 2), metadata


def average_trade_size(rows: list[dict[str, Any]]) -> float | None:
    """Compute the v4 depth denominator from SSI session aggregate fields."""
    if not rows:
        return None
    row = rows[-1]
    buy_volume = finite(_value(row, "total_buy_trade_volume", "active_buy_volume")) or 0.0
    sell_volume = finite(_value(row, "total_sell_trade_volume", "active_sell_volume")) or 0.0
    buy_count = finite(_value(row, "total_buy_trade", "buy_order_count")) or 0.0
    sell_count = finite(_value(row, "total_sell_trade", "sell_order_count")) or 0.0
    count = buy_count + sell_count
    return (buy_volume + sell_volume) / count if count > 0 else None


def session_turnover_value(rows: list[dict[str, Any]]) -> float | None:
    """Return exact accumulated session turnover in VND from SSI aggregates."""
    if not rows:
        return None
    return finite(_value(rows[-1], "total_value", "total_match_value", "matched_value"))


def _error(exc: Exception) -> dict[str, Any]:
    return {"type": type(exc).__name__, "code": getattr(exc, "code", None), "action": getattr(exc, "action", None)}


def fetch_symbol(
    symbol: str, today: date, cached_slow: dict[str, Any] | None = None,
    refresh_slow: bool = False, fetch_depth: bool = True, slow_retries: int = 3,
) -> dict[str, Any]:
    """Fetch fast endpoints and preserve slow FHSC factors between daily refreshes."""
    start, end = (today - timedelta(days=35)).isoformat(), today.isoformat()
    cached_slow = cached_slow or {}
    cached_raw = cached_slow.get("raw") or {}
    checked_at = datetime.now(UTC).isoformat()
    result: dict[str, Any] = {
        "refreshed_at": checked_at, "errors": {},
        "endpoint_sources": {}, "raw": {}, "s_ff_net": None,
        "s_depth_wall": finite(cached_slow.get("s_depth_wall")),
        "depth_signal_date": cached_slow.get("depth_signal_date"),
        "depth_snap_time": cached_slow.get("depth_snap_time"),
        "depth_captured_at": cached_slow.get("depth_captured_at"),
        "s_prop_5d": finite(cached_slow.get("s_prop_5d")),
        "s_insider": finite(cached_slow.get("s_insider")),
        "proprietary_flow_status": cached_slow.get("proprietary_flow_status"),
        "proprietary_flow_checked_at": cached_slow.get("proprietary_flow_checked_at"),
        "proprietary_flow_refreshed_at": cached_slow.get("proprietary_flow_refreshed_at"),
        "insider_deal_status": cached_slow.get("insider_deal_status"),
        "insider_deal_checked_at": cached_slow.get("insider_deal_checked_at"),
        "insider_deal_refreshed_at": cached_slow.get("insider_deal_refreshed_at"),
    }
    for key in (
        "proprietary_net_5d", "proprietary_net_20d", "proprietary_row_count",
        "proprietary_usable_rows", "insider_buy_count", "insider_sell_count",
        "insider_row_count", "insider_unclassified_count",
    ):
        value = finite(cached_raw.get(key))
        if value is not None:
            result["raw"][key] = value
    for key in ("proprietary_as_of", "insider_as_of"):
        if cached_raw.get(key) not in (None, ""):
            result["raw"][key] = cached_raw[key]
    if result["s_prop_5d"] is not None:
        result["endpoint_sources"]["proprietary_flow"] = "FHSC_CACHE"
        result["proprietary_flow_status"] = result["proprietary_flow_status"] or "available"
    else:
        result["proprietary_flow_status"] = result["proprietary_flow_status"] or "not_available"
    if result["s_insider"] is not None:
        result["endpoint_sources"]["insider_deal"] = "FHSC_CACHE"
        result["insider_deal_status"] = result["insider_deal_status"] or "available"
    else:
        result["insider_deal_status"] = result["insider_deal_status"] or "not_available"
    if result["s_depth_wall"] is not None:
        result["endpoint_sources"]["order_book"] = "FHSC_SESSION_CACHE"
    proprietary_rows: list[dict[str, Any]] = []
    insider_rows: list[dict[str, Any]] = []
    if refresh_slow:
        result["proprietary_flow_checked_at"] = checked_at
        for attempt in range(max(1, slow_retries)):
            try:
                proprietary_rows = _records(Market("fhsc").equity(symbol).proprietary_flow(start=start, end=end, compat="v6", floating=2))
                score, raw = proprietary_score(proprietary_rows)
                if score is None:
                    status = "empty_response_unverified" if not proprietary_rows else "unclassified_response"
                    result["proprietary_flow_status"] = status
                    result["raw"].update(raw)
                    result["errors"]["proprietary_flow_fhsc"] = {"type": status}
                    break
                result["s_prop_5d"], result["endpoint_sources"]["proprietary_flow"] = score, "FHSC"
                result["raw"].update(raw)
                result["proprietary_flow_status"] = "available"
                result["proprietary_flow_refreshed_at"] = checked_at
                result["errors"].pop("proprietary_flow_fhsc", None)
                break
            except Exception as exc:
                result["proprietary_flow_status"] = "source_error"
                result["errors"]["proprietary_flow_fhsc"] = _error(exc)
                if attempt + 1 < max(1, slow_retries):
                    time.sleep(0.5 * (attempt + 1))
        result["insider_deal_checked_at"] = checked_at
        try:
            insider_rows = _records(Market("fhsc").equity(symbol).insider_deal(compat="v6", floating=2))
            score, raw = insider_score(insider_rows)
            if score is None:
                status = "empty_response_unverified" if not insider_rows else "unclassified_response"
                result["insider_deal_status"] = status
                result["raw"].update(raw)
                result["errors"]["insider_deal_fhsc"] = {"type": status}
            else:
                result["s_insider"], result["endpoint_sources"]["insider_deal"] = score, "FHSC"
                result["raw"].update(raw)
                result["insider_deal_status"] = (
                    "available_with_unclassified"
                    if finite(raw.get("insider_unclassified_count")) else "available"
                )
                result["insider_deal_refreshed_at"] = checked_at
                result["errors"].pop("insider_deal_fhsc", None)
        except Exception as exc:
            result["insider_deal_status"] = "source_error"
            result["errors"]["insider_deal_fhsc"] = _error(exc)
    foreign_rows: list[dict[str, Any]] = []
    ssi_foreign_rows: list[dict[str, Any]] = []
    for source in ("ssi", "fhsc"):
        try:
            candidate_rows = _records(Market(source).equity(symbol).foreign_flow(
                start=start, end=end, interval="1D", compat="v6", floating=2
            ))
            if source == "ssi":
                ssi_foreign_rows = candidate_rows
            current_rows = rows_for_date(candidate_rows, today)
            score, raw = foreign_score(candidate_rows)
            if score is not None and current_rows:
                current_net = _net_value(_sort_by_date(current_rows)[-1])
                if current_net is None:
                    raise ValueError(f"{source.upper()} foreign_flow has no usable current-session value")
                raw["foreign_net_1d"] = current_net
                raw["foreign_as_of"] = today.isoformat()
                foreign_rows = candidate_rows
                result["s_ff_net"] = score
                result["raw"].update(raw)
                result["endpoint_sources"]["foreign_flow"] = source.upper()
                break
            result["errors"][f"foreign_flow_{source}"] = {
                "type": "StaleOrEmptyData", "as_of": _as_of(_sort_by_date(candidate_rows)),
                "required_date": today.isoformat(),
            }
        except Exception as exc:
            result["errors"][f"foreign_flow_{source}"] = _error(exc)

    stats_rows: list[dict[str, Any]] = []
    average: float | None = None
    try:
        candidate_stats = _records(Market("ssi").equity(symbol).session_stats(
            start=today.isoformat(), end=end, compat="v6", floating=2
        ))
        stats_rows = rows_for_date(candidate_stats, today)
        if not stats_rows:
            raise ValueError("SSI session_stats did not return the requested session")
        turnover = session_turnover_value(stats_rows)
        if turnover is not None:
            result["raw"]["session_turnover_value"] = turnover
            result["raw"]["session_turnover_as_of"] = today.isoformat()
            result["raw"]["session_turnover_checked_at"] = checked_at
            result["endpoint_sources"]["session_turnover"] = "SSI_SESSION_STATS"
        average = average_trade_size(stats_rows)
        if average:
            result["endpoint_sources"]["trade_size"] = "SSI"
        elif fetch_depth:
            raise ValueError("SSI session_stats returned no average trade size")
        current_stats = stats_rows[-1]
        stats_buy = finite(_value(current_stats, "fr_buy_value_total"))
        stats_sell = finite(_value(current_stats, "fr_sell_value_total"))
        stats_net = finite(_value(current_stats, "fr_net_value_total"))
        if stats_net is None and stats_buy is not None and stats_sell is not None:
            stats_net = stats_buy - stats_sell
        if stats_net is not None and ssi_foreign_rows:
            current_foreign = {
                "time": today.isoformat(),
                "foreign_buy_value": stats_buy,
                "foreign_sell_value": stats_sell,
                "foreign_net_value": stats_net,
            }
            aligned_history = [
                row for row in ssi_foreign_rows if _row_date(row) != today.isoformat()
            ] + [current_foreign]
            score, raw = foreign_score(aligned_history)
            if score is not None:
                result["s_ff_net"] = score
                result["raw"].update(raw)
                result["raw"]["foreign_as_of"] = today.isoformat()
                result["endpoint_sources"]["foreign_flow"] = "SSI_SESSION_STATS"
                foreign_rows = aligned_history
    except Exception as exc:
        result["errors"]["session_stats_ssi"] = _error(exc)
        if fetch_depth:
            try:
                active_rows = _records(Market("fhsc").equity(symbol).active_session(compat="v6", floating=2))
                average = average_trade_size(active_rows)
                if average:
                    result["endpoint_sources"]["trade_size"] = "FHSC"
                else:
                    result["errors"]["active_session_fhsc"] = {"type": "EmptyData"}
            except Exception as fallback_exc:
                average = None
                result["errors"]["active_session_fhsc"] = _error(fallback_exc)

    if not fetch_depth:
        result["endpoint_rows"] = {
            "foreign_flow": len(foreign_rows), "session_stats": len(stats_rows), "order_book": 0,
            "proprietary_flow": len(proprietary_rows), "insider_deal": len(insider_rows),
        }
        return result

    result["endpoint_sources"]["order_book_primary"] = "SSI_UNSUPPORTED"
    try:
        order_book = _records(Market("fhsc").equity(symbol).order_book(compat="v6", floating=2))
        if order_book:
            result["endpoint_sources"]["order_book"] = "FHSC"
        else:
            result["errors"]["order_book_fhsc"] = {"type": "EmptyData"}
    except Exception as exc:
        order_book = []
        result["errors"]["order_book_fhsc"] = _error(exc)
    result["raw"].update({"average_trade_size": average, "order_book": order_book})
    result["endpoint_rows"] = {
        "foreign_flow": len(foreign_rows), "session_stats": len(stats_rows), "order_book": len(order_book),
        "proprietary_flow": len(proprietary_rows), "insider_deal": len(insider_rows),
    }
    return result


def collect_market_factors(
    symbols: list[str], today: date, max_workers: int = 4,
    slow_cache: dict[str, dict[str, Any]] | None = None,
    refresh_slow: bool = False, fetch_depth: bool = True,
) -> dict[str, dict[str, Any]]:
    slow_cache = slow_cache or {}
    workers = max(1, min(int(max_workers), len(symbols) or 1))
    with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="vnstock6-market") as executor:
        values = list(executor.map(
            lambda symbol: fetch_symbol(
                symbol, today, slow_cache.get(symbol), refresh_slow, fetch_depth
            ), symbols
        ))
    return dict(zip(symbols, values))
