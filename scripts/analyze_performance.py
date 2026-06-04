"""
analyze_performance.py — Tổng hợp hiệu suất đề xuất (weekly)
==============================================================
Chạy SAU step_eval_predictions.py (trong cron_weekly.yml hoặc debug.yml).
Đọc 2 ledger, join theo pred_id, tính các chỉ số calibrate, xuất:

    output/history/performance/latest.json     (ghi đè mỗi tuần)
    output/history/performance/{YYYY-Www}.json  (snapshot tuần, archive)

Mọi chỉ số TÁCH THEO scoring_version (+ block "ALL") → khi đã tune trọng
số, không trộn lẫn các phiên bản mô hình.

CHỈ SỐ:
  by_decision     : n, avg_ret_5d, win_rate, avg_ret_10d theo decision
                    → kiểm đơn điệu STRONG BUY > BUY > NEUTRAL > SELL.
  by_confidence   : tương tự theo HIGH/MEDIUM/LOW.
  group_ic_ret5d  : Spearman corr giữa từng nhóm score và ret_5d
                    → nhóm IC≈0 là nhiễu (nên giảm cap), |IC| cao = có giá trị.
  pattern_flags   : avg_ret_5d theo từng flag (BULL_TRAP_RISK có thật xấu?).
  trade_stats     : fill_rate, tp1/tp2/stop_rate, expectancy_R, win_rate.
  threshold_scan  : avg_ret_5d theo bin total_score (canh lại cutoff 40/80).

KỶ LUẬT: report kèm cảnh báo nếu mẫu nhỏ — KHÔNG chỉnh trọng số khi N nhỏ.

Đọc ledger bằng raw reader (KHÔNG dùng load_json — nó xóa file khi gặp
dòng JSONL không parse được). Report là .json chuẩn nên dùng save_json.

CHANGELOG:
  v1 (2026-06-03) — initial.
"""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import glob
import json
import logging

import pandas as pd

from config import OUTPUT_DIR
from utils.helpers import now_ict
from utils.cache import save_json

logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s %(levelname)s %(message)s')
log = logging.getLogger(__name__)

# =====================================================
# Config
# =====================================================

PRED_GLOB = os.path.join(OUTPUT_DIR, "history/predictions", "*.jsonl")
OUT_GLOB  = os.path.join(OUTPUT_DIR, "history/outcomes",    "*.jsonl")

GROUP_SCORE_COLS = [
    "trend_score", "momentum_score", "volume_score", "volatility_score",
    "order_flow_score", "ff_score", "fundamental_score", "cf_score",
    "growth_score", "news_score", "confluence_bonus", "context_score",
    "tech_score", "fund_score", "total_score",
]

# Ngưỡng mẫu tối thiểu (cảnh báo, không chặn)
MIN_N_DECISION = 30
MIN_N_IC       = 60

# Bin total_score canh theo threshold quyết định 40/80/-15/-40
SCAN_BINS   = [-1e9, -40, -15, 0, 15, 40, 80, 1e9]
SCAN_LABELS = ["<-40", "-40..-15", "-15..0", "0..15", "15..40", "40..80", ">=80"]


# =====================================================
# Helpers
# =====================================================

def _read_jsonl_glob(pattern: str) -> list[dict]:
    rows = []
    for path in sorted(glob.glob(pattern)):
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError:
                    log.warning(f"  bỏ qua dòng lỗi trong {path}")
    return rows


def _r(x, nd: int = 2):
    """Round an toàn cho None/NaN."""
    try:
        if x is None:
            return None
        xf = float(x)
        if xf != xf:   # NaN
            return None
        return round(xf, nd)
    except (TypeError, ValueError):
        return None


# =====================================================
# Compute 1 block (cho 1 scoring_version hoặc ALL)
# =====================================================

