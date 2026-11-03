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
from pathlib import Path
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from export_ic_to_supabase import (  # noqa: E402
    OUT_GLOBS,
    PRED_GLOBS,
    compute_ic_rows,
)
from export_ic_industry_to_supabase import compute_rows as compute_industry_ic_rows  # noqa: E402
from eval_forward_ic import _load  # noqa: E402
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


def _write(path: Path, value: Any) -> dict[str, Any]:
    path.parent.mkdir(parents=True, exist_ok=True)
    body = json.dumps(value, ensure_ascii=False, separators=(",", ":"), default=str).encode()
    if len(body) > MAX_FILE_BYTES:
        raise RuntimeError(f"Serving file exceeds 20 MiB: {path} ({len(body)} bytes)")
    path.write_bytes(body)
    return {"path": path.as_posix(), "bytes": len(body), "sha256": hashlib.sha256(body).hexdigest()}


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
    for name in ("v2f_predictions_v4", "v2f_predictions"):
        paths.extend(_recent_files(ROOT / "output" / "history" / name))
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
    for name in ("v2f_outcomes_v4", "v2f_outcomes"):
        paths.extend(_recent_files(ROOT / "output" / "history" / name))
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
        projection["outcome"] = {key: outcome.get(key) for key in (
            "pred_id", "ret_1d", "ret_3d", "ret_5d", "ret_10d", "mfe_pct", "mae_pct", "eval_date", "n_bars", "lens"
        )}
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


def _merge_analysis(version: str, predictions: list[dict[str, Any]], outcomes: dict[tuple[str, str], dict[str, Any]]) -> dict[str, Any]:
    old = _json(CURRENT / "analysis" / f"{version}.json", {})
    results = {str(row.get("pred_id")): row for row in old.get("results", []) if row.get("pred_id")}
    latest_buy: dict[tuple[str, str], dict[str, Any]] = {}
    for row in predictions:
        if row.get("scoring_version") != version or row.get("decision") not in BUY_DECISIONS:
            continue
        key = (str(row.get("symbol")), str(row.get("signal_date")))
        if key not in latest_buy or str(row.get("snap_time")) > str(latest_buy[key].get("snap_time")):
            latest_buy[key] = row
    for pred in latest_buy.values():
        pred_id = str(pred.get("pred_id") or "")
        outcome = outcomes.get((version, pred_id), {})
        results[pred_id] = {
            "pred_id": pred_id, "scoring_version": version, "symbol": pred.get("symbol"),
            "signal_date": pred.get("signal_date"), "snap_time": pred.get("snap_time"),
            "decision": pred.get("decision"), "score_trade": pred.get("score_trade", pred.get("total_score")),
            "confidence": outcome.get("confidence", pred.get("confidence")),
            "t0_close": outcome.get("t0_close", pred.get("price")),
            **{key: outcome.get(key) for key in ("ret_1d", "ret_3d", "ret_5d", "ret_10d", "mfe_pct", "mae_pct")},
            "own_entry": pred.get("entry"), "own_tp1": pred.get("tp1"), "own_tp2": pred.get("tp2"),
            "own_stop": pred.get("stop", pred.get("stop_loss")),
            "std_outcome": None, "std_days": None, "std3_outcome": None,
            "own_outcome": None, "own_days": None,
        }
    ordered = sorted(results.values(), key=lambda row: (str(row.get("signal_date")), str(row.get("symbol"))), reverse=True)[:2000]
    return {"version": version, "results": ordered, "corr": old.get("corr", []), "pairs": old.get("pairs", []), "split": old.get("split", [])}


def _refresh_ic(staging: Path, release_id: str, generated_at: str,
                preds: list[dict[str, Any]], outs: list[dict[str, Any]],
                industry: list[dict[str, Any]]) -> None:
    old = _json(CURRENT / "ic.json", {"schema_version": 1, "indicators": [], "factor_versions": [], "marginal": [], "industry": [], "industry_errors": {}})
    metrics = compute_ic_rows(preds, outs)
    for row in metrics:
        row["computed_at"] = generated_at
    old.update({"release_id": release_id, "generated_at": generated_at, "source": "github",
                "metrics": metrics, "industry": industry, "industry_errors": {}})
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
    if not runs:
        raise RuntimeError("No local review-version run found")

    old_meta = _json(CURRENT / "metadata.json", {})
    merged_runs = {**old_meta.get("runs", {}), **runs}
    coverage: dict[str, dict[str, str]] = {}
    datasets: list[dict[str, Any]] = []
    full_predictions: list[dict[str, Any]] = []
    full_outcomes: list[dict[str, Any]] = []
    industry_rows: list[dict[str, Any]] = []
    if full:
        full_predictions = _full_ledger(PRED_GLOBS, set(versions))
        full_outcomes = _full_ledger(OUT_GLOBS, set(versions), outcomes=True)
        industry_rows, _ = compute_industry_ic_rows(full_predictions, full_outcomes, release_id)

    for version in versions:
        history = _merge_history(version, predictions, outcomes)
        dates = [str(row.get("signal_date")) for row in history["rows"] if row.get("signal_date")]
        if dates:
            coverage[version] = {"min": min(dates), "max": max(dates)}
        datasets.append(_write(staging / "history" / f"{version}.json", history))
        buy = _buy_snapshot(version, predictions, recompute=full,
                            full_predictions=full_predictions, full_outcomes=full_outcomes,
                            industry_rows=industry_rows)
        datasets.append(_write(staging / "buy" / f"{version}.json", buy))
        datasets.append(_write(staging / "analysis" / f"{version}.json", _merge_analysis(version, predictions, outcomes)))

        if version not in latest:
            continue
        run = runs[version]
        signal_date = str(run["run_id"]).split("_")[0]
        projected = [
            _today_signal(row, _previous_close(version, str(row.get("symbol")), signal_date))
            for row in sorted(latest[version], key=lambda item: float(item.get("score_trade") or item.get("total_score") or 0), reverse=True)
        ]
        status = _json(CURRENT / "today" / f"{version}.json", {}).get("status", {})
        datasets.append(_write(staging / "today" / f"{version}.json", {
            "version": version, "signal_date": signal_date, "run": run, "signals": projected,
            "status": status, "source_provenance": "git-ledger",
        }))

    metadata = {
        "schema_version": 2, "release_id": release_id, "generated_at": generated_at,
        "source_provenance": "git-ledger", "runs": merged_runs, "coverage": coverage,
    }
    datasets.append(_write(staging / "metadata.json", metadata))

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
            datasets.append(_write(staging / "charts" / version / f"{symbol}.json", chart))

    if full:
        _refresh_ic(staging, release_id, generated_at, full_predictions, full_outcomes, industry_rows)
    else:
        ic = _json(staging / "ic.json", {})
        if ic:
            ic.update({"release_id": release_id, "generated_at": generated_at, "source": "github"})
            _write(staging / "ic.json", ic)

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
    unique = {item["path"]: item for item in datasets}
    counts = {version: len(latest.get(version, [])) for version in versions}
    missing = [version for version, count in counts.items() if version in runs and count == 0]
    if missing:
        raise RuntimeError(f"Empty latest run for: {', '.join(missing)}")
    manifest = {
        "schema_version": 2, "release_id": release_id, "generated_at_utc": generated_at,
        "asof_ict": now.astimezone(ICT).isoformat(), "source_provenance": "git-ledger",
        "quality": {"status": "PASS", "checks": [
            "local_ledger_only", "non_empty_runs", "deduplicated_pred_id", "json_serializable",
            "sha256", "max_file_20_mib",
        ], "latest_signal_counts": counts},
        "datasets": list(unique.values()),
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
