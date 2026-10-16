#!/usr/bin/env python3
"""Compute clearly-labelled historical IC for retrospective shadow rows.

The v4.19 backfill re-scores historical v4.18 snapshots but intentionally has no
forward outcome rows of its own. This exporter joins each shadow prediction to
the mature outcome of its audited source prediction, then writes a separate
serving table. It never changes forward IC or v4_outcomes.
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from eval_forward_ic import _load  # noqa: E402
from export_ic_to_supabase import OUT_GLOBS, PRED_GLOBS, compute_ic_rows  # noqa: E402
from sync_supabase import Supabase  # noqa: E402

SHADOW_VERSION = "v4.19-shadow"
SOURCE_VERSION = "v4.18"
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("export_backfill_ic")


def build_backfill_sample(preds: list[dict], outs: list[dict]) -> tuple[list[dict], list[dict]]:
    source_outcomes = {
        o.get("pred_id"): o
        for o in outs
        if o.get("pred_id") and o.get("scoring_version") == SOURCE_VERSION and o.get("lens", "trade") == "trade"
    }
    sample_preds: list[dict] = []
    sample_outs: list[dict] = []
    for pred in preds:
        if pred.get("scoring_version") != SHADOW_VERSION:
            continue
        if pred.get("shadow_data_origin") != "retrospective_backfill":
            continue
        source_id = pred.get("shadow_backfill_source_pred_id")
        outcome = source_outcomes.get(source_id)
        if not outcome:
            continue
        shadow_id = pred.get("pred_id")
        if not shadow_id:
            continue
        mapped = dict(outcome)
        mapped["pred_id"] = shadow_id
        mapped["scoring_version"] = SHADOW_VERSION
        sample_preds.append(pred)
        sample_outs.append(mapped)
    return sample_preds, sample_outs


def compute_backfill_rows(preds: list[dict], outs: list[dict]) -> list[dict]:
    sample_preds, sample_outs = build_backfill_sample(preds, outs)
    rows = compute_ic_rows(sample_preds, sample_outs, include_retrospective=True)
    if not sample_preds:
        return []
    date_min = min(str(p.get("signal_date")) for p in sample_preds)
    date_max = max(str(p.get("signal_date")) for p in sample_preds)
    computed_at = datetime.now(timezone.utc).isoformat()
    for row in rows:
        row.update({
            "sample_kind": "retrospective_backfill",
            "source_version": SOURCE_VERSION,
            "signal_date_min": date_min,
            "signal_date_max": date_max,
            "computed_at": computed_at,
        })
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description="Export retrospective shadow IC separately from forward IC.")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    preds = [row for pattern in PRED_GLOBS for row in _load(pattern)]
    outs = [row for pattern in OUT_GLOBS for row in _load(pattern)]
    rows = compute_backfill_rows(preds, outs)
    log.info("Computed %d historical IC rows for %s.", len(rows), SHADOW_VERSION)
    if args.dry_run:
        for row in rows:
            log.info("%s %s %sd IC=%+.4f n=%s", row["config_version"], row["factor"], row["horizon"], row["ic"], row["n"])
        return 0
    if not rows:
        log.warning("No mature retrospective sample; existing serving rows are unchanged.")
        return 0
    url = os.environ.get("SUPABASE_URL") or os.environ.get("NEXT_PUBLIC_SUPABASE_URL")
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
    if not url or not key:
        log.error("Missing SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY.")
        return 2
    Supabase(url, key).upsert(
        "v4_ic_backfill_metrics", rows,
        on_conflict="config_version,factor,horizon,sample_kind",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

