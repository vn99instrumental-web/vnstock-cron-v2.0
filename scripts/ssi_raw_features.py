"""SSI-owned feature materializer from immutable SSI/FHSC raw releases."""
from __future__ import annotations

import json
import math
import re
import unicodedata
from datetime import date, datetime
from pathlib import Path
from typing import Any, Iterable

from scripts.shared_raw_collector import ENDPOINTS, RAW_ROOT, load_current_manifest, read_dataset, verify_release


FORMULA_VERSION = "ssi-raw-features-1.0.0"

ALIASES = {
    "revenue": ("IS_NET_REVENUE", "IS_REVENUE", "IS_TOTAL_OPERATING_INCOME", "IS_NET_INTEREST_INCOME", "IS_TOTAL_NET_REVENUE_FROM_INSURANCE_BUSINESS"),
    "gross_profit": ("IS_GROSS_PROFIT", "IS_GROSS_INSURANCE_OPERATING_PROFIT"),
    "net_profit": ("IS_NET_PROFIT_AFTER_TAX_OF_PARENT", "IS_PROFIT_AFTER_TAX_FOR_SHAREHOLDERS_OF_PARENT_COMPANY", "IS_NET_PROFIT_AFTER_TAX", "IS_NET_PROFIT"),
    "total_assets": ("BS_TOTAL_ASSETS",),
    "current_assets": ("BS_SHORT_TERM_ASSETS", "BS_CURRENT_ASSETS"),
    "equity": ("BS_EQUITY", "BS_OWNER_S_EQUITY", "BS_OWNERS_EQUITY", "BS_TOTAL_EQUITY"),
    "liabilities": ("BS_TOTAL_LIABILITIES",),
    "current_liabilities": ("BS_SHORT_TERM_LIABILITIES", "BS_CURRENT_LIABILITIES"),
    "debt": ("BS_TOTAL_BORROWINGS", "BS_SHORT_TERM_BORROWINGS", "BS_LONG_TERM_BORROWINGS"),
    "cfo": ("CF_CASH_FLOW_FROM_OPERATING_ACTIVITIES", "CF_NET_CASH_FLOWS_FROM_OPERATING_ACTIVITIES", "CF_OPERATING"),
}


def finite(value: Any) -> float | None:
    try:
        number = float(value)
        return number if math.isfinite(number) else None
    except (TypeError, ValueError):
        return None


def _value(row: dict[str, Any], *names: str) -> Any:
    normalized = {str(key).lower().replace(" ", "_"): value for key, value in row.items()}
    for name in names:
        if name.lower() in normalized:
            return normalized[name.lower()]
    return None


def _date_text(row: dict[str, Any]) -> str:
    value = _value(row, "time", "date", "trading_date", "report_period", "period")
    return str(value or "")[:10]


def _period_key(value: Any) -> tuple[int, int] | None:
    text = str(value or "").strip().upper()
    match = re.fullmatch(r"(\d{4})[-/]?Q([1-4])", text)
    if match:
        return int(match.group(1)), int(match.group(2))
    match = re.fullmatch(r"(\d{4})-(\d{2})-(\d{2})", text)
    if match:
        return int(match.group(1)), (int(match.group(2)) - 1) // 3 + 1
    return None


def _signal_quarter(signal_date: str) -> tuple[int, int]:
    value = date.fromisoformat(signal_date)
    return value.year, (value.month - 1) // 3 + 1


def _statement_rows(rows: list[dict[str, Any]], signal_date: str) -> list[dict[str, Any]]:
    limit = _signal_quarter(signal_date)
    result = []
    for row in rows:
        period = _period_key(_value(row, "report_period", "period"))
        if period and period <= limit:
            result.append(row)
    return result


def _line_series(rows: list[dict[str, Any]], aliases: Iterable[str]) -> list[tuple[tuple[int, int], float]]:
    wanted = set(aliases)
    by_period: dict[tuple[int, int], float] = {}
    for row in rows:
        item = str(_value(row, "item_id", "id", "line_code") or "")
        period = _period_key(_value(row, "report_period", "period"))
        value = finite(_value(row, "item_value", "value"))
        if item in wanted and period and value is not None and period not in by_period:
            by_period[period] = value
    return sorted(by_period.items())


def _latest(rows: list[dict[str, Any]], name: str) -> float | None:
    series = _line_series(rows, ALIASES[name])
    return series[-1][1] if series else None


