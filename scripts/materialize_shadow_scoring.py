#!/usr/bin/env python3
"""Materialize the forward-only IC-weighted shadow from a v4.18 snapshot.

The shadow reuses the factor norms and market regime already calculated by the
production scorer. It does not call a market API, mutate production rows, or
feed any notification path.
"""
from __future__ import annotations

import copy
import json
import math
from pathlib import Path
from typing import Iterable


ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / "config" / "scoring" / "v4.19-shadow.json"
PARENT_VERSION = "v4.18"
SHADOW_VERSION = "v4.19-shadow"
FACTORS = ("mean_reversion", "breakout", "flow", "fundamental", "growth", "context")
TRADE_FACTORS = FACTORS[:-1]
CONF_HI, CONF_MD = 80, 60
CONF_DISAGREE_MIN_GROSS = 0.45
CONF_DISAGREE_MAXPEN = 35
STALE_SHADOW_FIELDS = (
    "score_trade_altfund", "decision_altfund", "_alt_fund_pts", "_altfund_delta",
    "score_trade_nomr", "decision_nomr", "_nomr_delta",
    "score_trade_rank", "decision_rank", "_rank_delta",
    "score_trade_gate1", "decision_gate1", "_gate1_delta", "_extras_guard",
)


def _load_config(path: Path = CONFIG_PATH) -> dict:
    config = json.loads(path.read_text(encoding="utf-8"))
    if config.get("version_label") != SHADOW_VERSION or config.get("status") != "shadow":
        raise ValueError(f"invalid shadow config: {path}")
    weights = config.get("factor_weights", {}).get("trade", {})
    if set(weights) != set(FACTORS) or not math.isclose(sum(weights.values()), 1.0, abs_tol=1e-9):
        raise ValueError("shadow trade weights must cover six factors and total 1.0")
    return config


def _number(value, field: str) -> float:
    if isinstance(value, bool):
        raise ValueError(f"{field} must be numeric")
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} must be numeric") from exc
    if not math.isfinite(result):
        raise ValueError(f"{field} must be finite")
    return result


def _gates(config: dict, regime: str) -> dict[str, float]:
    matrix = config["gate_matrix"]
    regimes = matrix["regimes"]
    try:
        index = regimes.index(regime)
    except ValueError:
        index = regimes.index("UNKNOWN")
    return {factor: _number(matrix[factor][index], f"gate.{factor}") for factor in FACTORS}


def _weight_profile(weights: dict[str, float]) -> str:
    aliases = {
        "mean_reversion": "mr", "breakout": "bo", "flow": "flow",
        "fundamental": "fund", "growth": "growth",
    }
    return "_".join(
        f"{aliases[factor]}{int(round(weights[factor] * 100))}" for factor in TRADE_FACTORS
    )


def _decision(score: float, w_regime: float, thresholds: list[dict]) -> str:
    for threshold in thresholds:
        minimum = threshold["min"]
        if minimum is None or score >= _number(minimum, "threshold.min") * w_regime:
            return str(threshold["decision"])
    raise ValueError("shadow thresholds do not contain a fallback")


def _confidence(row: dict, weights: dict[str, float], gates: dict[str, float]) -> tuple[int, str]:
    score = 100.0
    for missing in row.get("data_missing") or []:
        text = str(missing)
        if "Giá" in text and "(" not in text:
            score -= 40
        elif "(" in text:
            score -= 5
        else:
            score -= 18
    if row.get("_regime") == "UNKNOWN":
        score -= 25
    if row.get("_regime_divergence"):
        score -= 6
    stale_days = _number(row.get("_ta_stale_days") or 0, "_ta_stale_days")
    if stale_days > 0:
        score -= min(4 * stale_days, 12)
    if row.get("_of_distribution") == "INSUFFICIENT_DATA":
        score -= 5

    raw_norms = [
        gates[factor] * _number(row.get(f"trade_{factor}_norm") or 0, f"trade_{factor}_norm")
        for factor in TRADE_FACTORS
    ]
    weighted_norms = [weights[factor] * norm for factor, norm in zip(TRADE_FACTORS, raw_norms)]
    if sum(abs(norm) for norm in raw_norms) >= CONF_DISAGREE_MIN_GROSS:
        gross = sum(abs(norm) for norm in weighted_norms)
        agreement = abs(sum(weighted_norms)) / gross if gross else 1.0
        score -= (1 - agreement) * CONF_DISAGREE_MAXPEN

    pct = int(max(0.0, min(100.0, round(score))))
    label = "HIGH" if pct >= CONF_HI else "MEDIUM" if pct >= CONF_MD else "LOW"
    return pct, label


def materialize_shadow_row(row: dict, config: dict | None = None) -> dict:
    """Return one isolated shadow row derived from one production row."""
    if row.get("scoring_version") != PARENT_VERSION:
        raise ValueError(f"shadow parent must be {PARENT_VERSION}")
    if not row.get("symbol"):
        raise ValueError("shadow parent row has no symbol")

    config = config or _load_config()
    weights = config["factor_weights"]["trade"]
    regime = str(row.get("_regime") or "UNKNOWN")
    gates = _gates(config, regime)
    norms = {
        factor: _number(row.get(f"trade_{factor}_norm"), f"trade_{factor}_norm")
        for factor in FACTORS
    }
    core_score = 100.0 * sum(weights[factor] * gates[factor] * norms[factor] for factor in FACTORS)
    core_score = max(-100.0, min(100.0, core_score))
    w_regime = sum(weights[factor] * gates[factor] for factor in FACTORS)
    if w_regime <= 1e-9:
        w_regime = 1.0

    shadow = copy.deepcopy(row)
    for field in STALE_SHADOW_FIELDS:
        shadow.pop(field, None)
    shadow.update({
        "scoring_version": SHADOW_VERSION,
        "score_trade": round(core_score, 2),
        "total_score": round(core_score, 2),
        "decision": _decision(core_score, w_regime, config["thresholds"]),
        "_gates": gates,
        "_w_regime": round(w_regime, 4),
        "confluence_bonus": 0,
        "n_supergroups_aligned": 0,
        "shadow_parent_version": PARENT_VERSION,
        "shadow_method": f"{config['weight_method']['name']}_core",
        "shadow_weight_profile": _weight_profile(weights),
        "shadow_core_only": True,
    })
    confidence_pct, confidence = _confidence(shadow, weights, gates)
    shadow["confidence_pct"] = confidence_pct
    shadow["confidence"] = confidence
    shadow["confidence_method"] = "data+weighted-consistency_v4.19-shadow"

    if shadow.get("regime_v42") == "RECOVERY" and shadow["decision"] in ("BUY", "STRONG BUY"):
        shadow["recovery_warn"] = True
        if shadow["confidence"] == "HIGH":
            shadow["confidence"] = "MEDIUM"
            shadow["confidence_pct"] = min(shadow["confidence_pct"], CONF_HI - 1)
    return shadow


def materialize_shadow_rows(rows: Iterable[dict], config_path: Path = CONFIG_PATH) -> list[dict]:
    config = _load_config(config_path)
    shadows = [materialize_shadow_row(row, config) for row in rows]
    symbols = [row["symbol"] for row in shadows]
    if len(symbols) != len(set(symbols)):
        raise ValueError("shadow output contains duplicate symbols")
    return shadows


__all__ = ["materialize_shadow_row", "materialize_shadow_rows"]
