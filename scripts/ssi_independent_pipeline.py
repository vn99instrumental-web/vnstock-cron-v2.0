"""Independent SSI scoring from immutable provider-raw SSI + FHSC releases.

This module deliberately does not import the Gen6 scorer and never consumes
Gen6 features, ratios, signals, scores or decisions. Gen6 and SSI may share
only the immutable provider-raw release ID.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from scripts.ssi_raw_features import FORMULA_VERSION, load_all_feature_rows, load_shared_ohlc

ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "config" / "ssi_independent.json"
SSI_SERVING = ROOT / "output" / "serving" / "ssi" / "current"
SSI_HISTORY = ROOT / "output" / "history" / "ssi-independent" / "predictions"
WEB_DATA = ROOT / "web" / "data" / "ssi-independent-dashboard.json"

SIGNAL_SPANS = {
    "willr_mr": 6, "bb_mr": 5, "overext_ema": 3,
    "rs_reversal": 4, "deep_dd": 4, "dist_52w": 4,
    "trend_st": 4, "vol_ratio_h": 3, "ff_net": 6,
    "of_phasefix": 4, "prop_5d": 3, "insider": 2,
    "depth_wall": 3, "fund_core": 8, "cf_core": 3,
    "growth_core": 5, "mkt_context": 2,
}
REGIMES = ("UPTREND", "SIDEWAYS", "RECOVERY", "DOWNTREND", "DEEP_DOWN", "UNKNOWN")
GATES = {
    "mean_reversion": (1, 1, 1, 1, 1, 1),
    "breakout": (.5, .7, .5, 1, 1, .5),
    "flow": (1, 1, 1, 1, 1, 1),
    "fundamental": (1, 1, .8, .8, .6, 1),
    "growth": (1, 1, .8, .8, .6, 1),
    "context": (1, 1, 1, 1, 1, 1),
}
FRACTION_ANCHORS = (
    (570, .08), (595, .18), (655, .38), (690, .46), (780, .46),
    (805, .66), (835, .74), (870, .92), (895, 1.0),
)


def finite(value: Any) -> float | None:
    try:
        number = float(value)
        return number if math.isfinite(number) else None
    except (TypeError, ValueError):
        return None


def clip(value: float, low: float = -1.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


def expected_fraction(snap_time: Any) -> float | None:
    try:
        hours, minutes = str(snap_time).split(":")[:2]
        minute = int(hours) * 60 + int(minutes)
    except (ValueError, AttributeError):
        return None
    if minute < FRACTION_ANCHORS[0][0]:
        return None
    if minute >= FRACTION_ANCHORS[-1][0]:
        return 1.0
    for (m1, f1), (m2, f2) in zip(FRACTION_ANCHORS, FRACTION_ANCHORS[1:]):
        if m1 <= minute <= m2:
            return f1 + (f2 - f1) * (minute - m1) / (m2 - m1)
    return None


def independent_regime(row: dict[str, Any]) -> str:
    close = finite(row.get("vnindex_close"))
    ema20 = finite(row.get("vnindex_ema20"))
    ema50 = finite(row.get("vnindex_ema50"))
    ema200 = finite(row.get("vnindex_ema200"))
    ret20 = finite(row.get("vnindex_return_20d"))
    if close is None or ema20 is None or ema50 is None:
        return "UNKNOWN"
    if ret20 is not None and ret20 <= -10 and ema200 is not None and close < ema200:
        return "DEEP_DOWN"
    if close < ema20 < ema50:
        return "DOWNTREND"
    if close > ema20 > ema50:
        return "UPTREND"
    if close > ema20 and ema20 <= ema50:
        return "RECOVERY"
    return "SIDEWAYS"


def _foreign_signal(row: dict[str, Any]) -> float | None:
    net5 = finite(row.get("foreign_net_5d"))
    net20 = finite(row.get("foreign_net_20d"))
    adtv = finite(row.get("adtv_20d_bil"))
    if net5 is None or adtv is None or adtv <= 0:
        return None
    intensity = net5 / (adtv * 1_000_000_000 * 5)
    if abs(intensity) < .02:
        raw = 0
    else:
        aligned = net20 is not None and (net20 >= 0) == (net5 >= 0)
        magnitude = 6 if abs(intensity) >= .10 and aligned else 4 if abs(intensity) >= .05 else 2
        raw = magnitude if net5 > 0 else -magnitude
    return float(raw)


def _proprietary_signal(row: dict[str, Any]) -> float | None:
    net5 = finite(row.get("proprietary_net_5d"))
    net20 = finite(row.get("proprietary_net_20d"))
    if net5 is None:
        return None
    bil = net5 / 1_000_000_000
    aligned = net20 is not None and (net20 >= 0) == (net5 >= 0)
    magnitude = 3 if abs(bil) >= 5 and aligned else 2 if abs(bil) >= 2 else 1 if abs(bil) >= .5 else 0
    return float(magnitude if net5 > 0 else -magnitude)


def _insider_signal(row: dict[str, Any]) -> float | None:
    buy = finite(row.get("insider_buy_count"))
    sell = finite(row.get("insider_sell_count"))
    unclassified = finite(row.get("insider_unclassified_count"))
    if buy is None or sell is None or (unclassified or 0) > 0 or buy + sell <= 0:
        return None
    net = buy - sell
    return 2.0 if net >= 3 else 1.0 if net >= 1 else 0.0 if net == 0 else -1.0 if net >= -2 else -2.0


def _depth_signal(row: dict[str, Any]) -> float | None:
    bid_multiple = finite(row.get("depth_bid_multiple"))
    ask_multiple = finite(row.get("depth_ask_multiple"))
    if bid_multiple is None or ask_multiple is None:
        return None
    def band(value: float) -> int:
        return 3 if value >= 250 else 2 if value >= 100 else 1 if value >= 40 else 0
    return float(max(-3, min(3, band(bid_multiple) - band(ask_multiple))))


def _fundamental_signal(row: dict[str, Any]) -> float | None:
    specs = (
        ("ratio_roe", .15, .15, False),
        ("ratio_roa", .07, .08, False),
        ("ratio_gross_margin", .25, .25, False),
        ("ratio_net_margin", .10, .15, False),
        ("ratio_current", 1.5, 1.5, False),
        ("ratio_debt_equity", 1.5, 1.5, True),
    )
    parts: list[float] = []
    for key, center, scale, invert in specs:
        value = finite(row.get(key))
        if value is None:
            continue
        parts.append(clip((center - value if invert else value - center) / scale))
    return round(sum(parts) / len(parts) * 8, 4) if parts else None


def _growth_signal(row: dict[str, Any]) -> float | None:
    values = [finite(row.get(key)) for key in ("growth_revenue_yoy", "growth_profit_yoy")]
    present = [value for value in values if value is not None]
    return round(sum(clip(value / .25) for value in present) / len(present) * 5, 4) if present else None


def _cashflow_signal(row: dict[str, Any]) -> float | None:
    industry = str(((row.get("fundamental_metrics") or {}).get("industry") or "")).lower()
    if any(word in industry for word in ("ngân hàng", "chứng khoán", "bảo hiểm", "bank", "securities", "insurance")):
        return None
    operating = finite(row.get("cash_flow_operating"))
    quality = finite(row.get("cash_flow_quality"))
    parts: list[float] = []
    if operating is not None:
        parts.append(5 if operating > 0 else -10)
    if quality is not None:
        parts.append(5 if quality > 1 else -5 if quality < .5 else 0)
    return round(clip((sum(parts) / len(parts)) / 10) * 3) if parts else None


def independent_signals(row: dict[str, Any], regime: str) -> dict[str, float | None]:
    willr = finite(row.get("willr_14"))
    bb = finite(row.get("bb_position"))
    overext = finite(row.get("price_vs_ema200_pct"))
    relative = finite(row.get("relative_return_20d"))
    pos52 = finite(row.get("position_52w"))
    adx = finite(row.get("adx"))
    supertrend = finite(row.get("supertrend"))
    price = finite(row.get("price")) or finite(row.get("entry"))
    vol_ratio = finite(row.get("vol_ma_ratio"))
    spike = finite(row.get("of_vol_spike_pct"))
    fraction = expected_fraction(row.get("snap_time"))
    if spike is None or fraction is None or fraction <= 0:
        phase = None
    else:
        adjusted = ((1 + spike / 100) / fraction - 1) * 100
        phase = 4.0 if adjusted > 50 else 2.0 if adjusted > 20 else -4.0 if adjusted < -50 else -2.0 if adjusted < -20 else 0.0
    return {
        "willr_mr": None if willr is None else 6.0 if willr <= -80 else -6.0 if willr >= -20 else 0.0,
        "bb_mr": None if bb is None else 5.0 if bb <= .2 else -5.0 if bb >= .8 else 0.0,
        "overext_ema": None if overext is None else round(clip(-overext / 10) * 3, 4),
        "rs_reversal": None if relative is None else round(clip(-relative / 10) * 4, 4),
        "deep_dd": None if pos52 is None else 4.0 if pos52 < .2 else 0.0,
        "dist_52w": None if pos52 is None else 4.0 if pos52 >= .8 else 2.0 if pos52 >= .65 else 0.0,
        "trend_st": None if adx is None or supertrend is None or price is None else float((4 if adx >= 25 else 1 if adx < 18 else 2) * (1 if price > supertrend else -1)),
        "vol_ratio_h": None if vol_ratio is None else 3.0 if vol_ratio >= 1.5 else -3.0 if vol_ratio < .5 else 0.0,
        "ff_net": _foreign_signal(row),
        "of_phasefix": phase,
        "prop_5d": _proprietary_signal(row),
        "insider": _insider_signal(row),
        "depth_wall": _depth_signal(row),
        "fund_core": _fundamental_signal(row),
        "cf_core": _cashflow_signal(row),
        "growth_core": _growth_signal(row),
        "mkt_context": {"UPTREND": 2.0, "RECOVERY": 1.0, "SIDEWAYS": 0.0, "DOWNTREND": -1.0, "DEEP_DOWN": -2.0}.get(regime),
    }


def factor_values(signals: dict[str, float | None], horizon: str) -> dict[str, float | None]:
    def strict(keys: Iterable[str], cap: float) -> float | None:
        values = [signals.get(key) for key in keys]
        return None if any(value is None for value in values) else clip(sum(float(value) for value in values if value is not None) / cap)
    def available(spans: dict[str, int]) -> float | None:
        values = {key: signals.get(key) for key in spans if signals.get(key) is not None}
        return clip(sum(float(value) for value in values.values()) / sum(spans[key] for key in values)) if values else None
    flow = {"ff_net": 6, "of_phasefix": 4, "prop_5d": 3, "insider": 2}
    if horizon == "trade":
        flow["depth_wall"] = 3
    return {
        "mean_reversion": strict(("willr_mr", "bb_mr", "overext_ema", "rs_reversal", "deep_dd"), 22),
        "breakout": strict(("dist_52w", "trend_st"), 8),
        "flow": available(flow),
        "fundamental": available({"fund_core": 8, "cf_core": 3}),
        "growth": strict(("growth_core",), 5),
        "context": strict(("mkt_context",), 2),
    }


def _decision(score: float, thresholds: dict[str, Any]) -> str:
    if score >= thresholds["strong_buy"]:
        return "STRONG BUY"
    if score >= thresholds["buy"]:
        return "BUY"
    if score <= thresholds["strong_sell"]:
        return "STRONG SELL"
    if score <= thresholds["sell"]:
        return "SELL"
    return "NEUTRAL"


def score_factors(factors: dict[str, float | None], regime: str, weights: dict[str, float], *, bonus: bool) -> dict[str, Any]:
    gate_index = REGIMES.index(regime if regime in REGIMES else "UNKNOWN")
    gates = {name: GATES[name][gate_index] for name in factors}
    included = {name: float(value) for name, value in factors.items() if value is not None and weights[name] > 0 and gates[name] > 0}
    available_weight = sum(weights[name] * gates[name] for name in included)
    if available_weight <= 0:
        raise ValueError("NO_AVAILABLE_SSI_SCORING_FACTORS")
    contributions = {name: 100 * weights[name] * gates[name] * value / available_weight for name, value in included.items()}
    raw = sum(contributions.values())
    aligned = sum(1 for value in included.values() if abs(value) >= .3 and (raw == 0 or math.copysign(1, value) == math.copysign(1, raw)))
    confluence = (5 if raw > 0 else -5) if bonus and aligned >= 3 else 0
    return {
        "score": round(clip(raw + confluence, -100, 100), 2),
        "available_weight": round(available_weight, 6),
        "n_aligned": aligned,
        "confluence_bonus": confluence,
        "contributions": contributions,
        "gates": gates,
    }


def score_row(row: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    if row.get("market_source") != config["sources"]["market"]:
        raise ValueError("SSI_INPUT_MARKET_SOURCE_MUST_BE_SSI")
    if row.get("fundamental_source") != config["sources"]["fundamental"]:
        raise ValueError("SSI_INPUT_FUNDAMENTAL_SOURCE_MUST_BE_FHSC")
    regime = independent_regime(row)
    signals = independent_signals(row, regime)
    trade_factors = factor_values(signals, "trade")
    hold_factors = factor_values(signals, "hold")
    trade = score_factors(trade_factors, regime, config["weights"]["trade"], bonus=True)
    hold = score_factors(hold_factors, regime, config["weights"]["hold"], bonus=False)
    signal_date = str(row.get("signal_date") or "")
    snap_time = str(row.get("snap_time") or "")
    symbol = str(row.get("symbol") or "")
    digest = hashlib.sha256(f"ssi|{symbol}|{signal_date}|{snap_time}|{config['version']}".encode()).hexdigest()[:20]
    non_null = sum(value is not None for value in signals.values())
    return {
        "pred_id": f"ssi_{digest}", "symbol": symbol,
        "signal_date": signal_date, "snap_time": snap_time,
        "snapshot_at": row.get("snapshot_at"), "scoring_version": config["version"],
        "pipeline_generation": "SSI_INDEPENDENT_2", "market_source": "SSI",
        "fundamental_source": "FHSC", "data_origin": "shared_raw_independent_calculation",
        "calculation_engine": "ssi_independent_python", "calculation_version": "2.0.0",
        "input_feature_version": row.get("feature_version") or FORMULA_VERSION,
        "raw_release_id": row.get("raw_release_id"), "input_layer": "shared_raw",
        "price": finite(row.get("price")), "previous_close": finite(row.get("previous_close")),
        "regime": regime, "market_regime": regime,
        "score_trade": trade["score"], "total_score": trade["score"], "score_hold": hold["score"],
        "decision": _decision(trade["score"], config["decision_thresholds"]),
        "confidence": "HIGH" if trade["available_weight"] >= .7 and trade["n_aligned"] >= 3 else "MEDIUM" if trade["available_weight"] >= .5 else "LOW",
        "available_weight": trade["available_weight"], "configured_weight": round(sum(config["weights"]["trade"].values()), 6),
        "missing_data_policy": config["missing_data_policy"],
        "signal_coverage": non_null, "signal_count": len(SIGNAL_SPANS),
        "missing_signals": [name for name, value in signals.items() if value is None],
        "signals": signals, "factors": trade_factors, "hold_factors": hold_factors,
        "factor_contributions": trade["contributions"], "hold_factor_contributions": hold["contributions"],
        "n_supergroups_aligned": trade["n_aligned"], "confluence_bonus": trade["confluence_bonus"],
        "source_provenance": {
            "market": "SSI", "fundamental": "FHSC",
            "feature_layer": row.get("feature_version") or FORMULA_VERSION,
            "raw_release_id": row.get("raw_release_id"),
            "input_layer": "shared_raw", "bctc_engine": "ssi",
            "standalone": True, "gen6_dependencies": [],
            "gen6_scores_consumed": False, "gen6_signals_consumed": False,
        },
    }


def load_input_rows(config: dict[str, Any]) -> list[dict[str, Any]]:
    del config
    return load_all_feature_rows()

def attach_outcomes(rows: list[dict[str, Any]], ohlc_by_symbol: dict[str, list[dict[str, Any]]]) -> None:
    by_symbol: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        by_symbol.setdefault(row["symbol"], []).append(row)
    for symbol, predictions in by_symbol.items():
        prices = ohlc_by_symbol.get(symbol, [])
        for prediction in predictions:
            later = [item for item in prices if str(item.get("date")) > prediction["signal_date"]]
            base = finite(prediction.get("price"))
            for horizon in (3, 5, 10):
                key = f"ret_{horizon}d"
                prediction[key] = round((finite(later[horizon - 1]["close"]) / base - 1) * 100, 4) if base and len(later) >= horizon else None


def _pearson(pairs: list[tuple[float, float]]) -> float | None:
    if len(pairs) < 3:
        return None
    xs, ys = zip(*pairs)
    mx, my = sum(xs) / len(xs), sum(ys) / len(ys)
    numerator = sum((x - mx) * (y - my) for x, y in pairs)
    denominator = math.sqrt(sum((x - mx) ** 2 for x in xs) * sum((y - my) ** 2 for y in ys))
    return round(numerator / denominator, 6) if denominator else None


def ic_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for horizon in (3, 5, 10):
        pairs = [(float(row["score_trade"]), float(row[f"ret_{horizon}d"])) for row in rows if row.get(f"ret_{horizon}d") is not None]
        result[f"ret_{horizon}d"] = {"n": len(pairs), "pearson": _pearson(pairs)}
    return result


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def build(required_raw_release_id: str | None = None) -> dict[str, Any]:
    config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    input_rows = load_input_rows(config)
    scored = [score_row(row, config) for row in input_rows]
    if not scored:
        raise RuntimeError("NO_IMMUTABLE_SHARED_RAW_SSI_FHSC_INPUT_ROWS")
    attach_outcomes(scored, load_shared_ohlc())
    dates = sorted({row["signal_date"] for row in scored})
    latest_date = dates[-1]
    latest = sorted((row for row in scored if row["signal_date"] == latest_date), key=lambda row: row["symbol"])
    if required_raw_release_id and any(row.get("raw_release_id") != required_raw_release_id for row in latest):
        raise RuntimeError(f"SSI_RAW_RELEASE_NOT_LATEST:{required_raw_release_id}")
    if len(latest) < 80:
        raise RuntimeError(f"SSI_LATEST_COVERAGE_BELOW_80:{len(latest)}")
    generated = datetime.now(timezone.utc).isoformat()
    ic = ic_summary(scored)
    summary = {
        "symbols": len(latest), "history_dates": len(dates), "history_rows": len(scored),
        "buy": sum(row["decision"] in {"BUY", "STRONG BUY"} for row in latest),
        "sell": sum(row["decision"] in {"SELL", "STRONG SELL"} for row in latest),
        "full_17_signal_rows": sum(row["signal_coverage"] == 17 for row in latest),
        "minimum_signal_coverage": min(row["signal_coverage"] for row in latest),
        "scored_symbols": len(latest),
    }
    compact_history = [
        {key: row.get(key) for key in (
            "pred_id", "symbol", "signal_date", "snap_time", "price", "score_trade", "score_hold",
            "decision", "confidence", "signal_coverage", "ret_3d", "ret_5d", "ret_10d",
        )} for row in sorted(scored, key=lambda value: (value["signal_date"], value["symbol"]), reverse=True)
    ]
    dashboard = {
        "schema_version": 1, "version": config["version"], "generated_at": generated,
        "signal_date": latest_date, "source_provenance": {
            "market": "SSI", "fundamental": "FHSC", "input_layer": "shared_raw",
            "raw_release_id": latest[0].get("raw_release_id"), "feature_engine": "ssi",
            "bctc_engine": "ssi", "standalone": True, "gen6_dependencies": [],
            "calculation": "SSI independent from immutable provider raw; no Gen6 artifact consumed",
        },
        "summary": summary, "latest": latest, "history": compact_history, "ic": ic,
    }
    _write_json(SSI_SERVING / "dashboard.json", dashboard)
    _write_json(SSI_SERVING / "metadata.json", {key: dashboard[key] for key in ("schema_version", "version", "generated_at", "signal_date", "source_provenance", "summary")})
    _write_json(SSI_SERVING / "today" / f"{config['version']}.json", {"version": config["version"], "signal_date": latest_date, "signals": latest, "summary": summary})
    _write_json(SSI_SERVING / "buy" / f"{config['version']}.json", {"version": config["version"], "signal_date": latest_date, "signals": [row for row in latest if row["decision"] in {"BUY", "STRONG BUY"}], "summary": summary})
    _write_json(SSI_SERVING / "history" / f"{config['version']}.json", {"version": config["version"], "rows": compact_history})
    _write_json(SSI_SERVING / "ic.json", {"version": config["version"], "generated_at": generated, "metrics": ic})
    _write_json(WEB_DATA, dashboard)
    for date_value in dates:
        path = SSI_HISTORY / f"{date_value}.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        date_rows = [row for row in scored if row["signal_date"] == date_value]
        path.write_text("".join(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n" for row in date_rows), encoding="utf-8")
    return dashboard


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("build",), default="build", nargs="?")
    parser.add_argument("--raw-release-id")
    args = parser.parse_args()
    dashboard = build(args.raw_release_id)
    print(json.dumps({"version": dashboard["version"], "signal_date": dashboard["signal_date"], **dashboard["summary"]}, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