def _ttm(rows: list[dict[str, Any]], name: str) -> float | None:
    series = _line_series(rows, ALIASES[name])
    return sum(value for _, value in series[-4:]) if len(series) >= 4 else None


def _year_average(rows: list[dict[str, Any]], name: str) -> float | None:
    series = _line_series(rows, ALIASES[name])
    if not series:
        return None
    current_period, current = series[-1]
    prior = next((value for period, value in reversed(series[:-1]) if period == (current_period[0] - 1, current_period[1])), None)
    return (current + prior) / 2 if prior is not None else current


def _ratio(numerator: float | None, denominator: float | None) -> float | None:
    return numerator / denominator if numerator is not None and denominator not in (None, 0) else None


def _growth(rows: list[dict[str, Any]], name: str) -> float | None:
    series = _line_series(rows, ALIASES[name])
    if len(series) < 5:
        return None
    current_period, current = series[-1]
    prior = next((value for period, value in reversed(series[:-1]) if period == (current_period[0] - 1, current_period[1])), None)
    return current / abs(prior) - (1 if prior > 0 else -1) if prior not in (None, 0) else None


def _is_financial(industry: str | None) -> bool:
    text = unicodedata.normalize("NFKD", str(industry or "")).encode("ascii", "ignore").decode().lower()
    return any(term in text for term in ("ngan hang", "chung khoan", "bao hiem", "dich vu tai chinh", "bank", "securities", "insurance", "financial services"))


def fundamental_features(
    balance: list[dict[str, Any]], income: list[dict[str, Any]], cash: list[dict[str, Any]],
    signal_date: str, industry: str | None,
) -> dict[str, Any]:
    balance, income, cash = (_statement_rows(rows, signal_date) for rows in (balance, income, cash))
    revenue, gross, profit = _ttm(income, "revenue"), _ttm(income, "gross_profit"), _ttm(income, "net_profit")
    latest_profit = _latest(income, "net_profit")
    assets, equity = _year_average(balance, "total_assets"), _year_average(balance, "equity")
    current_assets, current_liabilities = _latest(balance, "current_assets"), _latest(balance, "current_liabilities")
    debt = _latest(balance, "debt")
    if debt is None:
        debt = _latest(balance, "liabilities")
    cfo = _latest(cash, "cfo")
    periods = [_period_key(_value(row, "report_period", "period")) for row in balance + income + cash]
    periods = [period for period in periods if period]
    latest_period = f"{max(periods)[0]}-Q{max(periods)[1]}" if periods else None
    return {
        "ratio_roe": _ratio(profit, equity),
        "ratio_roa": _ratio(profit, assets),
        "ratio_gross_margin": _ratio(gross, revenue),
        "ratio_net_margin": _ratio(profit, revenue),
        "ratio_current": _ratio(current_assets, current_liabilities),
        "ratio_debt_equity": _ratio(debt, equity),
        "growth_revenue_yoy": _growth(income, "revenue"),
        "growth_profit_yoy": _growth(income, "net_profit"),
        "cash_flow_operating": cfo,
        "cash_flow_quality": None if _is_financial(industry) else _ratio(cfo, latest_profit),
        "fundamental_metrics": {"industry": industry},
        "fundamental_period": latest_period,
        "fundamental_formula_version": FORMULA_VERSION,
        "fundamental_pit_policy": "release_fetch_time_and_report_period_not_after_signal_quarter",
    }


def _ema(values: list[float], span: int) -> float | None:
    if len(values) < span:
        return None
    alpha, result = 2 / (span + 1), values[0]
    for value in values[1:]:
        result = alpha * value + (1 - alpha) * result
    return result


def _rma(values: list[float], length: int) -> list[float | None]:
    result: list[float | None] = [None] * len(values)
    if len(values) < length:
        return result
    prior = sum(values[:length]) / length
    result[length - 1] = prior
    for index in range(length, len(values)):
        prior = (prior * (length - 1) + values[index]) / length
        result[index] = prior
    return result