def compute_block(df: pd.DataFrame) -> dict:
    block: dict = {}

    # ── by_decision ──
    bd = {}
    if "decision" in df.columns:
        for dec, g in df.groupby("decision"):
            r5 = g["ret_5d"].dropna()
            bd[str(dec)] = {
                "n": int(len(g)),
                "avg_ret_5d":  _r(r5.mean()) if len(r5) else None,
                "win_rate_5d": _r((r5 > 0).mean() * 100) if len(r5) else None,
                "avg_ret_10d": _r(g["ret_10d"].dropna().mean())
                               if "ret_10d" in g else None,
            }
    block["by_decision"] = bd

    # ── by_confidence ──
    bc = {}
    if "confidence" in df.columns:
        for conf, g in df.groupby("confidence"):
            r5 = g["ret_5d"].dropna()
            bc[str(conf)] = {
                "n": int(len(g)),
                "avg_ret_5d":  _r(r5.mean()) if len(r5) else None,
                "win_rate_5d": _r((r5 > 0).mean() * 100) if len(r5) else None,
            }
    block["by_confidence"] = bc

    # ── by_snap_time (sáng vs chiều — chỉ có nghĩa khi ghi mọi run) ──
    bst = {}
    if "snap_time" in df.columns:
        for snap, g in df.groupby("snap_time"):
            if not snap:
                continue
            r5 = g["ret_5d"].dropna()
            # phân bố decision tại snap này (xem model có flip nhiều không)
            dec_counts = g["decision"].value_counts().to_dict() if "decision" in g else {}
            bst[str(snap)] = {
                "n": int(len(g)),
                "avg_ret_5d":  _r(r5.mean()) if len(r5) else None,
                "win_rate_5d": _r((r5 > 0).mean() * 100) if len(r5) else None,
                "decisions":   {str(k): int(v) for k, v in dec_counts.items()},
            }
    block["by_snap_time"] = dict(sorted(bst.items()))

    # ── group IC (Spearman vs ret_5d) ──
    ic = {}
    for c in GROUP_SCORE_COLS:
        if c not in df.columns:
            continue
        sub = df[[c, "ret_5d"]].dropna()
        if len(sub) >= 10 and sub[c].nunique() > 1:
            ic[c] = _r(sub[c].corr(sub["ret_5d"], method="spearman"), 3)
        else:
            ic[c] = None
    block["group_ic_ret5d"] = ic

    # ── pattern flags ──
    pf = {}
    if "pattern_flags" in df.columns:
        ex = df[["pattern_flags", "ret_5d"]].explode("pattern_flags")
        ex = ex.dropna(subset=["pattern_flags"])
        for flag, g in ex.groupby("pattern_flags"):
            r5 = g["ret_5d"].dropna()
            pf[str(flag)] = {
                "n": int(len(g)),
                "avg_ret_5d":  _r(r5.mean()) if len(r5) else None,
                "win_rate_5d": _r((r5 > 0).mean() * 100) if len(r5) else None,
            }
    block["pattern_flags"] = pf

    # ── trade stats (actionable + filled) ──
    ts = {}
    if "actionable" in df.columns:
        act = df[df["actionable"] == True]   # noqa: E712
        ts["n_actionable"] = int(len(act))
        if len(act):
            ts["fill_rate"] = _r((act["filled"] == True).mean() * 100)  # noqa: E712
            filled = act[act["filled"] == True]                          # noqa: E712
            ts["n_filled"] = int(len(filled))
            if len(filled):
                ts["tp1_rate"]     = _r((filled["hit_tp1"] == True).mean() * 100)  # noqa: E712
                ts["tp2_rate"]     = _r((filled["hit_tp2"] == True).mean() * 100)  # noqa: E712
                ts["stop_rate"]    = _r((filled["hit_stop"] == True).mean() * 100) # noqa: E712
                ts["expectancy_R"] = _r(filled["realized_R"].dropna().mean())
                if "trade_outcome" in filled.columns:
                    ts["win_rate"] = _r((filled["trade_outcome"] == "WIN").mean() * 100)
    block["trade_stats"] = ts

    # ── threshold scan ──
    scan = []
    if "total_score" in df.columns:
        tdf = df.dropna(subset=["ret_5d", "total_score"]).copy()
        if len(tdf):
            tdf["bucket"] = pd.cut(tdf["total_score"], bins=SCAN_BINS,
                                   labels=SCAN_LABELS, right=False)
            for b, g in tdf.groupby("bucket", observed=True):
                scan.append({
                    "bucket": str(b),
                    "n": int(len(g)),
                    "avg_ret_5d":  _r(g["ret_5d"].mean()),
                    "win_rate_5d": _r((g["ret_5d"] > 0).mean() * 100),
                })
    block["threshold_scan"] = scan

    return block


