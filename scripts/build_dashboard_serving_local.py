#!/usr/bin/env python3
"""Publish dashboard snapshots from the Git ledger without reading Supabase.

The committed ``output/serving/current`` release is used only as an incremental
baseline for derived datasets that do not change during an intraday run.  New
runs, signals, history, charts and locally available outcomes always come from
the ledger in this checkout.  ``--full`` additionally recomputes forward IC
and BUY expectancy from the complete local ledger.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import logging
import shutil
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from itertools import combinations
from pathlib import Path
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from export_ic_to_supabase import (  # noqa: E402
    FACTOR_COLS,
    HORIZONS,
    LEGACY_FACTOR_COLS,
    OUT_GLOBS,
    PRED_GLOBS,
    compute_ic_rows,
)
from export_ic_industry_to_supabase import compute_rows as compute_industry_ic_rows  # noqa: E402
from eval_forward_ic import _f, _load, _spearman, daily_last  # noqa: E402
from sync_supabase import build_run_rows, build_signal_row  # noqa: E402

SERVING_ROOT = ROOT / "output" / "serving"
CURRENT = SERVING_ROOT / "current"
REVIEW_CONFIG = ROOT / "config" / "scoring" / "review_versions.json"
ICT = timezone(timedelta(hours=7))
MAX_FILE_BYTES = 20 * 1024 * 1024
BUY_DECISIONS = {"BUY", "STRONG BUY"}
RECENT_MONTHS = 2

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("dashboard_serving_local")


def _json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def _write(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    body = json.dumps(value, ensure_ascii=False, separators=(",", ":"), default=str).encode()
    if len(body) > MAX_FILE_BYTES:
        raise RuntimeError(f"Serving file exceeds 20 MiB: {path} ({len(body)} bytes)")
    path.write_bytes(body)


def _versions(requested: list[str] | None) -> list[str]:
    configured = _json(REVIEW_CONFIG, {}).get("versions", [])
    if not requested:
        return configured
    values = [part for raw in requested for part in raw.replace(",", " ").split()]
    unknown = sorted(set(values) - set(configured))
    if unknown:
        raise ValueError(f"Unknown review versions: {', '.join(unknown)}")
    return [version for version in configured if version in values]


def _read_jsonl(paths: Iterable[Path]) -> Iterable[dict[str, Any]]:
    for path in paths:
        with path.open(encoding="utf-8") as handle:
            for line_no, line in enumerate(handle, 1):
                if not line.strip():
                    continue
                try:
                    value = json.loads(line)
                except json.JSONDecodeError:
                    log.warning("Skipping invalid JSONL %s:%d", path, line_no)
                    continue
                if isinstance(value, dict):
                    yield value


def _recent_files(directory: Path) -> list[Path]:
    files = sorted(directory.glob("*.jsonl"))
    months = sorted({path.stem[:7] for path in files})[-RECENT_MONTHS:]
    return [path for path in files if path.stem[:7] in months]


def _recent_predictions(versions: set[str]) -> list[dict[str, Any]]:
    paths: list[Path] = []
    for directory in (
        ROOT / "output" / "history" / "v2f_predictions_v4",
        ROOT / "output" / "history" / "v2f_predictions",
        ROOT / "output" / "history" / "vnstock6" / "predictions",
    ):
        paths.extend(_recent_files(directory))
    dedup: dict[tuple[str, str], dict[str, Any]] = {}
    for row in _read_jsonl(paths):
        version = str(row.get("scoring_version") or "")
        if version not in versions:
            continue
        pred_id = str(row.get("pred_id") or "")
        key = (version, pred_id or f"{row.get('symbol')}|{row.get('signal_date')}|{row.get('snap_time')}")
        dedup[key] = row
    return list(dedup.values())


def _recent_outcomes(versions: set[str]) -> dict[tuple[str, str], dict[str, Any]]:
    paths: list[Path] = []
    for directory in (
        ROOT / "output" / "history" / "v2f_outcomes_v4",
        ROOT / "output" / "history" / "v2f_outcomes",
        ROOT / "output" / "history" / "vnstock6" / "outcomes",
    ):
        paths.extend(_recent_files(directory))
    output: dict[tuple[str, str], dict[str, Any]] = {}
    for row in _read_jsonl(paths):
        version, pred_id = str(row.get("scoring_version") or ""), str(row.get("pred_id") or "")
        if version in versions and pred_id and (row.get("lens") or "trade") == "trade":
            output[(version, pred_id)] = row
    return output


def _full_ledger(globs: list[str], versions: set[str], *, outcomes: bool = False) -> list[dict[str, Any]]:
    dedup: dict[tuple[str, str, str], dict[str, Any]] = {}
    for glob in globs:
        for row in _load(glob):
            version, pred_id = str(row.get("scoring_version") or ""), str(row.get("pred_id") or "")
            if version not in versions or not pred_id:
                continue
            lens = str(row.get("lens") or "trade") if outcomes else "prediction"
            dedup[(version, pred_id, lens)] = row
    return list(dedup.values())


def _run_key(row: dict[str, Any]) -> tuple[str, str, str]:
    return str(row.get("signal_date")), str(row.get("snap_time")), str(row.get("scoring_version"))


def _latest_runs(predictions: list[dict[str, Any]], versions: list[str]) -> tuple[dict[str, dict[str, Any]], dict[str, list[dict[str, Any]]]]:
    groups: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in predictions:
        groups[_run_key(row)].append(row)
    latest_rows: dict[str, list[dict[str, Any]]] = {}
    for version in versions:
        candidates = [(key, rows) for key, rows in groups.items() if key[2] == version]
        if candidates:
            latest_rows[version] = max(candidates, key=lambda item: item[0][:2])[1]
    runs = {
        version: build_run_rows(rows)[0]
        for version, rows in latest_rows.items()
    }
    return runs, latest_rows


def _latest_day_rows(predictions: list[dict[str, Any]], versions: list[str]) -> dict[str, list[dict[str, Any]]]:
    """Keep every intraday snapshot from the newest signal date per version."""
    newest_dates = {
        version: max(
            (str(row.get("signal_date")) for row in predictions
             if row.get("scoring_version") == version and row.get("signal_date")),
            default="",
        )
        for version in versions
    }
    return {
        version: [
            row for row in predictions
            if row.get("scoring_version") == version
            and str(row.get("signal_date")) == newest_dates[version]
        ]
        for version in versions
        if newest_dates[version]
    }


def _breakdown(row: dict[str, Any]) -> dict[str, Any]:
    return build_signal_row(row)["breakdown"]


def _today_signal(row: dict[str, Any], previous_close: float | None) -> dict[str, Any]:
    breakdown = _breakdown(row)
    price = breakdown.get("price")
    change = None
    if isinstance(price, (int, float)) and previous_close:
        change = (float(price) - previous_close) / previous_close * 100
    return {
        "symbol": row.get("symbol"), "scoring_version": row.get("scoring_version"),
        "pipeline_generation": row.get("pipeline_generation"), "market_source": row.get("market_source"),
        "signal_date": row.get("signal_date"), "decision": row.get("decision"),
        "score_trade": row.get("score_trade", row.get("total_score")),
        "snap_time": row.get("snap_time"), "price": price,
        "confidence": breakdown.get("confidence"), "ff_intra_net": breakdown.get("ff_intra_net"),
        "ff_intra_ratio": breakdown.get("ff_intra_ratio"),
        "n_aligned": breakdown.get("n_supergroups_aligned"), "ff_score": breakdown.get("ff_score"),
        "fundamental_score": breakdown.get("fundamental_score"), "entry": breakdown.get("entry"),
        "stop": breakdown.get("stop", breakdown.get("stop_loss")), "tp1": breakdown.get("tp1"),
        "previous_close": previous_close, "changePct": change, "breakdown": breakdown,
    }


def _chart_baseline(version: str, symbol: str) -> dict[str, Any]:
    local = _json(ROOT / "output" / "ohlc" / f"{symbol}.json", None)
    old = _json(CURRENT / "charts" / version / f"{symbol}.json", {})
    return {"ohlc": local if isinstance(local, list) else old.get("ohlc", []), "signals": old.get("signals", [])}


def _previous_close(version: str, symbol: str, signal_date: str) -> float | None:
    bars = _chart_baseline(version, symbol).get("ohlc", [])
    values = [row for row in bars if str(row.get("date", "")) < signal_date and row.get("close") is not None]
    try:
        return float(max(values, key=lambda row: str(row.get("date")))["close"]) if values else None
    except (TypeError, ValueError):
        return None


def _outcome_projection(outcome: dict[str, Any]) -> dict[str, Any]:
    return {key: outcome.get(key) for key in (
        "pred_id", "ret_1d", "ret_3d", "ret_5d", "ret_10d", "mfe_pct", "mae_pct", "eval_date", "n_bars", "lens"
    )}


def _history_row(row: dict[str, Any], outcome: dict[str, Any] | None, *, compact: bool = True) -> dict[str, Any]:
    signal = build_signal_row(row)
    breakdown = signal["breakdown"]
    if compact:
        breakdown = {
            key: breakdown.get(key) for key in ("pred_id", "price", "confidence") if breakdown.get(key) is not None
        }
    projection = {
        "id": row.get("pred_id"), "symbol": signal["symbol"], "decision": signal["decision"],
        "score_trade": signal["score_trade"], "regime": signal["regime"],
        "signal_date": signal["signal_date"], "snap_time": signal["snap_time"],
        "scoring_version": signal["scoring_version"], "breakdown": breakdown,
    }
    if outcome:
        projection["outcome"] = _outcome_projection(outcome)
    return projection


def _merge_history(version: str, predictions: list[dict[str, Any]], outcomes: dict[tuple[str, str], dict[str, Any]]) -> dict[str, Any]:
    old = _json(CURRENT / "history" / f"{version}.json", {"rows": []})
    merged: dict[str, dict[str, Any]] = {}
    for row in old.get("rows", []):
        pred_id = str((row.get("breakdown") or {}).get("pred_id") or row.get("id") or "")
        key = pred_id or f"{row.get('symbol')}|{row.get('signal_date')}|{row.get('snap_time')}"
        merged[key] = row
    for row in predictions:
        if row.get("scoring_version") != version:
            continue
        pred_id = str(row.get("pred_id") or "")
        merged[pred_id or "|".join(map(str, _run_key(row)))] = _history_row(row, outcomes.get((version, pred_id)))
    # A full rebuild reads every outcome partition, but deliberately preserves the
    # already-retained history signal set. This refreshes matured historical outcomes
    # without re-introducing signal rows removed by the serving retention policy.
    for row in merged.values():
        pred_id = str((row.get("breakdown") or {}).get("pred_id") or row.get("id") or "")
        outcome = outcomes.get((version, pred_id))
        if outcome:
            row["outcome"] = _outcome_projection(outcome)
    rows = sorted(merged.values(), key=lambda row: (str(row.get("signal_date")), str(row.get("snap_time"))), reverse=True)
    return {"version": version, "rows": rows, "count": len(rows)}


def _buy_snapshot(
    version: str, predictions: list[dict[str, Any]], *, recompute: bool = False,
    full_predictions: list[dict[str, Any]] | None = None,
    full_outcomes: list[dict[str, Any]] | None = None,
    industry_rows: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    old = _json(CURRENT / "buy" / f"{version}.json", {})
    buys = [row for row in predictions if row.get("scoring_version") == version and row.get("decision") in BUY_DECISIONS]
    if not buys:
        return old
    latest_key = max((_run_key(row)[:2] for row in buys))
    selected = [row for row in buys if _run_key(row)[:2] == latest_key]
    version_rows = [row for row in predictions if row.get("scoring_version") == version]
    newest_key = max((_run_key(row)[:2] for row in version_rows))
    newest_rows = [row for row in version_rows if _run_key(row)[:2] == newest_key]
    newest_run = build_run_rows(newest_rows)[0]
    run = build_run_rows(selected)[0]
    signals = []
    for row in sorted(selected, key=lambda item: float(item.get("score_trade") or item.get("total_score") or 0), reverse=True):
        signal = build_signal_row(row)
        previous = _previous_close(version, str(row.get("symbol")), str(row.get("signal_date")))
        signals.append({
            "id": row.get("pred_id"), "symbol": row.get("symbol"), "decision": row.get("decision"),
            "score_trade": signal.get("score_trade"), "signal_date": row.get("signal_date"),
            "breakdown": signal.get("breakdown"),
            "changePct": ((float(row.get("price")) - previous) / previous * 100) if previous and row.get("price") is not None else None,
        })
    expectancy = _buy_expectancy(version, full_outcomes or []) if recompute else old.get("expectancy", [])
    robustness = _buy_robustness(version, full_predictions or []) if recompute else old.get("robustness", [])
    industry_ic = old.get("industryIC", {})
    if recompute:
        industry_ic = {
            str(item["industry"]): {"ic": item.get("ic"), "n": int(item.get("n") or 0)}
            for item in (industry_rows or [])
            if item.get("version") == version and item.get("factor") == "score_trade"
            and int(item.get("horizon") or 0) == 5
        }
    return {
        "version": version,
        "latestBuy": {"run_id": run["run_id"], "signal_date": latest_key[0], "snap_time": latest_key[1]},
        "newestRun": {"run_id": newest_run["run_id"]}, "signals": signals, "runRow": {"started_at": run["started_at"]},
        "expectancy": expectancy, "robustness": robustness,
        "industryIC": industry_ic,
    }


def _average(rows: list[dict[str, Any]], key: str) -> float | None:
    values: list[float] = []
    for row in rows:
        try:
            value = row.get(key)
            if value is not None:
                values.append(float(value))
        except (TypeError, ValueError):
            continue
    return round(sum(values) / len(values), 2) if values else None


def _pearson(xs: list[float], ys: list[float]) -> float | None:
    if len(xs) < 2 or len(xs) != len(ys):
        return None
    mx, my = sum(xs) / len(xs), sum(ys) / len(ys)
    dx = sum((x - mx) ** 2 for x in xs)
    dy = sum((y - my) ** 2 for y in ys)
    if dx <= 0 or dy <= 0:
        return None
    return sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / (dx * dy) ** 0.5


def _factor_group(factor: str) -> str:
    if factor.startswith("s_"):
        return "signal"
    if factor.startswith("trade_") and factor.endswith("_norm"):
        return "factor_trade"
    if factor.startswith("hold_") and factor.endswith("_norm"):
        return "factor_hold"
    if factor.startswith("rank_"):
        return "rank"
    if factor.startswith("ff_intra_") or factor == "of_bp_pts":
        return "flow"
    return "other"


_FACTOR_EXCLUDES = {
    "price", "score_trade", "total_score", "gate_version", "registry_version",
    "schema_version", "scoring_version", "result_5d", "result_30d", "pred_id",
    "entry", "tp1", "tp2", "stop", "stop_loss",
}


def _numeric_factors(breakdown: dict[str, Any]) -> dict[str, float]:
    output: dict[str, float] = {}
    for key, value in breakdown.items():
        if key.startswith("_") or key.startswith("score_trade_") or key in _FACTOR_EXCLUDES:
            continue
        number = _f(value)
        if number is not None:
            output[key] = number
    return output


def _hit_summary(version: str, pred: dict[str, Any], outcome: dict[str, Any]) -> dict[str, Any]:
    breakdown = _breakdown(pred)
    signal_date = str(pred.get("signal_date") or "")
    try:
        start = datetime.fromisoformat(signal_date).date()
    except ValueError:
        start = None
    future = []
    for bar in _chart_baseline(version, str(pred.get("symbol"))).get("ohlc", []):
        try:
            day = datetime.fromisoformat(str(bar.get("date"))).date()
        except (TypeError, ValueError):
            continue
        if start and start < day <= start + timedelta(days=16):
            future.append((day, bar))
    future.sort(key=lambda item: item[0])
    base = _f(outcome.get("t0_close")) or _f(pred.get("price")) or _f(breakdown.get("price"))
    own_tp1 = _f(pred.get("tp1"))
    own_tp2 = _f(pred.get("tp2")) or _f(breakdown.get("tp2"))
    own_stop = _f(pred.get("stop")) or _f(pred.get("stop_loss"))

    def first_hit(kind: str, level: float | None) -> Any:
        if level is None:
            return None
        for day, bar in future:
            value = _f(bar.get(kind))
            if value is not None and ((kind == "high" and value >= level) or (kind == "low" and value <= level)):
                return day
        return None

    def days(day: Any) -> int | None:
        return (day - start).days if day is not None and start is not None else None

    up6 = first_hit("high", base * 1.06 if base else None)
    dn4 = first_hit("low", base * 0.96 if base else None)
    up3 = first_hit("high", base * 1.03 if base else None)
    dn3 = first_hit("low", base * 0.97 if base else None)
    otp1, otp2, ostop = first_hit("high", own_tp1), first_hit("high", own_tp2), first_hit("low", own_stop)
    has_outcome = bool(outcome) and outcome.get("mfe_pct") is not None and base is not None

    def outcome_label(up: Any, down: Any, tp: str = "tp") -> str | None:
        if not has_outcome:
            return None
        if up is not None and (down is None or up < down):
            return tp
        if down is not None and (up is None or down <= up):
            return "sl"
        return "open"

    own_label = None
    if has_outcome and (own_tp1 is not None or own_stop is not None):
        if otp2 is not None and (ostop is None or otp2 < ostop):
            own_label = "tp2"
        elif otp1 is not None and (ostop is None or otp1 < ostop):
            own_label = "tp1"
        elif ostop is not None:
            own_label = "sl"
        else:
            own_label = "open"
    own_day = otp1 if otp1 is not None and (ostop is None or otp1 < ostop) else ostop
    return {
        "std_outcome": outcome_label(up6, dn4),
        "std_days": days(up6 if up6 is not None and (dn4 is None or up6 < dn4) else dn4),
        "std3_outcome": outcome_label(up3, dn3),
        "own_outcome": own_label,
        "own_days": days(own_day),
    }

def _buy_expectancy(version: str, outcomes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in outcomes:
        if (row.get("scoring_version") != version or row.get("decision") not in BUY_DECISIONS
                or (row.get("lens") or "trade") != "trade" or row.get("ret_5d") is None):
            continue
        groups[(str(row.get("decision")), str(row.get("confidence") or "ALL"))].append(row)
    result = []
    for (decision, confidence), rows in sorted(groups.items()):
        wins = sum(1 for row in rows if float(row["ret_5d"]) > 0)
        result.append({
            "decision": decision, "confidence": confidence, "n": len(rows),
            "avg_ret_1d": _average(rows, "ret_1d"), "avg_ret_5d": _average(rows, "ret_5d"),
            "avg_ret_10d": _average(rows, "ret_10d"), "avg_mfe": _average(rows, "mfe_pct"),
            "avg_mae": _average(rows, "mae_pct"), "winrate_5d": round(100 * wins / len(rows), 1),
            "scoring_version": version,
        })
    return result


def _buy_robustness(version: str, predictions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    source = [row for row in predictions if row.get("scoring_version") == version and row.get("signal_date")]
    buys = [row for row in source if row.get("decision") in BUY_DECISIONS]
    if not buys:
        return []
    latest_date, latest_snap = max((str(row.get("signal_date")), str(row.get("snap_time"))) for row in buys)
    latest_symbols = {
        str(row.get("symbol")) for row in buys
        if str(row.get("signal_date")) == latest_date and str(row.get("snap_time")) == latest_snap
    }
    cutoff = (datetime.fromisoformat(latest_date) - timedelta(days=21)).date().isoformat()
    window = [row for row in source if cutoff < str(row.get("signal_date")) <= latest_date]
    total_days = len({str(row.get("signal_date")) for row in window})
    today = [row for row in source if str(row.get("signal_date")) == latest_date]
    total_snaps = len({str(row.get("snap_time")) for row in today})
    result = []
    for symbol in sorted(latest_symbols):
        symbol_buys = [row for row in window if str(row.get("symbol")) == symbol and row.get("decision") in BUY_DECISIONS]
        today_buys = [row for row in symbol_buys if str(row.get("signal_date")) == latest_date]
        snaps = sorted(str(row.get("snap_time")) for row in today_buys if row.get("snap_time"))
        result.append({
            "symbol": symbol, "signal_date": latest_date, "total_days_15d": total_days,
            "total_snaps_today": total_snaps,
            "buy_days_15d": len({str(row.get("signal_date")) for row in symbol_buys}),
            "buy_snaps_today": len(today_buys), "first_buy_snap_vn": snaps[0][:5] if snaps else None,
            "scoring_version": version,
        })
    return result

def _analysis_diagnostics(rows: list[tuple[dict[str, Any], dict[str, float]]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    factors: dict[str, list[tuple[float, float, float | None, str | None, str | None]]] = defaultdict(list)
    per_pred: list[dict[str, float]] = []
    for result, values in rows:
        ret5 = _f(result.get("ret_5d"))
        if ret5 is None:
            continue
        status = result.get("std_outcome")
        win = 1.0 if status == "tp" else (0.0 if status in {"sl", "open"} else None)
        confidence = str(result.get("confidence")) if result.get("confidence") is not None else None
        regime = str(result.get("regime")) if result.get("regime") is not None else None
        per_pred.append(values)
        for factor, value in values.items():
            factors[factor].append((value, ret5, win, confidence, regime))

    corr: list[dict[str, Any]] = []
    accepted: set[str] = set()
    for factor, samples in sorted(factors.items()):
        if len(samples) < 30:
            continue
        corr_ret = _pearson([x[0] for x in samples], [x[1] for x in samples])
        if corr_ret is None:
            continue
        win_samples = [x for x in samples if x[2] is not None]
        corr_win = _pearson([x[0] for x in win_samples], [float(x[2]) for x in win_samples])
        accepted.add(factor)
        corr.append({"factor": factor, "grp": _factor_group(factor), "n": len(samples),
                     "corr_ret5": round(corr_ret, 3),
                     "corr_win": None if corr_win is None else round(corr_win, 3)})

    pair_values: dict[tuple[str, str], tuple[list[float], list[float]]] = defaultdict(lambda: ([], []))
    for values in per_pred:
        keys = sorted(set(values) & accepted)
        for fa, fb in combinations(keys, 2):
            pair_values[(fa, fb)][0].append(values[fa])
            pair_values[(fa, fb)][1].append(values[fb])
    pairs = []
    for (fa, fb), (xs, ys) in sorted(pair_values.items()):
        value = _pearson(xs, ys)
        if len(xs) >= 30 and value is not None:
            pairs.append({"fa": fa, "fb": fb, "n": len(xs), "corr": round(value, 3)})

    split: list[dict[str, Any]] = []
    for factor, samples in sorted(factors.items()):
        for dim, index in (("confidence", 3), ("regime", 4)):
            buckets: dict[str, list[tuple[float, float, float | None]]] = defaultdict(list)
            for sample in samples:
                if sample[index] is not None:
                    buckets[str(sample[index])].append((sample[0], sample[1], sample[2]))
            for bucket, values in sorted(buckets.items()):
                corr_ret = _pearson([x[0] for x in values], [x[1] for x in values])
                if len(values) < 20 or corr_ret is None:
                    continue
                win_values = [x for x in values if x[2] is not None]
                corr_win = _pearson([x[0] for x in win_values], [float(x[2]) for x in win_values])
                split.append({"dim": dim, "bucket": bucket, "factor": factor,
                              "grp": _factor_group(factor), "n": len(values),
                              "corr_ret5": round(corr_ret, 3),
                              "corr_win": None if corr_win is None else round(corr_win, 3)})
    return corr, pairs, split


def _pooled_ic(preds: list[dict[str, Any]], outs: list[dict[str, Any]], *, indicators: bool) -> list[dict[str, Any]]:
    ret_by_pid = {str(row.get("pred_id")): row for row in outs if row.get("pred_id")}
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in preds:
        if row.get("shadow_forward_eligible") is not False:
            grouped[str(row.get("scoring_version"))].append(row)
    source = [row for version_rows in grouped.values() for row in daily_last(version_rows)]
    versions = [None] if indicators else sorted({str(row.get("scoring_version")) for row in source})
    rows: list[dict[str, Any]] = []
    if indicators:
        from analyze_marginal_ic import INDICATORS  # noqa: PLC0415
        columns = {name: name for name in INDICATORS}
    for version in versions:
        selected = source if version is None else [row for row in source if str(row.get("scoring_version")) == version]
        if not indicators:
            columns = LEGACY_FACTOR_COLS if version == "v2.3" else FACTOR_COLS
        for factor, column in columns.items():
            for horizon in HORIZONS:
                xs, ys = [], []
                for pred in selected:
                    outcome = ret_by_pid.get(str(pred.get("pred_id")))
                    value = _f(pred.get(column))
                    ret = _f((outcome or {}).get(f"ret_{horizon}d"))
                    if value is not None and ret is not None:
                        xs.append(value)
                        ys.append(ret)
                ic = _spearman(xs, ys)
                if ic is None:
                    continue
                row = {"factor" if not indicators else "indicator": factor, "horizon": horizon,
                       "ic": round(ic, 3), "n": len(xs)}
                if not indicators:
                    row["version"] = version
                rows.append(row)
    return rows


def _marginal_ic(preds: list[dict[str, Any]], outs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    from analyze_marginal_ic import HORIZONS as MARGINAL_HORIZONS, analyze_version  # noqa: PLC0415
    ret_by_pid = {row.get("pred_id"): row for row in outs if row.get("pred_id")}
    by_version: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in preds:
        if row.get("shadow_forward_eligible") is not False:
            by_version[str(row.get("scoring_version"))].append(row)
    output = []
    for version, version_preds in sorted(by_version.items()):
        selected = daily_last(version_preds)
        for horizon in MARGINAL_HORIZONS:
            for row in analyze_version(selected, ret_by_pid, horizon) or []:
                output.append({"version": version, **row})
    return output


def _merge_analysis(version: str, predictions: list[dict[str, Any]], outcomes: dict[tuple[str, str], dict[str, Any]],
                    *, recompute: bool = False, generated_at: str | None = None) -> dict[str, Any]:
    old = _json(CURRENT / "analysis" / f"{version}.json", {})
    results = {str(row.get("pred_id")): row for row in old.get("results", []) if row.get("pred_id")}
    latest_buy: dict[tuple[str, str], dict[str, Any]] = {}
    diagnostic_rows: list[tuple[dict[str, Any], dict[str, float]]] = []
    for row in predictions:
        if row.get("scoring_version") != version or row.get("decision") not in BUY_DECISIONS:
            continue
        key = (str(row.get("symbol")), str(row.get("signal_date")))
        if key not in latest_buy or str(row.get("snap_time")) > str(latest_buy[key].get("snap_time")):
            latest_buy[key] = row
    for pred in latest_buy.values():
        pred_id = str(pred.get("pred_id") or "")
        outcome = outcomes.get((version, pred_id), {})
        breakdown = _breakdown(pred)
        existing = results.get(pred_id, {})
        hit = (_hit_summary(version, pred, outcome) if recompute else
               {key: existing.get(key) for key in ("std_outcome", "std_days", "std3_outcome", "own_outcome", "own_days")})
        result = {
            "pred_id": pred_id, "scoring_version": version, "symbol": pred.get("symbol"),
            "signal_date": pred.get("signal_date"), "snap_time": pred.get("snap_time"),
            "decision": pred.get("decision"), "score_trade": pred.get("score_trade", pred.get("total_score")),
            "confidence": outcome.get("confidence", pred.get("confidence", breakdown.get("confidence"))),
            "t0_close": outcome.get("t0_close", pred.get("price")),
            **{key: outcome.get(key) for key in ("ret_1d", "ret_3d", "ret_5d", "ret_10d", "mfe_pct", "mae_pct")},
            "own_entry": pred.get("entry"), "own_tp1": pred.get("tp1"), "own_tp2": pred.get("tp2"),
            "own_stop": pred.get("stop", pred.get("stop_loss")),
            "regime": pred.get("regime", breakdown.get("regime")),
            **hit,
        }
        results[pred_id] = result
        if recompute:
            diagnostic_rows.append((result, _numeric_factors(breakdown)))
    ordered = sorted(results.values(), key=lambda row: str(row.get("symbol")))
    ordered.sort(key=lambda row: str(row.get("signal_date")), reverse=True)
    ordered = ordered[:2000]
    corr, pairs, split = (_analysis_diagnostics(diagnostic_rows) if recompute
                          else (old.get("corr", []), old.get("pairs", []), old.get("split", [])))
    return {"version": version, "results": ordered, "corr": corr, "pairs": pairs, "split": split,
            "analytics_generated_at": generated_at if recompute else old.get("analytics_generated_at")}


def _refresh_ic(staging: Path, release_id: str, generated_at: str,
                preds: list[dict[str, Any]], outs: list[dict[str, Any]],
                industry: list[dict[str, Any]]) -> None:
    old = _json(CURRENT / "ic.json", {"schema_version": 1, "indicators": [], "factor_versions": [], "marginal": [], "industry": [], "industry_errors": {}})
    metrics = compute_ic_rows(preds, outs)
    for row in metrics:
        row["computed_at"] = generated_at
    old.update({"release_id": release_id, "generated_at": generated_at, "published_at": generated_at,
                "source": "github", "metrics": metrics,
                "indicators": _pooled_ic(preds, outs, indicators=True),
                "factor_versions": _pooled_ic(preds, outs, indicators=False),
                "marginal": _marginal_ic(preds, outs),
                "industry": industry, "industry_errors": {},
                "section_freshness": {name: {"generated_at": generated_at, "source": "git-ledger"}
                                      for name in ("metrics", "indicators", "factor_versions", "marginal", "industry")}})
    _write(staging / "ic.json", old)


def build(versions: list[str], full: bool, dry_run: bool) -> Path:
    if not CURRENT.exists():
        raise RuntimeError("Missing bootstrap output/serving/current release")
    now = datetime.now(timezone.utc)
    release_id, generated_at = now.strftime("%Y%m%dT%H%M%SZ"), now.isoformat()
    staging = SERVING_ROOT / f".staging-{release_id}"
    if staging.exists():
        shutil.rmtree(staging)
    shutil.copytree(CURRENT, staging)

    predictions = _recent_predictions(set(versions))
    outcomes = _recent_outcomes(set(versions))
    runs, latest = _latest_runs(predictions, versions)
    latest_day = _latest_day_rows(predictions, versions)
    if not runs:
        raise RuntimeError("No local review-version run found")

    old_meta = _json(CURRENT / "metadata.json", {})
    merged_runs = {**old_meta.get("runs", {}), **runs}
    coverage: dict[str, dict[str, str]] = {}
    full_predictions: list[dict[str, Any]] = []
    full_outcomes: list[dict[str, Any]] = []
    industry_rows: list[dict[str, Any]] = []
    if full:
        full_predictions = _full_ledger(PRED_GLOBS, set(versions))
        full_outcomes = _full_ledger(OUT_GLOBS, set(versions), outcomes=True)
        industry_rows, _ = compute_industry_ic_rows(full_predictions, full_outcomes, release_id)
    full_outcome_map = {
        (str(row.get("scoring_version")), str(row.get("pred_id"))): row for row in full_outcomes
    }

    for version in versions:
        history = _merge_history(version, predictions, full_outcome_map if full else outcomes)
        dates = [str(row.get("signal_date")) for row in history["rows"] if row.get("signal_date")]
        if dates:
            coverage[version] = {"min": min(dates), "max": max(dates)}
        _write(staging / "history" / f"{version}.json", history)
        buy = _buy_snapshot(version, predictions, recompute=full,
                            full_predictions=full_predictions, full_outcomes=full_outcomes,
                            industry_rows=industry_rows)
        _write(staging / "buy" / f"{version}.json", buy)
        analysis_predictions = full_predictions if full else predictions
        analysis_outcomes = full_outcome_map if full else outcomes
        _write(staging / "analysis" / f"{version}.json", _merge_analysis(
            version, analysis_predictions, analysis_outcomes, recompute=full, generated_at=generated_at))

        if version not in latest:
            continue
        run = runs[version]
        signal_date = max(str(row.get("signal_date")) for row in latest[version])
        projected = [
            _today_signal(row, _previous_close(version, str(row.get("symbol")), str(row.get("signal_date"))))
            for row in sorted(latest_day[version], key=lambda item: (
                str(item.get("snap_time")), float(item.get("score_trade") or item.get("total_score") or 0)
            ))
        ]
        status = _json(CURRENT / "today" / f"{version}.json", {}).get("status", {})
        _write(staging / "today" / f"{version}.json", {
            "version": version, "signal_date": signal_date, "run": run, "signals": projected,
            "status": status, "source_provenance": "git-ledger",
        })

    metadata = {
        "schema_version": 2, "release_id": release_id, "generated_at": generated_at,
        "source_provenance": "git-ledger", "runs": merged_runs, "coverage": coverage,
    }
    _write(staging / "metadata.json", metadata)

    for version in versions:
        history = _json(staging / "history" / f"{version}.json", {"rows": []})
        by_symbol: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for row in reversed(history.get("rows", [])):
            breakdown = row.get("breakdown") or {}
            by_symbol[str(row.get("symbol"))].append({
                "signal_date": row.get("signal_date"), "snap_time": row.get("snap_time"),
                "decision": row.get("decision"), "price": breakdown.get("price"),
            })
        for symbol, signal_rows in by_symbol.items():
            chart = _chart_baseline(version, symbol)
            chart["signals"] = signal_rows
            _write(staging / "charts" / version / f"{symbol}.json", chart)

    if full:
        _refresh_ic(staging, release_id, generated_at, full_predictions, full_outcomes, industry_rows)
    else:
        ic = _json(staging / "ic.json", {})
        if ic:
            ic.update({"release_id": release_id, "published_at": generated_at, "source": "github"})
            _write(staging / "ic.json", ic)

    datasets: list[dict[str, Any]] = []
    for path in sorted(staging.rglob("*.json")):
        if path.name == "manifest.json":
            continue
        body = path.read_bytes()
        if len(body) > MAX_FILE_BYTES:
            raise RuntimeError(f"Serving file exceeds 20 MiB: {path}")
        datasets.append({
            "path": path.relative_to(staging).as_posix(), "bytes": len(body),
            "sha256": hashlib.sha256(body).hexdigest(),
        })
    paths = [item["path"] for item in datasets]
    if len(paths) != len(set(paths)) or any(Path(path).is_absolute() for path in paths):
        raise RuntimeError("Manifest dataset paths must be unique and relative")
    counts = {version: len(latest.get(version, [])) for version in versions}
    today_counts = {version: len(latest_day.get(version, [])) for version in versions}
    missing = [version for version, count in counts.items() if version in runs and count == 0]
    if missing:
        raise RuntimeError(f"Empty latest run for: {', '.join(missing)}")
    manifest = {
        "schema_version": 2, "release_id": release_id, "generated_at_utc": generated_at,
        "asof_ict": now.astimezone(ICT).isoformat(), "source_provenance": "git-ledger",
        "quality": {"status": "PASS", "checks": [
            "local_ledger_only", "non_empty_runs", "complete_latest_day", "deduplicated_pred_id", "json_serializable",
            "sha256", "max_file_20_mib", "relative_unique_paths",
        ], "latest_signal_counts": counts, "today_signal_counts": today_counts},
        "datasets": datasets,
    }
    _write(staging / "manifest.json", manifest)
    log.info("Built local release %s (%s)", release_id, "full" if full else "intraday")
    if dry_run:
        return staging
    if CURRENT.exists():
        shutil.rmtree(CURRENT)
    staging.rename(CURRENT)
    previous = SERVING_ROOT / "previous"
    if previous.exists():
        shutil.rmtree(previous)
    _write(SERVING_ROOT / "latest.json", {"schema_version": 2, "release_id": release_id, "path": "current/manifest.json"})
    return CURRENT


def main() -> int:
    parser = argparse.ArgumentParser(description="Build GitHub serving data from local ledgers")
    parser.add_argument("--versions", nargs="*")
    parser.add_argument("--full", action="store_true", help="Recompute ledger-derived IC metrics")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    try:
        build(_versions(args.versions), args.full, args.dry_run)
        return 0
    except Exception as exc:  # noqa: BLE001
        log.error("Local serving build failed: %s", exc)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