def _adx_supertrend(rows: list[dict[str, Any]], length: int = 14, st_length: int = 10, multiplier: float = 3) -> tuple[float | None, float | None]:
    if len(rows) < max(length * 2, st_length + 2):
        return None, None
    highs = [float(row["high"]) for row in rows]
    lows = [float(row["low"]) for row in rows]
    closes = [float(row["close"]) for row in rows]
    tr, plus_dm, minus_dm = [], [], []
    for index in range(len(rows)):
        previous = closes[index - 1] if index else closes[index]
        tr.append(max(abs(highs[index] - lows[index]), abs(highs[index] - previous), abs(lows[index] - previous)))
        up = highs[index] - highs[index - 1] if index else 0
        down = lows[index - 1] - lows[index] if index else 0
        plus_dm.append(up if up > down and up > 0 else 0)
        minus_dm.append(down if down > up and down > 0 else 0)
    atr, plus_avg, minus_avg = _rma(tr, length), _rma(plus_dm, length), _rma(minus_dm, length)
    dx: list[float] = []
    for index in range(length - 1, len(rows)):
        if not atr[index]:
            dx.append(0)
            continue
        plus, minus = 100 * float(plus_avg[index] or 0) / float(atr[index]), 100 * float(minus_avg[index] or 0) / float(atr[index])
        dx.append(100 * abs(plus - minus) / (plus + minus) if plus + minus else 0)
    adx_values = _rma(dx, length)
    adx = next((value for value in reversed(adx_values) if value is not None), None)
    st_atr = _rma(tr, st_length)
    upper: list[float | None] = [None] * len(rows)
    lower: list[float | None] = [None] * len(rows)
    trend: list[float | None] = [None] * len(rows)
    for index in range(len(rows)):
        if st_atr[index] is None:
            continue
        middle = (highs[index] + lows[index]) / 2
        upper[index] = middle + multiplier * float(st_atr[index])
        lower[index] = middle - multiplier * float(st_atr[index])
        if index and upper[index - 1] is not None and closes[index - 1] <= float(upper[index - 1]):
            upper[index] = min(float(upper[index]), float(upper[index - 1]))
        if index and lower[index - 1] is not None and closes[index - 1] >= float(lower[index - 1]):
            lower[index] = max(float(lower[index]), float(lower[index - 1]))
        prior = trend[index - 1] if index else None
        if prior is None:
            trend[index] = lower[index] if closes[index] >= middle else upper[index]
        elif prior == upper[index - 1]:
            trend[index] = lower[index] if closes[index] > float(upper[index]) else upper[index]
        else:
            trend[index] = upper[index] if closes[index] < float(lower[index]) else lower[index]
    return finite(adx), finite(trend[-1])


def _normalized_ohlcv(rows: list[dict[str, Any]], signal_date: str) -> list[dict[str, Any]]:
    normalized = []
    for row in rows:
        values = {key: finite(_value(row, key)) for key in ("open", "high", "low", "close", "volume")}
        day = _date_text(row)
        if day and day <= signal_date and all(values[key] is not None for key in values):
            normalized.append({"date": day, **values})
    return sorted(normalized, key=lambda row: row["date"])


def technical_features(rows: list[dict[str, Any]], index_return20: float | None, signal_date: str) -> dict[str, Any]:
    data = _normalized_ohlcv(rows, signal_date)
    if not data:
        return {}
    close = [float(row["close"]) for row in data]
    high = [float(row["high"]) for row in data]
    low = [float(row["low"]) for row in data]
    volume = [float(row["volume"]) for row in data]
    price = close[-1]
    ret20 = (price / close[-21] - 1) * 100 if len(close) >= 21 and close[-21] else None
    ema200 = _ema(close, 200)
    high14, low14 = (max(high[-14:]), min(low[-14:])) if len(data) >= 14 else (None, None)
    stoch = (price - low14) / (high14 - low14) * 100 if high14 is not None and high14 != low14 else None
    mid = sum(close[-20:]) / 20 if len(close) >= 20 else None
    std = math.sqrt(sum((value - mid) ** 2 for value in close[-20:]) / 20) if mid is not None else None
    lower, upper = (mid - 2 * std, mid + 2 * std) if mid is not None and std is not None else (None, None)
    bb = (price - lower) / (upper - lower) if lower is not None and upper != lower else None
    high52, low52 = max(high[-252:]), min(low[-252:])
    vol_mean = sum(volume[-20:]) / min(20, len(volume))
    previous_volume = sum(volume[-5:-1]) / 4 if len(volume) >= 5 else None
    adx, supertrend = _adx_supertrend(data)
    return {
        "price": price, "entry": price,
        "previous_close": close[-2] if len(close) >= 2 else None,
        "willr_14": stoch - 100 if stoch is not None else None,
        "bb_position": bb,
        "price_vs_ema200_pct": (price / ema200 - 1) * 100 if ema200 else None,
        "relative_return_20d": ret20 - index_return20 if ret20 is not None and index_return20 is not None else None,
        "position_52w": (price - low52) / (high52 - low52) if high52 != low52 else None,
        "adx": adx, "supertrend": supertrend,
        "vol_ma_ratio": volume[-1] / vol_mean if vol_mean else None,
        "of_vol_spike_pct": volume[-1] / previous_volume * 100 - 100 if previous_volume else None,
        "adtv_20d_bil": sum(c * v for c, v in zip(close[-20:], volume[-20:])) / min(20, len(close)) / 1_000_000,
        "ohlcv_as_of": data[-1]["date"], "technical_formula_version": FORMULA_VERSION,
    }


