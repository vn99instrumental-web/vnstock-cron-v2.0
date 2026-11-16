"""Approved Gen6 foreign-flow and bid/ask factors with endpoint provenance."""
from __future__ import annotations

import math
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


def foreign_score(rows: list[dict[str, Any]]) -> tuple[float | None, dict[str, Any]]:
    """Match the v4 foreign 5/20-session bands, using actual daily values."""
    if not rows:
        return None, {}
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
    if not nets:
        return None, {}
    net5, net20 = sum(nets[-5:]) / 1e9, sum(nets) / 1e9
    trend = (sum(nets[-5:]) / 5) - (sum(nets[-10:-5]) / 5) if len(nets) >= 10 else 0
    raw = 10 if net5 > 5 and net20 > 0 and trend > 0 else 5 if net5 > 2 else 2 if net5 > .5 else 0 if net5 > -.5 else -2 if net5 > -2 else -5 if net5 > -5 else -10
    return round(raw / 10 * 3), {"proprietary_net_5d": sum(nets[-5:]), "proprietary_net_20d": sum(nets)}


def insider_score(rows: list[dict[str, Any]]) -> tuple[float | None, dict[str, Any]]:
    if not rows:
        return None, {}
    buy = sell = 0
    for row in rows:
        kind = str(_value(row, "transaction_type", "deal_type", "type") or "").lower()
        if any(word in kind for word in ("mua", "buy", "purchase", "acqui")):
            buy += 1
        elif any(word in kind for word in ("b\u00e1n", "ban", "sell", "dispos")):
            sell += 1
    net = buy - sell
    raw = 5 if net >= 3 else 3 if net >= 1 else 0 if net == 0 else -3 if net >= -2 else -5
    return round(raw / 5 * 2), {"insider_buy_count": buy, "insider_sell_count": sell}


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


def _error(exc: Exception) -> dict[str, Any]:
    return {"type": type(exc).__name__, "code": getattr(exc, "code", None), "action": getattr(exc, "action", None)}


def fetch_symbol(symbol: str, today: date, cached_slow: dict[str, Any] | None = None, refresh_slow: bool = False) -> dict[str, Any]:
    """Fetch fast endpoints and preserve slow FHSC factors between daily refreshes."""
    start, end = (today - timedelta(days=35)).isoformat(), today.isoformat()
    cached_slow = cached_slow or {}
    cached_raw = cached_slow.get("raw") or {}
    result: dict[str, Any] = {
        "refreshed_at": datetime.now(UTC).isoformat(), "errors": {},
        "endpoint_sources": {}, "raw": {}, "s_ff_net": None, "s_depth_wall": None,
        "s_prop_5d": finite(cached_slow.get("s_prop_5d")),
        "s_insider": finite(cached_slow.get("s_insider")),
    }
    for key in ("proprietary_net_5d", "proprietary_net_20d", "insider_buy_count", "insider_sell_count"):
        value = finite(cached_raw.get(key))
        if value is not None:
            result["raw"][key] = value
    if result["s_prop_5d"] is not None:
        result["endpoint_sources"]["proprietary_flow"] = "FHSC_CACHE"
    if result["s_insider"] is not None:
        result["endpoint_sources"]["insider_deal"] = "FHSC_CACHE"
    proprietary_rows: list[dict[str, Any]] = []
    insider_rows: list[dict[str, Any]] = []
    if refresh_slow:
        try:
            proprietary_rows = _records(Market("fhsc").equity(symbol).proprietary_flow(start=start, end=end, compat="v6", floating=2))
            score, raw = proprietary_score(proprietary_rows)
            if score is None:
                raise ValueError("FHSC proprietary_flow returned no usable values")
            result["s_prop_5d"], result["endpoint_sources"]["proprietary_flow"] = score, "FHSC"
            result["raw"].update(raw)
        except Exception as exc:
            result["errors"]["proprietary_flow_fhsc"] = _error(exc)
        try:
            insider_rows = _records(Market("fhsc").equity(symbol).insider_deal(compat="v6", floating=2))
            score, raw = insider_score(insider_rows)
            if score is None:
                raise ValueError("FHSC insider_deal returned no usable values")
            result["s_insider"], result["endpoint_sources"]["insider_deal"] = score, "FHSC"
            result["raw"].update(raw)
        except Exception as exc:
            result["errors"]["insider_deal_fhsc"] = _error(exc)
    foreign_rows: list[dict[str, Any]] = []
    for source in ("ssi", "fhsc"):
        try:
            foreign_rows = _records(Market(source).equity(symbol).foreign_flow(
                start=start, end=end, interval="1D", compat="v6", floating=2
            ))
            score, raw = foreign_score(foreign_rows)
            if score is not None:
                result["s_ff_net"] = score
                result["raw"].update(raw)
                result["endpoint_sources"]["foreign_flow"] = source.upper()
                break
            result["errors"][f"foreign_flow_{source}"] = {"type": "EmptyData"}
        except Exception as exc:
            result["errors"][f"foreign_flow_{source}"] = _error(exc)

    stats_rows: list[dict[str, Any]] = []
    try:
        stats_rows = _records(Market("ssi").equity(symbol).session_stats(
            start=today.isoformat(), end=end, compat="v6", floating=2
        ))
        average = average_trade_size(stats_rows)
        if not average:
            raise ValueError("SSI session_stats returned no average trade size")
        result["endpoint_sources"]["trade_size"] = "SSI"
    except Exception as exc:
        result["errors"]["session_stats_ssi"] = _error(exc)
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


def collect_market_factors(symbols: list[str], today: date, max_workers: int = 4, slow_cache: dict[str, dict[str, Any]] | None = None, refresh_slow: bool = False) -> dict[str, dict[str, Any]]:
    slow_cache = slow_cache or {}
    workers = max(1, min(int(max_workers), len(symbols) or 1))
    with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="vnstock6-market") as executor:
        values = list(executor.map(
            lambda symbol: fetch_symbol(symbol, today, slow_cache.get(symbol), refresh_slow), symbols
        ))
    return dict(zip(symbols, values))
