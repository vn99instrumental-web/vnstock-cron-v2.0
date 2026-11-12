"""Availability-aware Gen6 scoring adapted from the production factor contract.

Only factors with complete inputs participate. Missing factors stay explicit and
the configured weights are renormalized across the available factors.
"""
from __future__ import annotations
from typing import Any

DECISION_THRESHOLDS = {"strong_buy": 55, "buy": 25, "sell": -25, "strong_sell": -55}


def _component(value: float | None, weight: float, reason: str | None = None) -> dict[str, Any]:
    included = value is not None
    return {
        "included": included,
        "value": None if value is None else round(max(-1.0, min(1.0, float(value))), 6),
        "configured_weight": float(weight),
        "reason": None if included else (reason or "missing_input"),
    }


def availability_score(inputs: dict[str, float | None], weights: dict[str, float]) -> dict[str, Any]:
    current, ema20, ema50 = inputs.get("price"), inputs.get("ema20"), inputs.get("ema50")
    trend = None
    if current is not None and ema20 is not None and ema50 is not None:
        trend = ((1 if current > ema20 else -1) + (1 if ema20 > ema50 else -1)) / 2

    rsi = inputs.get("rsi14")
    momentum = None if rsi is None else (1.0 if 45 <= rsi <= 70 else -0.8 if rsi > 75 else 0.67 if rsi < 30 else 0.0)
    ret20 = inputs.get("return20")
    breakout = None if ret20 is None else (1.0 if ret20 > 5 else -1.0 if ret20 < -5 else 0.0)
    volume_ratio = inputs.get("volume_ratio")
    liquidity = None if volume_ratio is None else (1.0 if volume_ratio >= 1.2 else -1.0 if volume_ratio < 0.5 else 0.0)

    factors = {
        "trend": _component(trend, weights["trend"]),
        "momentum": _component(momentum, weights["momentum"]),
        "breakout": _component(breakout, weights["breakout"]),
        "liquidity": _component(liquidity, weights["liquidity"]),
        "fundamental": _component(inputs.get("fundamental"), weights["fundamental"], "fundamental_not_normalized_per_symbol"),
        "growth": _component(inputs.get("growth"), weights["growth"], "growth_not_normalized_per_symbol"),
    }
    available_weight = sum(item["configured_weight"] for item in factors.values() if item["included"])
    if available_weight <= 0:
        raise ValueError("No scoring factor has complete input data")
    weighted = sum(item["configured_weight"] * item["value"] for item in factors.values() if item["included"])
    score = round(max(-100.0, min(100.0, 100.0 * weighted / available_weight)), 2)
    decision = (
        "STRONG BUY" if score >= DECISION_THRESHOLDS["strong_buy"] else
        "BUY" if score >= DECISION_THRESHOLDS["buy"] else
        "STRONG SELL" if score <= DECISION_THRESHOLDS["strong_sell"] else
        "SELL" if score <= DECISION_THRESHOLDS["sell"] else "NEUTRAL"
    )
    return {
        "score": score,
        "decision": decision,
        "factor_status": factors,
        "included_factors": [name for name, item in factors.items() if item["included"]],
        "excluded_factors": [name for name, item in factors.items() if not item["included"]],
        "available_weight": round(available_weight, 6),
        "configured_weight": round(sum(weights.values()), 6),
        "missing_data_policy": "exclude_and_renormalize",
    }