def _sum_net(rows: list[dict[str, Any]], count: int, *, prefix: str = "foreign") -> float | None:
    values = []
    for row in sorted(rows, key=_date_text)[-count:]:
        net = finite(_value(row, f"{prefix}_net_value", "net_value", "net_val"))
        if net is None:
            buy = finite(_value(row, f"{prefix}_buy_value", "buy_value", "buy_val"))
            sell = finite(_value(row, f"{prefix}_sell_value", "sell_value", "sell_val"))
            net = buy - sell if buy is not None and sell is not None else None
        if net is not None:
            values.append(net)
    return sum(values) if values else None


def flow_features(foreign: list[dict[str, Any]], proprietary: list[dict[str, Any]], insider: list[dict[str, Any]], order_book: list[dict[str, Any]], session: list[dict[str, Any]]) -> dict[str, Any]:
    buy = sell = unclassified = 0
    for row in insider:
        kind = str(_value(row, "transaction_type", "deal_type", "type") or "").lower()
        if any(word in kind for word in ("mua", "buy", "purchase", "acqui")):
            buy += 1
        elif any(word in kind for word in ("bán", "ban", "sell", "dispos")):
            sell += 1
        else:
            unclassified += 1
    average = None
    if session:
        row = session[-1]
        volume = (finite(_value(row, "total_buy_trade_volume")) or 0) + (finite(_value(row, "total_sell_trade_volume")) or 0)
        count = (finite(_value(row, "total_buy_trade")) or 0) + (finite(_value(row, "total_sell_trade")) or 0)
        average = volume / count if count else None
    bid = ask = None
    if order_book and average:
        row = order_book[-1]
        bid_volume = sum(finite(_value(row, f"bid_volume_{level}", f"bid_vol_{level}")) or 0 for level in (1, 2, 3))
        ask_volume = sum(finite(_value(row, f"ask_volume_{level}", f"ask_vol_{level}")) or 0 for level in (1, 2, 3))
        bid, ask = bid_volume / average, ask_volume / average
    return {
        "foreign_net_5d": _sum_net(foreign, 5), "foreign_net_20d": _sum_net(foreign, 20),
        "proprietary_net_5d": _sum_net(proprietary, 5, prefix="proprietary"),
        "proprietary_net_20d": _sum_net(proprietary, 20, prefix="proprietary"),
        "insider_buy_count": buy if insider else None, "insider_sell_count": sell if insider else None,
        "insider_unclassified_count": unclassified if insider else None,
        "depth_bid_multiple": bid, "depth_ask_multiple": ask,
        "flow_formula_version": FORMULA_VERSION,
    }


def _by_symbol(release_dir: Path, endpoint: str) -> dict[str, dict[str, Any]]:
    path = ENDPOINTS[endpoint][1]
    if not (release_dir / path).exists():
        return {}
    return {str(value.get("symbol") or "").upper(): value for value in read_dataset(release_dir, path)}


def _rows(mapping: dict[str, dict[str, Any]], symbol: str) -> list[dict[str, Any]]:
    envelope = mapping.get(symbol) or {}
    return list(envelope.get("rows") or []) if envelope.get("status") == "success" else []


