#!/usr/bin/env python3
"""Read-only parity check for the latest GitHub serving runs and Supabase mirror."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from build_dashboard_serving import SupabaseReader

ROOT = Path(__file__).resolve().parent.parent
CURRENT = ROOT / "output" / "serving" / "current"
REVIEW_CONFIG = ROOT / "config" / "scoring" / "review_versions.json"
ICT = timezone(timedelta(hours=7))


def _json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _minute(value: Any) -> str:
    text = str(value or "")
    if not text:
        return ""
    if len(text) == 5 and text[2] == ":":
        return text
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        if parsed.tzinfo is not None:
            parsed = parsed.astimezone(ICT)
        return parsed.strftime("%H:%M")
    except ValueError:
        return text[:5]


def _normalize(value: Any) -> Any:
    if isinstance(value, bool) or value is None or isinstance(value, str):
        return value
    if isinstance(value, (int, float)):
        number = float(value)
        return round(number, 12) if math.isfinite(number) else str(number)
    if isinstance(value, dict):
        return {str(key): _normalize(item) for key, item in sorted(value.items())}
    if isinstance(value, list):
        return [_normalize(item) for item in value]
    return str(value)


def _digest(value: Any) -> str:
    body = json.dumps(_normalize(value), ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def _signal(row: dict[str, Any], run_id: str) -> dict[str, Any]:
    breakdown = row.get("breakdown") or {}
    return _normalize({
        "run_id": run_id,
        "pred_id": breakdown.get("pred_id") or row.get("id"),
        "symbol": row.get("symbol"),
        "decision": row.get("decision"),
        "score_trade": row.get("score_trade"),
        "signal_date": row.get("signal_date"),
        "snap_time": _minute(row.get("snap_time")),
        "scoring_version": row.get("scoring_version"),
        "breakdown": breakdown,
    })


def _run(row: dict[str, Any]) -> dict[str, Any]:
    return _normalize({
        "run_id": row.get("run_id"),
        "kind": row.get("kind"),
        "started_at": f"{str(row.get('started_at') or '')[:10]}T{_minute(row.get('started_at'))}",
        "scoring_version": row.get("scoring_version"),
        "gate_version": None if row.get("gate_version") is None else str(row.get("gate_version")),
        "universe_size": row.get("universe_size"),
        "n_buy": row.get("n_buy"),
        "health": row.get("health") or {},
    })


def verify_history(reader: SupabaseReader, versions: list[str]) -> list[str]:
    failures: list[str] = []
    outcome_fields = (
        "pred_id", "ret_1d", "ret_3d", "ret_5d", "ret_10d", "mfe_pct", "mae_pct", "eval_date", "n_bars", "lens"
    )
    for version in versions:
        history = _json(CURRENT / "history" / f"{version}.json")
        expected_signal_ids = {
            str((row.get("breakdown") or {}).get("pred_id") or row.get("id") or "")
            for row in history.get("rows", [])
        }
        expected_signal_ids.discard("")
        actual_signals = reader.rows(
            "v4_signals", select="pred_id:breakdown->>pred_id",
            filters={"scoring_version": f"eq.{version}"},
        )
        actual_signal_ids = {str(row.get("pred_id") or "") for row in actual_signals}
        actual_signal_ids.discard("")
        if expected_signal_ids != actual_signal_ids:
            missing = sorted(expected_signal_ids - actual_signal_ids)
            extra = sorted(actual_signal_ids - expected_signal_ids)
            failures.append(
                f"{version}: history signal ids differ github={len(expected_signal_ids)} "
                f"supabase={len(actual_signal_ids)} missing={missing[:3]} extra={extra[:3]}"
            )

        expected_outcomes = {
            str(row["outcome"].get("pred_id")): _normalize(row["outcome"])
            for row in history.get("rows", []) if row.get("outcome") and row["outcome"].get("pred_id")
        }
        actual_outcome_rows = reader.rows(
            "v4_outcomes", select=",".join(outcome_fields),
            filters={"scoring_version": f"eq.{version}"},
        )
        actual_outcomes = {
            str(row.get("pred_id")): _normalize({key: row.get(key) for key in outcome_fields})
            for row in actual_outcome_rows if row.get("pred_id")
        }
        if expected_outcomes != actual_outcomes:
            missing = sorted(set(expected_outcomes) - set(actual_outcomes))
            extra = sorted(set(actual_outcomes) - set(expected_outcomes))
            changed = sorted(
                pred_id for pred_id in set(expected_outcomes) & set(actual_outcomes)
                if expected_outcomes[pred_id] != actual_outcomes[pred_id]
            )
            failures.append(
                f"{version}: history outcomes differ github={len(expected_outcomes)} "
                f"supabase={len(actual_outcomes)} missing={missing[:3]} extra={extra[:3]} changed={changed[:3]}"
            )
        if expected_signal_ids == actual_signal_ids and expected_outcomes == actual_outcomes:
            print(
                f"PASS history {version}: signals={len(expected_signal_ids)} outcomes={len(expected_outcomes)} "
                f"signal_sha256={_digest(sorted(expected_signal_ids))[:12]} "
                f"outcome_sha256={_digest(expected_outcomes)[:12]}"
            )
    return failures


def verify(reader: SupabaseReader, versions: list[str]) -> list[str]:
    metadata = _json(CURRENT / "metadata.json")
    failures: list[str] = []
    for version in versions:
        expected_run = (metadata.get("runs") or {}).get(version)
        if not expected_run:
            failures.append(f"{version}: missing GitHub run metadata")
            continue
        run_id = str(expected_run.get("run_id") or "")
        actual_runs = reader.rows("v4_runs", filters={"run_id": f"eq.{run_id}"}, limit=2)
        if len(actual_runs) != 1:
            failures.append(f"{version}: Supabase run count={len(actual_runs)} for {run_id}")
            continue
        if _run(expected_run) != _run(actual_runs[0]):
            failures.append(
                f"{version}: run metadata differs github={_digest(_run(expected_run))[:12]} "
                f"supabase={_digest(_run(actual_runs[0]))[:12]}"
            )

        today = _json(CURRENT / "today" / f"{version}.json")
        target_date, target_time = run_id[:10], run_id[11:16]
        expected_rows = [
            _signal(row, run_id) for row in today.get("signals", [])
            if str(row.get("signal_date")) == target_date and _minute(row.get("snap_time")) == target_time
        ]
        actual_raw = reader.rows("v4_signals", filters={"run_id": f"eq.{run_id}"}, order="symbol.asc")
        actual_rows = [_signal(row, run_id) for row in actual_raw]
        expected_by_id = {str(row.get("pred_id")): row for row in expected_rows}
        actual_by_id = {str(row.get("pred_id")): row for row in actual_rows}
        missing = sorted(set(expected_by_id) - set(actual_by_id))
        extra = sorted(set(actual_by_id) - set(expected_by_id))
        changed = sorted(
            pred_id for pred_id in set(expected_by_id) & set(actual_by_id)
            if expected_by_id[pred_id] != actual_by_id[pred_id]
        )
        if missing or extra or changed or len(expected_rows) != int(expected_run.get("universe_size") or 0):
            failures.append(
                f"{version}: signals differ expected={len(expected_rows)} actual={len(actual_rows)} "
                f"missing={missing[:3]} extra={extra[:3]} changed={changed[:3]}"
            )
        else:
            print(
                f"PASS {version}: run={run_id} signals={len(expected_rows)} "
                f"sha256={_digest(sorted(expected_rows, key=lambda row: str(row.get('pred_id'))))[:16]}"
            )
    return failures


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--versions", nargs="*")
    parser.add_argument("--history", action="store_true", help="also compare retained history signals and outcomes")
    args = parser.parse_args()
    url = os.environ.get("SUPABASE_URL", "").strip()
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "").strip()
    if not url or not key:
        print("SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY are required", file=sys.stderr)
        return 2
    configured = _json(REVIEW_CONFIG).get("versions", [])
    versions = args.versions or configured
    reader = SupabaseReader(url, key)
    failures = verify(reader, versions)
    if args.history:
        failures.extend(verify_history(reader, versions))
    if failures:
        print("PARITY FAILED", file=sys.stderr)
        for failure in failures:
            print(f"- {failure}", file=sys.stderr)
        return 1
    print(f"PARITY PASS: {len(versions)} version(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())