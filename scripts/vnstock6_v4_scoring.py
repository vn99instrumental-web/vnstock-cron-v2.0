"""V4-family scoring profiles calculated from auditable Gen6 inputs.

The profiles deliberately keep a ``v6.`` prefix: available technical and
fundamental signals follow the v4.17/v4.18/v4.19 factor architecture, while
signals requiring order-flow, foreign, proprietary or insider feeds remain
explicitly unavailable and are never fabricated as zero.
"""
from __future__ import annotations

import math
from typing import Any

import pandas as pd


PROFILES: dict[str, dict[str, Any]] = {
    "v6.4.17": {
        "weights": {"mean_reversion": .27, "breakout": .1307, "flow": .2724,
                    "fundamental": .2179, "growth": .109, "context": 0.0},
        "extras": True,
    },
    "v6.4.18": {
        "weights": {"mean_reversion": .50, "breakout": .05, "flow": .15,
                    "fundamental": .20, "growth": .10, "context": 0.0},
        "extras": True,
    },
    "v6.4.19-shadow": {
        "weights": {"mean_reversion": .05, "breakout": .15, "flow": .20,
                    "fundamental": .25, "growth": .35, "context": 0.0},
        "extras": False,
    },
}

HOLD_WEIGHTS = {"mean_reversion": .15, "breakout": .28, "flow": .12,
                "fundamental": .25, "growth": .15, "context": .05}
REGIMES = ("UPTREND", "SIDEWAYS", "RECOVERY", "DOWNTREND", "DEEP_DOWN", "UNKNOWN")
GATES = {
    "mean_reversion": (1, 1, 1, 1, 1, 1),
    "breakout": (.5, .7, .5, 1, 1, .5),
    "flow": (1, 1, 1, 1, 1, 1),
    "fundamental": (1, 1, .8, .8, .6, 1),
    "growth": (1, 1, .8, .8, .6, 1),
    "context": (1, 1, 1, 1, 1, 1),
}


def finite(value: Any) -> float | None:
    try:
        number = float(value)
        return number if math.isfinite(number) else None
    except (TypeError, ValueError):
        return None


