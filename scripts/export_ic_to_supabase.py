#!/usr/bin/env python3
"""
export_ic_to_supabase.py — [E6] Đánh giá forward rank-IC per (version, factor, horizon)
và ghi v4_ic_metrics.

NGUỒN CHÂN LÝ (golden rule #3): TÁI SỬ DỤNG methodology IC chính thức của Python —
import trực tiếp _spearman / daily_last / _load / _f từ eval_forward_ic.py. KHÔNG
reimplement công thức IC. Ghi Supabase dùng lại class Supabase của sync_supabase.py.

Methodology (kế thừa eval_forward_ic.py):
  1) daily-last: mỗi (symbol, signal_date) chỉ giữ snap_time muộn nhất (hết đếm trùng).
  2) IC theo NGÀY rồi TRUNG BÌNH (Spearman trong từng ngày, ≥5 mã/ngày; ≥3 ngày).
  3) Tách horizon 1d/3d/5d/10d.
  Join outcome theo pred_id.

Factor đánh giá (khung trade — outcomes lens='trade'):
  score_trade (tổng) + 6 supergroup norm (mean_reversion/breakout/flow/fundamental/
  growth/context) đọc từ cột trade_<factor>_norm.

Ghi: v4_ic_metrics (config_version, factor, horizon, ic, n) — upsert idempotent.

Env (server-only): SUPABASE_URL (hoặc NEXT_PUBLIC_SUPABASE_URL) + SUPABASE_SERVICE_ROLE_KEY.

Cách chạy:
  python3 scripts/export_ic_to_supabase.py --dry-run     # tính + in, KHÔNG ghi
  python3 scripts/export_ic_to_supabase.py                # tính + ghi Supabase
  python3 scripts/export_ic_to_supabase.py --version v4.17
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
from collections import defaultdict
from pathlib import Path

# Import methodology IC chính thức + client Supabase (single source of truth).
sys.path.insert(0, str(Path(__file__).resolve().parent))
from eval_forward_ic import _spearman, daily_last, _load, _f  # noqa: E402
from sync_supabase import Supabase  # noqa: E402

PRED_GLOB = str(Path(__file__).resolve().parent.parent / "output/history/v2f_predictions_v4/*.jsonl")
OUT_GLOB = str(Path(__file__).resolve().parent.parent / "output/history/v2f_outcomes_v4/*.jsonl")

# factor label (ghi vào v4_ic_metrics.factor) → cột trong prediction ledger.
FACTOR_COLS = {
    "score_trade":    "score_trade",
    "mean_reversion": "trade_mean_reversion_norm",
    "breakout":       "trade_breakout_norm",
    "flow":           "trade_flow_norm",
    "fundamental":    "trade_fundamental_norm",
    "growth":         "trade_growth_norm",
    "context":        "trade_context_norm",
}
HORIZONS = [1, 3, 5, 10]

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("export_ic")


def compute_ic_rows(preds: list[dict], outs: list[dict]) -> list[dict]:
    """Trả list row v4_ic_metrics: mỗi (scoring_version, factor, horizon) 1 row.
    ic = trung bình IC theo ngày (methodology chính thức); n = số quan sát đã chín."""
    ret_by_pid = {o.get("pred_id"): o for o in outs if o.get("pred_id")}

    # gom prediction theo version
    by_version: dict[str, list[dict]] = defaultdict(list)
    for p in preds:
        by_version[p.get("scoring_version") or "unknown"].append(p)

    rows: list[dict] = []
    for version, vpreds in by_version.items():
        vpreds = daily_last(vpreds)  # 1 dòng/(symbol,signal_date)
        for factor, col in FACTOR_COLS.items():
            for h in HORIZONS:
                ret_key = f"ret_{h}d"
                by_day = defaultdict(lambda: ([], []))
                matured = 0
                for p in vpreds:
                    o = ret_by_pid.get(p.get("pred_id"))
                    if not o:
                        continue
                    sc = _f(p.get(col))
                    rt = _f(o.get(ret_key))
                    if sc is None or rt is None:
                        continue
                    xs, ys = by_day[p.get("signal_date")]
                    xs.append(sc)
                    ys.append(rt)
                    matured += 1
                day_ics = []
                for d in by_day:
                    ic = _spearman(*by_day[d])
                    if ic is not None:
                        day_ics.append(ic)
                if len(day_ics) < 3:
                    continue  # chưa đủ ngày chín (methodology: ≥3 ngày)
                mean_ic = sum(day_ics) / len(day_ics)
                rows.append({
                    "config_version": version,
                    "factor":         factor,
                    "horizon":        h,
                    "ic":             round(mean_ic, 6),
                    "n":              matured,
                })
    return rows


def main() -> int:
    ap = argparse.ArgumentParser(description="Tính forward rank-IC → v4_ic_metrics.")
    ap.add_argument("--version", default=None, help="lọc scoring_version (vd v4.17)")
    ap.add_argument("--dry-run", action="store_true", help="tính + in, KHÔNG ghi Supabase")
    args = ap.parse_args()

    preds = _load(PRED_GLOB)
    outs = _load(OUT_GLOB)
    if not preds or not outs:
        log.error("Không có dữ liệu ledger predictions/outcomes.")
        return 1
    if args.version:
        preds = [p for p in preds if p.get("scoring_version") == args.version]

    rows = compute_ic_rows(preds, outs)
    log.info("Tính xong: %d dòng IC (version×factor×horizon).", len(rows))
    for r in sorted(rows, key=lambda x: (x["config_version"], x["factor"], x["horizon"]))[:24]:
        log.info("  %s | %-15s h=%2dd | IC=%+.4f | n=%d",
                 r["config_version"], r["factor"], r["horizon"], r["ic"], r["n"])
    if len(rows) > 24:
        log.info("  … (%d dòng nữa)", len(rows) - 24)

    if args.dry_run:
        log.info("DRY-RUN: bỏ qua ghi Supabase.")
        return 0
    if not rows:
        log.info("Không có dòng IC nào đủ điều kiện — không ghi.")
        return 0

    url = os.environ.get("SUPABASE_URL") or os.environ.get("NEXT_PUBLIC_SUPABASE_URL")
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
    if not url or not key:
        log.error("Thiếu env SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY (server-only).")
        return 2

    sb = Supabase(url, key)
    sb.upsert("v4_ic_metrics", rows, on_conflict="config_version,factor,horizon")
    log.info("=== IC EXPORT DONE === %d dòng.", len(rows))
    return 0


if __name__ == "__main__":
    sys.exit(main())