def build_feature_rows(release_dir: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    manifest = verify_release(release_dir)
    signal_date = str(manifest["signal_date"])
    maps = {endpoint: _by_symbol(release_dir, endpoint) for endpoint in ENDPOINTS if endpoint not in {"reference", "index_ohlcv"}}
    reference_values = read_dataset(release_dir, ENDPOINTS["reference"][1])
    reference_rows = list(reference_values[0].get("rows") or []) if reference_values else []
    industry_map = {str(_value(row, "symbol", "ticker", "code") or "").upper(): str(_value(row, "industry", "industry_name", "icb_name3") or "") or None for row in reference_rows}
    index_values = read_dataset(release_dir, ENDPOINTS["index_ohlcv"][1])
    index_raw = list(index_values[0].get("rows") or []) if index_values else []
    index_data = _normalized_ohlcv(index_raw, signal_date)
    index_close = [float(row["close"]) for row in index_data]
    index_return20 = (index_close[-1] / index_close[-21] - 1) * 100 if len(index_close) >= 21 and index_close[-21] else None
    created = datetime.fromisoformat(str(manifest["created_at"]).replace("Z", "+00:00"))
    market_context = {
        "vnindex_close": index_close[-1] if index_close else None,
        "vnindex_ema20": _ema(index_close, 20), "vnindex_ema50": _ema(index_close, 50),
        "vnindex_ema200": _ema(index_close, 200), "vnindex_return_20d": index_return20,
    }
    rows = []
    for symbol in manifest["universe"]:
        ohlcv = _rows(maps["ohlcv"], symbol)
        technical = technical_features(ohlcv, index_return20, signal_date)
        if not technical:
            continue
        fundamentals = fundamental_features(
            _rows(maps["balance_sheet"], symbol), _rows(maps["income_statement"], symbol),
            _rows(maps["cash_flow"], symbol), signal_date, industry_map.get(symbol),
        )
        flow = flow_features(
            _rows(maps["foreign_flow"], symbol), _rows(maps.get("proprietary_flow", {}), symbol),
            _rows(maps.get("insider_deal", {}), symbol), _rows(maps.get("order_book", {}), symbol),
            _rows(maps["session_stats"], symbol),
        )
        rows.append({
            "symbol": symbol, "signal_date": signal_date, "snap_time": created.strftime("%H:%M"),
            "snapshot_at": manifest["created_at"], "market_source": "SSI", "fundamental_source": "FHSC",
            "raw_release_id": manifest["release_id"], "input_layer": "shared_raw",
            "feature_engine": "ssi", "feature_version": FORMULA_VERSION,
            **market_context, **technical, **fundamentals, **flow,
        })
    return manifest, rows


def load_all_feature_rows(raw_root: Path = RAW_ROOT) -> list[dict[str, Any]]:
    releases = raw_root / "releases"
    rows: list[dict[str, Any]] = []
    for manifest_path in sorted(releases.glob("*/manifest.json")):
        _, current = build_feature_rows(manifest_path.parent)
        rows.extend(current)
    latest: dict[tuple[str, str], dict[str, Any]] = {}
    for row in rows:
        key = (row["signal_date"], row["symbol"])
        if key not in latest or str(row["snapshot_at"]) >= str(latest[key]["snapshot_at"]):
            latest[key] = row
    return [latest[key] for key in sorted(latest)]


def load_shared_ohlc(raw_root: Path = RAW_ROOT) -> dict[str, list[dict[str, Any]]]:
    combined: dict[str, dict[str, dict[str, Any]]] = {}
    for manifest_path in sorted((raw_root / "releases").glob("*/manifest.json")):
        release_dir = manifest_path.parent
        verify_release(release_dir)
        for envelope in read_dataset(release_dir, ENDPOINTS["ohlcv"][1]):
            symbol = str(envelope.get("symbol") or "")
            for row in _normalized_ohlcv(list(envelope.get("rows") or []), "9999-12-31"):
                combined.setdefault(symbol, {})[row["date"]] = row
    return {symbol: [values[key] for key in sorted(values)] for symbol, values in combined.items()}


def current_feature_rows(raw_root: Path = RAW_ROOT) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    release_dir, _ = load_current_manifest(raw_root)
    return build_feature_rows(release_dir)


if __name__ == "__main__":
    manifest, rows = current_feature_rows()
    print(json.dumps({"release_id": manifest["release_id"], "signal_date": manifest["signal_date"], "symbols": len(rows), "feature_version": FORMULA_VERSION}, sort_keys=True))