def _clip(value: float, low: float = -1.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


def _position(value: float | None, low: float | None, high: float | None) -> float | None:
    if value is None or low is None or high is None or high == low:
        return None
    return _clip((value - low) / (high - low), 0.0, 1.0)


def indicator_snapshot(frame: pd.DataFrame, quant: dict[str, Any], index_return20: float | None) -> dict[str, Any]:
    data = frame.copy().sort_values("date")
    for column in ("open", "high", "low", "close", "volume"):
        data[column] = pd.to_numeric(data[column], errors="coerce")
    latest = data.iloc[-1]
    price = finite(latest["close"])
    close, high, low, volume = data["close"], data["high"], data["low"], data["volume"]
    ema200, atr14, obv = finite(quant.get("ema200")), finite(quant.get("atr14")), finite(quant.get("obv"))
    ret20 = finite((price / close.iloc[-21] - 1) * 100) if price and len(data) >= 21 else None
    vol_mean20 = finite(volume.tail(20).mean())
    vol_ratio = finite(volume.iloc[-1] / vol_mean20) if vol_mean20 else None
    high14, low14 = finite(high.tail(14).max()), finite(low.tail(14).min())
    high52, low52 = finite(high.tail(252).max()), finite(low.tail(252).min())
    stoch = None if price is None else (_position(price, low14, high14) * 100 if _position(price, low14, high14) is not None else None)
    willr = None if stoch is None else stoch - 100
    mid = finite(close.tail(20).mean())
    std = finite(close.tail(20).std(ddof=0))
    bb_low = None if mid is None or std is None else mid - 2 * std
    bb_high = None if mid is None or std is None else mid + 2 * std
    bb_position = _position(price, bb_low, bb_high)
    money_range = (high - low).replace(0, pd.NA)
    money_flow_multiplier = ((close - low) - (high - close)) / money_range
    cmf_den = finite(volume.tail(20).sum())
    cmf = finite((money_flow_multiplier * volume).tail(20).sum() / cmf_den) if cmf_den else None
    pos52 = _position(price, low52, high52)
    price_vs_ema200 = finite((price / ema200 - 1) * 100) if price and ema200 else None
    relative20 = None if ret20 is None or index_return20 is None else ret20 - index_return20
    adtv_bil = finite((close.tail(20) * volume.tail(20)).mean() / 1_000_000)
    ema12 = close.ewm(span=12, adjust=False).mean()
    ema26 = close.ewm(span=26, adjust=False).mean()
    macd_series = ema12 - ema26
    macd_signal_series = macd_series.ewm(span=9, adjust=False).mean()
    macd = finite(macd_series.iloc[-1])
    macd_signal = finite(macd_signal_series.iloc[-1])
    entry = price
    stop = finite(price - 1.5 * atr14) if price and atr14 else None
    tp1 = finite(price + 2 * atr14) if price and atr14 else None
    tp2 = finite(price + 3 * atr14) if price and atr14 else None
    return {
        "ema20": finite(quant.get("ema20")), "ema50": finite(quant.get("ema50")), "ema200": ema200, "adx": finite(quant.get("adx14")), "supertrend": finite(quant.get("supertrend")),
        "rsi_14": finite(quant.get("rsi14")), "atr_14": atr14,
        "atr_pct": finite(atr14 / price * 100) if atr14 and price else None, "obv": obv,
        "macd": macd, "macd_signal": macd_signal,
        "macd_histogram": finite(macd - macd_signal) if macd is not None and macd_signal is not None else None,
        "return_20d": ret20, "vnindex_return_20d": index_return20, "relative_return_20d": relative20,
        "vol_ma_ratio": vol_ratio, "adtv_bil": adtv_bil, "high_52w": high52, "low_52w": low52,
        "position_52w": pos52, "price_vs_ema200_pct": price_vs_ema200,
        "willr_14": willr, "stoch_k": stoch, "bb_mid": mid, "bb_lower": bb_low,
        "bb_upper": bb_high, "bb_position": bb_position, "cmf": cmf,
        "entry": entry, "stop": stop, "tp1": tp1, "tp2": tp2,
    }


def classify_regime(index_rows: list[dict[str, Any]], signal_date: str) -> dict[str, Any]:
    eligible = [row for row in index_rows if str(row.get("date", "")) < signal_date]
    if len(eligible) < 50:
        return {"regime": "UNKNOWN", "as_of": eligible[-1]["date"] if eligible else None,
                "return_20d": None, "reason": "insufficient_prior_vnindex_history"}
    frame = pd.DataFrame(eligible).sort_values("date")
    close = pd.to_numeric(frame["close"], errors="coerce")
    current = finite(close.iloc[-1])
    ema20 = finite(close.ewm(span=20, adjust=False).mean().iloc[-1])
    ema50 = finite(close.ewm(span=50, adjust=False).mean().iloc[-1])
    ema200 = finite(close.ewm(span=200, adjust=False).mean().iloc[-1]) if len(close) >= 200 else None
    ret20 = finite((current / close.iloc[-21] - 1) * 100) if current else None
    if current is None or ema20 is None or ema50 is None:
        regime = "UNKNOWN"
    elif ret20 is not None and ret20 <= -10 and ema200 is not None and current < ema200:
        regime = "DEEP_DOWN"
    elif current < ema20 < ema50:
        regime = "DOWNTREND"
    elif current > ema20 > ema50:
        regime = "UPTREND"
    elif current > ema20 and ema20 <= ema50:
        regime = "RECOVERY"
    else:
        regime = "SIDEWAYS"
    return {"regime": regime, "as_of": str(frame.iloc[-1]["date"]), "return_20d": ret20,
            "close": current, "ema20": ema20, "ema50": ema50, "ema200": ema200,
            "reason": "prior_close_only"}


def _depth_wall(market: dict[str,Any], price: float | None) -> float | None:
    rows=((market.get("raw") or {}).get("order_book") or [])
    if not rows or not price: return None
    normalized={str(key).lower().replace(" ","_"):value for key,value in rows[-1].items()}; avg=finite((market.get("raw") or {}).get("average_trade_size"))
    if not avg: return None
    bid=ask=0.0
    for i in (1,2,3):
        bp=finite(normalized.get(f"bid_price_{i}")); bv=finite(normalized.get(f"bid_volume_{i}")); ap=finite(normalized.get(f"ask_price_{i}")); av=finite(normalized.get(f"ask_volume_{i}"))
        if bp and bp>price*10: bp/=1000
        if ap and ap>price*10: ap/=1000
        if bp and bv and price*.98<=bp<=price*1.02: bid=max(bid,bv)
        if ap and av and price*.98<=ap<=price*1.02: ask=max(ask,av)
    def band(value): return 3 if value/avg>=250 else 2 if value/avg>=100 else 1 if value/avg>=40 else 0
    return float(max(-3,min(3,band(bid)-band(ask))))
def signal_values(ind: dict[str, Any], fundamental: dict[str, Any], regime: str, market: dict[str, Any] | None = None) -> dict[str, float | None]:
    market = market or {}
    willr, bb, overext, relative = ind.get("willr_14"), ind.get("bb_position"), ind.get("price_vs_ema200_pct"), ind.get("relative_return_20d")
    pos52, vol_ratio = ind.get("position_52w"), ind.get("vol_ma_ratio")
    values: dict[str, float | None] = {
        "s_willr_mr": None if willr is None else (6 if willr <= -80 else -6 if willr >= -20 else 0),
        "s_bb_mr": None if bb is None else (5 if bb <= .2 else -5 if bb >= .8 else 0),
        "s_overext_ema": None if overext is None else round(_clip(-overext / 10) * 3, 4),
        "s_rs_reversal": None if relative is None else round(_clip(-relative / 10) * 4, 4),
        "s_deep_dd": None if pos52 is None else (4 if pos52 < .2 else 0),
        "s_dist_52w": None if pos52 is None else (4 if pos52 >= .8 else 2 if pos52 >= .65 else 0),
        "s_trend_st": None if ind.get("supertrend") is None or ind.get("adx") is None or ind.get("entry") is None else ((4 if ind["adx"] >= 25 else 1 if ind["adx"] < 18 else 2) * (1 if ind["entry"] > ind["supertrend"] else -1)),
        "s_vol_ratio_h": None if vol_ratio is None else (3 if vol_ratio >= 1.5 else -3 if vol_ratio < .5 else 0),
        "s_ff_net": finite(market.get("s_ff_net")), "s_of_phasefix": finite(market.get("s_of_phasefix")), "s_prop_5d": finite(market.get("s_prop_5d")), "s_insider": finite(market.get("s_insider")),
        "s_depth_wall": _depth_wall(market, finite(ind.get("entry"))),
        "s_fund_core": None if fundamental.get("fundamental") is None else round(float(fundamental["fundamental"]) * 8, 4),
        "s_cf_core": None if fundamental.get("cash_flow") is None else round(float(fundamental["cash_flow"]) * 3, 4),
        "s_growth_core": None if fundamental.get("growth") is None else round(float(fundamental["growth"]) * 5, 4),
        "s_mkt_context": {"UPTREND": 2, "RECOVERY": 1, "SIDEWAYS": 0, "DOWNTREND": -1, "DEEP_DOWN": -2}.get(regime),
    }
    return values


def factor_values(signals: dict[str, float | None], include_extras: bool = True, horizon: str = "trade") -> dict[str, float | None]:
    def normalized(keys, cap):
        vals=[signals.get(key) for key in keys]
        if any(value is None for value in vals): return None
        return _clip(sum(float(value) for value in vals)/cap)
    def available_normalized(spans):
        present={key:signals.get(key) for key in spans if signals.get(key) is not None}
        if not present: return None
        return _clip(sum(float(value) for value in present.values())/sum(spans[key] for key in present))
    flow_spans={"s_ff_net":6,"s_of_phasefix":4,"s_prop_5d":3,"s_insider":2}
    if include_extras and horizon=="trade": flow_spans["s_depth_wall"]=3
    return {"mean_reversion":normalized(("s_willr_mr","s_bb_mr","s_overext_ema","s_rs_reversal","s_deep_dd"),22),"breakout":normalized(("s_dist_52w","s_trend_st"),8) if include_extras else normalized(("s_dist_52w",),4),"flow":available_normalized(flow_spans),"fundamental":available_normalized({"s_fund_core":8,"s_cf_core":3}) if include_extras else normalized(("s_fund_core",),8),"growth":normalized(("s_growth_core",),5),"context":normalized(("s_mkt_context",),2)}

def _decision(score: float) -> str:
    if score >= 50: return "STRONG BUY"
    if score >= 25: return "BUY"
    if score >= -10: return "NEUTRAL"
    if score >= -25: return "SELL"
    return "STRONG SELL"


def score_profile(version: str, factors: dict[str, float | None], regime: str, hold_factors: dict[str, float | None] | None = None) -> dict[str, Any]:
    profile = PROFILES[version]
    hold_factors = hold_factors or factors
    gate_index = REGIMES.index(regime if regime in REGIMES else "UNKNOWN")
    gates = {name: GATES[name][gate_index] for name in factors}

    def calculate(values: dict[str, float | None], weights: dict[str, float], extras: bool) -> tuple[float, dict[str, float], float, int]:
        included = {name: value for name, value in values.items() if value is not None and weights[name] > 0 and gates[name] > 0}
        available = sum(weights[name] * gates[name] for name in included)
        if available <= 0:
            raise ValueError(f"No available scoring factors for {version}")
        contributions = {name: 100 * weights[name] * gates[name] * float(value) / available for name, value in included.items()}
        raw = sum(contributions.values())
        aligned = sum(1 for value in included.values() if abs(float(value)) >= .3 and (raw == 0 or math.copysign(1, float(value)) == math.copysign(1, raw)))
        bonus = (5 if raw > 0 else -5) if extras and aligned >= 3 else 0
        return round(_clip(raw + bonus, -100, 100), 2), contributions, available, aligned

    trade, contributions, available, aligned = calculate(factors, profile["weights"], profile["extras"])
    hold, hold_contributions, hold_available, _ = calculate(hold_factors, HOLD_WEIGHTS, False)
    status = {
        name: {"included": value is not None, "value": value, "configured_weight": profile["weights"][name],
               "gate": gates[name], "reason": None if value is not None else "source_unavailable"}
        for name, value in factors.items()
    }
    return {
        "score_trade": trade, "total_score": trade, "score_hold": hold, "decision": _decision(trade),
        "confidence": "HIGH" if available >= .7 and aligned >= 3 else "MEDIUM" if available >= .5 else "LOW",
        "regime": regime, "gates": gates, "factor_status": status,
        "included_factors": [name for name, value in factors.items() if value is not None],
        "excluded_factors": [name for name, value in factors.items() if value is None],
        "available_weight": round(available, 6), "configured_weight": round(sum(profile["weights"].values()), 6),
        "hold_available_weight": round(hold_available, 6), "missing_data_policy": "exclude_and_renormalize",
        "n_supergroups_aligned": aligned, "confluence_bonus": (5 if trade > 0 else -5) if profile["extras"] and aligned >= 3 else 0,
        **{f"trade_{name}_norm": value for name, value in factors.items()},
        **{f"hold_{name}_norm": value for name, value in hold_factors.items()},
        "factor_contributions": contributions, "hold_factor_contributions": hold_contributions,
    }
