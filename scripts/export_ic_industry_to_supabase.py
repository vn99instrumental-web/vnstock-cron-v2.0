#!/usr/bin/env python3
"""Compute daily Spearman IC by scoring version, factor, industry and horizon.

Rows are written under a new batch id first; the ready pointer is published last.
This makes the dashboard read an all-or-nothing snapshot.
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
import uuid
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from eval_forward_ic import _f, _load, _spearman, daily_last  # noqa: E402
from sync_supabase import Supabase  # noqa: E402

PRED_GLOB = str(Path(__file__).resolve().parent.parent / "output/history/v2f_predictions_v4/*.jsonl")
OUT_GLOB = str(Path(__file__).resolve().parent.parent / "output/history/v2f_outcomes_v4/*.jsonl")
FACTORS = {"score_trade": "score_trade", "mean_reversion": "trade_mean_reversion_norm",
           "breakout": "trade_breakout_norm", "flow": "trade_flow_norm",
           "fundamental": "trade_fundamental_norm", "growth": "trade_growth_norm",
           "context": "trade_context_norm"}
HORIZONS = (1, 3, 5, 10)
BATCH = 200
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("export_ic_industry")

def compute_rows(preds, outs, batch_id):
    ret = {o.get("pred_id"): o for o in outs if o.get("pred_id")}
    by_version = defaultdict(list)
    for p in preds:
        by_version[p.get("scoring_version") or "unknown"].append(p)
    rows = []
    asof = None
    for version, source in by_version.items():
        last = daily_last(source)
        for factor, col in FACTORS.items():
            for horizon in HORIZONS:
                groups = defaultdict(lambda: defaultdict(lambda: ([], [])))
                for p in last:
                    o = ret.get(p.get("pred_id"))
                    industry = p.get("industry") or p.get("sector_group")
                    x, y = _f(p.get(col)), _f(o.get(f"ret_{horizon}d")) if o else None
                    if not industry or x is None or y is None:
                        continue
                    groups[str(industry)][p.get("signal_date")][0].append(x)
                    groups[str(industry)][p.get("signal_date")][1].append(y)
                    asof = max(asof or p.get("signal_date"), p.get("signal_date"))
                for industry, by_day in groups.items():
                    day_ics = [_spearman(*xy) for xy in by_day.values() if len(xy[0]) >= 5]
                    day_ics = [v for v in day_ics if v is not None]
                    if len(day_ics) < 3:
                        continue
                    rows.append({"batch_id": batch_id, "version": version, "factor": factor,
                                 "industry": industry, "horizon": horizon,
                                 "ic": round(sum(day_ics) / len(day_ics), 6),
                                 "n": sum(len(xy[0]) for xy in by_day.values()),
                                 "n_days": len(day_ics), "data_asof": asof})
    return rows, asof

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    preds, outs = _load(PRED_GLOB), _load(OUT_GLOB)
    if not preds or not outs:
        log.error("Missing prediction/outcome ledger")
        return 1
    batch_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:8]
    rows, asof = compute_rows(preds, outs, batch_id)
    log.info("Computed %d IC industry rows (batch %s, asof %s)", len(rows), batch_id, asof)
    if args.dry_run:
        return 0
    url = os.environ.get("SUPABASE_URL") or os.environ.get("NEXT_PUBLIC_SUPABASE_URL")
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
    if not url or not key:
        log.error("Missing SUPABASE_URL/SUPABASE_SERVICE_ROLE_KEY")
        return 2
    sb = Supabase(url, key)
    for i in range(0, len(rows), BATCH):
        sb.upsert("v4_ic_industry_metrics", rows[i:i+BATCH], on_conflict="batch_id,version,factor,industry,horizon")
    sb.upsert("v4_ic_industry_batch", [{"batch_id": batch_id, "data_asof": asof,
                                        "row_count": len(rows), "status": "ready"}], on_conflict="batch_id")
    log.info("Published ready batch %s", batch_id)
    return 0

if __name__ == "__main__":
    sys.exit(main())