# =====================================================
# MAIN
# =====================================================

def main():
    log.info(f"Time: {now_ict():%Y-%m-%d %H:%M:%S} ICT")

    preds = _read_jsonl_glob(PRED_GLOB)
    outs  = _read_jsonl_glob(OUT_GLOB)
    log.info(f"Predictions: {len(preds)} | Outcomes: {len(outs)}")

    report = {
        "generated_at": now_ict().isoformat(),
        "horizon_note": "ret_Nd = % so với close ngày signal_date; "
                        "outcome đóng khi đủ 10 phiên. STOP ưu tiên khi "
                        "cùng phiên chạm cả stop lẫn TP.",
        "sample": {
            "predictions_total": len(preds),
            "outcomes_total": len(outs),
        },
        "warnings": [],
        "by_version": {},
    }

    if not outs:
        report["warnings"].append(
            "Chưa có outcome nào đóng — cần tích lũy ≥10 phiên sau đề xuất "
            "đầu tiên. Report sẽ có số liệu ở các tuần sau.")
        save_json("history/performance/latest.json", report)
        _save_weekly(report)
        log.info("Chưa có outcome — ghi report rỗng. Xong.")
        return

    df_pred = pd.DataFrame(preds)
    df_out  = pd.DataFrame(outs)

    # Chỉ lấy cột cần từ outcome, đổi tên outcome→trade_outcome tránh nhầm
    out_cols = ["pred_id", "ret_1d", "ret_3d", "ret_5d", "ret_10d",
                "mfe_pct", "mae_pct", "filled", "hit_tp1", "hit_tp2",
                "hit_stop", "first_hit", "realized_R", "outcome"]
    out_cols = [c for c in out_cols if c in df_out.columns]
    df_out = df_out[out_cols].rename(columns={"outcome": "trade_outcome"})

    df = df_pred.merge(df_out, on="pred_id", how="inner")
    report["sample"]["closed_joined"] = int(len(df))
    if "signal_date" in df.columns and len(df):
        report["sample"]["date_range"] = [
            str(df["signal_date"].min()), str(df["signal_date"].max())]

    if len(df) < MIN_N_DECISION:
        report["warnings"].append(
            f"Mẫu nhỏ (N={len(df)} < {MIN_N_DECISION}). Số liệu chỉ tham "
            f"khảo — CHƯA nên chỉnh trọng số.")
    if len(df) < MIN_N_IC:
        report["warnings"].append(
            f"IC chưa đáng tin (N={len(df)} < {MIN_N_IC}).")

    # ── Block ALL + từng scoring_version ──
    report["by_version"]["ALL"] = compute_block(df)
    if "scoring_version" in df.columns:
        for ver, g in df.groupby("scoring_version"):
            report["by_version"][str(ver)] = compute_block(g)

    save_json("history/performance/latest.json", report)
    _save_weekly(report)

    _print_summary(report)
    log.info("=== ANALYZE PERFORMANCE DONE ===")


def _save_weekly(report: dict):
    y, w, _ = now_ict().isocalendar()
    save_json(f"history/performance/{y}-W{w:02d}.json", report)


def _print_summary(report: dict):
    log.info("─" * 55)
    log.info(f"Closed joined: {report['sample'].get('closed_joined')}")
    for wn in report["warnings"]:
        log.info(f"⚠️  {wn}")
    allb = report["by_version"].get("ALL", {})
    log.info("By decision (avg_ret_5d | win% | n):")
    for dec, m in allb.get("by_decision", {}).items():
        log.info(f"  {dec:<12} {str(m['avg_ret_5d']):>7} | "
                 f"{str(m['win_rate_5d']):>5} | n={m['n']}")
    log.info("Group IC vs ret_5d:")
    for c, v in allb.get("group_ic_ret5d", {}).items():
        log.info(f"  {c:<20} {v}")
    ts = allb.get("trade_stats", {})
    if ts.get("n_filled"):
        log.info(f"Trade: fill={ts.get('fill_rate')}% tp1={ts.get('tp1_rate')}% "
                 f"stop={ts.get('stop_rate')}% expR={ts.get('expectancy_R')} "
                 f"win={ts.get('win_rate')}% (n_filled={ts['n_filled']})")


if __name__ == "__main__":
    main()
