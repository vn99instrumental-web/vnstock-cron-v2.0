#!/usr/bin/env python3
"""Backfill serving-only v4.19 shadow rows from historical v4.18 ledger.

The backfill keeps, per day, the final snapshot and the final snapshot that has
at least one v4.19 BUY. It never copies entry/stop/target levels and is marked
ineligible for outcome/IC evaluation so retrospective rows cannot contaminate
the forward shadow evidence.
"""
from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path
from typing import Iterable

try:
    from materialize_shadow_scoring import CONFIG_PATH, SHADOW_VERSION, materialize_shadow_row
except ModuleNotFoundError:
    from scripts.materialize_shadow_scoring import CONFIG_PATH, SHADOW_VERSION, materialize_shadow_row

ROOT = Path(__file__).resolve().parent.parent
LEDGER_DIR = ROOT / "output" / "history" / "v2f_predictions_v4"
BUY_DECISIONS = {"BUY", "STRONG BUY"}
ENTRY_FIELDS = (
    "entry", "entry_low", "entry_high", "stop", "stop_loss", "tp1", "tp2",
    "risk_pct", "rr_tp1", "rr_headroom", "size_hint", "nearest_support",
    "nearest_resist", "levels_used", "flags", "skip",
)


def _read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _pred_id(row: dict) -> str:
    return f"{row['symbol']}_{row['signal_date']}_{row['snap_time']}_v2fv4_{SHADOW_VERSION}"


def select_backfill_rows(parent_rows: Iterable[dict], before_date: str) -> list[dict]:
    snapshots: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for parent in parent_rows:
        if parent.get("scoring_version") != "v4.18" or not parent.get("signal_date") or parent["signal_date"] >= before_date:
            continue
        shadow = materialize_shadow_row(parent)
        shadow["pred_id"] = _pred_id(shadow)
        shadow["shadow_data_origin"] = "retrospective_backfill"
        shadow["shadow_forward_eligible"] = False
        shadow["shadow_backfill_source_pred_id"] = parent.get("pred_id")
        for field in ENTRY_FIELDS:
            shadow.pop(field, None)
        snapshots[(shadow["signal_date"], shadow.get("snap_time") or "")].append(shadow)

    by_day: dict[str, list[tuple[str, list[dict]]]] = defaultdict(list)
    for (signal_date, snap_time), rows in snapshots.items():
        by_day[signal_date].append((snap_time, rows))

    selected: list[dict] = []
    for signal_date in sorted(by_day):
        day_snapshots = sorted(by_day[signal_date], key=lambda item: item[0])
        keep_times = {day_snapshots[-1][0]}
        buy_snapshots = [item for item in day_snapshots if any(row.get("decision") in BUY_DECISIONS for row in item[1])]
        if buy_snapshots:
            keep_times.add(buy_snapshots[-1][0])
        for snap_time, rows in day_snapshots:
            if snap_time in keep_times:
                selected.extend(rows)
    return selected


def main() -> int:
    parser = argparse.ArgumentParser(description="Backfill v4.19 serving rows from v4.18 ledger")
    parser.add_argument("--before-date", help="exclusive YYYY-MM-DD cutoff; default config forward_start")
    parser.add_argument("--write", action="store_true", help="rewrite ledger and append backfill rows")
    args = parser.parse_args()

    config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    before_date = args.before_date or config["weight_method"]["forward_start"]
    paths = sorted(LEDGER_DIR.glob("*.jsonl"))
    all_rows = [row for path in paths for row in _read_jsonl(path)]
    backfill = select_backfill_rows(all_rows, before_date)
    stale_equal = [row for row in all_rows if row.get("scoring_version") == SHADOW_VERSION and row.get("shadow_method") == "equal_weight_core"]
    print(f"before_date={before_date} backfill_rows={len(backfill)} stale_equal_rows={len(stale_equal)}")
    print(f"days={len({row['signal_date'] for row in backfill})} snapshots={len({(row['signal_date'], row['snap_time']) for row in backfill})}")
    if not args.write:
        print("dry-run: use --write to update ledger")
        return 0

    backfill_by_month: dict[str, list[dict]] = defaultdict(list)
    for row in backfill:
        backfill_by_month[row["signal_date"][:7]].append(row)

    for path in paths:
        month = path.stem
        raw = path.read_text(encoding="utf-8")
        newline = "\r\n" if "\r\n" in raw else "\n"
        original_lines = [line for line in raw.splitlines() if line.strip()]
        parsed = [json.loads(line) for line in original_lines]
        kept_pairs = [(line, row) for line, row in zip(original_lines, parsed) if not (
            row.get("scoring_version") == SHADOW_VERSION
            and (row.get("shadow_method") == "equal_weight_core" or row.get("shadow_data_origin") == "retrospective_backfill")
        )]
        existing = {(row.get("symbol"), row.get("signal_date"), row.get("snap_time"), row.get("scoring_version")) for _, row in kept_pairs}
        additions = [row for row in backfill_by_month.get(month, []) if (row.get("symbol"), row.get("signal_date"), row.get("snap_time"), row.get("scoring_version")) not in existing]
        removed = len(original_lines) - len(kept_pairs)
        if additions or removed:
            kept_lines = [line for line, _ in kept_pairs]
            addition_lines = [json.dumps(row, ensure_ascii=False, separators=(",", ":"), default=str) for row in additions]
            with path.open("w", encoding="utf-8", newline="") as handle:
                handle.write(newline.join(kept_lines + addition_lines) + newline)
            print(f"{path.name}: removed={removed} added={len(additions)} total={len(kept_lines)+len(additions)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())