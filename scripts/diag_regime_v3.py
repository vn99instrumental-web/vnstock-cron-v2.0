"""
diag_regime_v3.py — Việc 1: kiểm tra MÔ TẢ classifier regime v3 trên
lịch sử VNINDEX (24 tháng). READ-ONLY, chạy qua debug.yml.

ĐÂY KHÔNG PHẢI BACKTEST LỢI NHUẬN. Dataset backtest đã cạn (37 test) —
script này CHỈ kiểm tra cái nhãn có hợp lý về mặt mô tả:
  - Mỗi state chiếm bao nhiêu % số phiên?
  - Run trung vị dài mấy phiên (có nhảy loạn không)?
  - RECOVERY có thực sự xuất hiện SAU vùng yếu không?
  - Hysteresis giảm được bao nhiêu transition?
  - Ngày 03/08/2026: v2=DEEP_DOWN, v3 phải =RECOVERY (sanity anchor).

TIÊU CHÍ CHẤP NHẬN (pre-registered 2026-08-03 — chấm PASS/FAIL tự động,
không chỉnh sau khi thấy kết quả):
  AC1  RECOVERY chiếm 3–18% số phiên (sau hysteresis)
  AC2  Run trung vị mọi state ≥ 2 phiên (sau hysteresis)
  AC3  ≥70% lần vào RECOVERY đến từ DEEP_DOWN/DOWNTREND
  AC4  Hysteresis giảm ≥20% số transition so với raw
  AC5  Sanity anchor 2026-08-03: v3 effective = RECOVERY
Pass ≥4/5 (bắt buộc có AC3 + AC5) → tiến Việc 2 (shadow production).
"""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

os.environ["VNSTOCK_INTERACTIVE"] = "0"
os.environ["VNSTOCK_LANGUAGE"]    = "en"
os.environ["MPLCONFIGDIR"]        = "/home/runner/.config/matplotlib"
os.makedirs("/home/runner/.vnstock",           exist_ok=True)
os.makedirs("/home/runner/.config/matplotlib", exist_ok=True)

import json
import logging
from collections import Counter

import numpy as np
import pandas as pd
from vnstock_data import Quote

from utils.helpers import safe_run, now_ict
from utils.cache import save_json
from utils.regime_v3 import classify_v3, apply_hysteresis

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

ANCHOR_DATE = "2026-08-03"   # AC5 sanity anchor


# ─────────────────────────────────────────────────────────────────────
def fetch_vnindex() -> pd.DataFrame | None:
    for ln in ("24M", "18M", "12M"):
        df = safe_run(f"vnindex_{ln}",
             lambda l=ln: Quote(source="VCI", symbol="VNINDEX")
                          .history(length=l, interval="1D"))
        if df is not None and not df.empty and "close" in df.columns:
            df = df.copy()
            tc = "time" if "time" in df.columns else df.columns[0]
            df["time"]  = pd.to_datetime(df[tc])
            df["close"] = pd.to_numeric(df["close"], errors="coerce")
            df = df.dropna(subset=["close"]).sort_values("time")\
                   .reset_index(drop=True)
            log.info(f"VNINDEX {ln}: {len(df)} phiên "
                     f"{df['time'].min().date()} → {df['time'].max().date()}")
            return df[["time", "close"]]
    return None


def classify_v2(close, e50, e200, c5, c20) -> str:
    """Logic v2 production (step_context_refresh) — để so sánh."""
    a50  = close > e50
    a200 = (close > e200) if e200 is not None else a50
    c5   = c5  if c5  is not None else 0.0
    c20  = c20 if c20 is not None else 0.0
    if ((not a50) and (not a200)) or c20 <= -8:
        return "DEEP_DOWN"
    if (not a50) and (c20 <= -2 or c5 <= -3):
        return "DOWNTREND"
    if a50 and a200 and c20 > 0:
        return "UPTREND"
    return "SIDEWAYS"


def build_series(df: pd.DataFrame) -> pd.DataFrame:
    """Point-in-time: EMA/chg tại mỗi phiên chỉ dùng data tới phiên đó."""
    c = df["close"]
    df = df.copy()
    df["ema50"]  = c.ewm(span=50,  adjust=False).mean()
    df["ema200"] = c.ewm(span=200, adjust=False, min_periods=200).mean()
    df["c5"]     = (c / c.shift(5)  - 1) * 100
    df["c20"]    = (c / c.shift(20) - 1) * 100

    rows = []
    for i in range(len(df)):
        r = df.iloc[i]
        e200 = None if pd.isna(r["ema200"]) else float(r["ema200"])
        c5   = None if pd.isna(r["c5"])     else float(r["c5"])
        c20  = None if pd.isna(r["c20"])    else float(r["c20"])
        v3 = classify_v3(float(r["close"]), float(r["ema50"]), e200, c5, c20)
        rows.append({
            "date": r["time"].strftime("%Y-%m-%d"),
            "close": round(float(r["close"]), 2),
            "c5": None if c5 is None else round(c5, 2),
            "c20": None if c20 is None else round(c20, 2),
            "v2": classify_v2(float(r["close"]), float(r["ema50"]),
                              e200, c5, c20),
            "v3_raw": v3["regime_raw"],
            "crash": v3["crash_rule"],
        })
    out = pd.DataFrame(rows)

    # Hysteresis tuần tự (mỗi ngày = 1 phiên; prev_session_raw = raw hôm qua)
    eff, pending = [], []
    prev_eff = None
    for i in range(len(out)):
        prev_raw = out["v3_raw"].iloc[i - 1] if i > 0 else None
        h = apply_hysteresis(out["v3_raw"].iloc[i],
                             bool(out["crash"].iloc[i]),
                             prev_eff, prev_raw)
        prev_eff = h["regime_effective"]
        eff.append(prev_eff)
        pending.append(h["pending"])
    out["v3_eff"] = eff
    out["v3_pending"] = pending
    return out


def run_stats(labels: pd.Series) -> dict:
    """% phân bố, số transition, run length trung vị theo state."""
    n = len(labels)
    dist = {k: round(v / n * 100, 1) for k, v in Counter(labels).items()}
    runs, cur, ln = [], None, 0
    for x in labels:
        if x == cur:
            ln += 1
        else:
            if cur is not None:
                runs.append((cur, ln))
            cur, ln = x, 1
    runs.append((cur, ln))
    med_run = {}
    for st in set(labels):
        lens = [l for s, l in runs if s == st]
        med_run[st] = float(np.median(lens)) if lens else 0.0
    return {"dist_pct": dist, "n_transitions": len(runs) - 1,
            "median_run": med_run, "runs": runs}


# ─────────────────────────────────────────────────────────────────────
def main():
    log.info("═" * 70)
    log.info("  DIAG REGIME V3 — mô tả classifier trên VNINDEX (KHÔNG "
             "phải backtest lợi nhuận, KHÔNG tính vào sổ 37 test)")
    log.info("═" * 70)

    df = fetch_vnindex()
    if df is None or len(df) < 120:
        log.error("❌ Không đủ data VNINDEX (cần ≥120 phiên).")
        return
    ser = build_series(df)

    # Bỏ 20 phiên đầu (c20 chưa có) khỏi thống kê
    ser_stat = ser.iloc[20:].reset_index(drop=True)

    s_v2  = run_stats(ser_stat["v2"])
    s_raw = run_stats(ser_stat["v3_raw"])
    s_eff = run_stats(ser_stat["v3_eff"])

    log.info(f"\n── PHÂN BỐ ({len(ser_stat)} phiên) ──")
    log.info(f"{'state':<11}{'v2 %':>8}{'v3 raw %':>10}{'v3 eff %':>10}"
             f"{'run trung vị (eff)':>22}")
    for st in ("UPTREND", "SIDEWAYS", "RECOVERY", "DOWNTREND", "DEEP_DOWN"):
        log.info(f"{st:<11}"
                 f"{s_v2['dist_pct'].get(st, 0):>8}"
                 f"{s_raw['dist_pct'].get(st, 0):>10}"
                 f"{s_eff['dist_pct'].get(st, 0):>10}"
                 f"{s_eff['median_run'].get(st, 0):>22}")
    log.info(f"Transitions: v2={s_v2['n_transitions']} "
             f"v3_raw={s_raw['n_transitions']} "
             f"v3_eff={s_eff['n_transitions']}")

    # Nguồn vào RECOVERY (theo effective)
    prev_before_rec = []
    for i in range(1, len(ser_stat)):
        if (ser_stat["v3_eff"].iloc[i] == "RECOVERY"
                and ser_stat["v3_eff"].iloc[i - 1] != "RECOVERY"):
            prev_before_rec.append(ser_stat["v3_eff"].iloc[i - 1])
    rec_entries = len(prev_before_rec)
    from_weak = sum(1 for x in prev_before_rec
                    if x in ("DEEP_DOWN", "DOWNTREND"))
    log.info(f"\nRECOVERY entries: {rec_entries} — nguồn: "
             f"{dict(Counter(prev_before_rec))}")

    # 30 ngày gần nhất: v2 vs v3 song song để user soi mắt thường
    log.info(f"\n── 30 PHIÊN GẦN NHẤT (v2 → v3) ──")
    for _, r in ser.tail(30).iterrows():
        mark = "  ← KHÁC" if r["v2"] != r["v3_eff"] else ""
        pend = f" (pending {r['v3_pending']})" if r["v3_pending"] else ""
        log.info(f"{r['date']}  close={r['close']:>9}  "
                 f"c5={str(r['c5']):>7} c20={str(r['c20']):>7}  "
                 f"{r['v2']:<10} → {r['v3_eff']:<10}{pend}{mark}")

    # ── CHẤM TIÊU CHÍ (pre-registered) ──
    rec_pct   = s_eff["dist_pct"].get("RECOVERY", 0)
    min_run   = min(s_eff["median_run"].values()) if s_eff["median_run"] else 0
    from_weak_pct = (from_weak / rec_entries * 100) if rec_entries else 0.0
    trans_cut = (1 - s_eff["n_transitions"] / max(s_raw["n_transitions"], 1)) * 100
    anchor_row = ser[ser["date"] == ANCHOR_DATE]
    anchor_ok  = (not anchor_row.empty
                  and anchor_row["v3_eff"].iloc[-1] == "RECOVERY")

    ac = {
        "AC1_recovery_share_3_18pct": bool(3 <= rec_pct <= 18),
        "AC2_median_run_ge_2":        bool(min_run >= 2),
        "AC3_recovery_from_weak_ge_70pct": bool(from_weak_pct >= 70),
        "AC4_hysteresis_cuts_ge_20pct":    bool(trans_cut >= 20),
        "AC5_anchor_0308_is_recovery":     bool(anchor_ok),
    }
    n_pass = sum(ac.values())
    verdict = (n_pass >= 4 and ac["AC3_recovery_from_weak_ge_70pct"]
               and ac["AC5_anchor_0308_is_recovery"])

    log.info(f"\n── TIÊU CHÍ (pre-registered) ──")
    log.info(f"AC1 RECOVERY share 3–18%      : {rec_pct}%  "
             f"→ {'PASS' if ac['AC1_recovery_share_3_18pct'] else 'FAIL'}")
    log.info(f"AC2 run trung vị ≥2 mọi state : min={min_run}  "
             f"→ {'PASS' if ac['AC2_median_run_ge_2'] else 'FAIL'}")
    log.info(f"AC3 vào RECOVERY từ vùng yếu  : {from_weak_pct:.0f}%  "
             f"→ {'PASS' if ac['AC3_recovery_from_weak_ge_70pct'] else 'FAIL'}")
    log.info(f"AC4 hysteresis cắt transition : {trans_cut:.0f}%  "
             f"→ {'PASS' if ac['AC4_hysteresis_cuts_ge_20pct'] else 'FAIL'}")
    log.info(f"AC5 anchor {ANCHOR_DATE}=RECOVERY : "
             f"{'PASS' if ac['AC5_anchor_0308_is_recovery'] else 'FAIL'}")
    log.info(f"\n{'█'*70}")
    log.info(f"  VERDICT: {'✅ PASS — tiến Việc 2 (shadow production)' if verdict else '❌ FAIL — review ngưỡng, KHÔNG tự chỉnh rồi chạy lại nhiều lần'}"
             f"  ({n_pass}/5)")
    log.info(f"{'█'*70}")

    report = {
        "generated_at": now_ict().strftime("%Y-%m-%d %H:%M"),
        "n_sessions": len(ser_stat),
        "dist_v2": s_v2["dist_pct"], "dist_v3_raw": s_raw["dist_pct"],
        "dist_v3_eff": s_eff["dist_pct"],
        "median_run_v3_eff": s_eff["median_run"],
        "transitions": {"v2": s_v2["n_transitions"],
                        "v3_raw": s_raw["n_transitions"],
                        "v3_eff": s_eff["n_transitions"]},
        "recovery_entries": rec_entries,
        "recovery_entry_sources": dict(Counter(prev_before_rec)),
        "acceptance": ac, "n_pass": n_pass, "verdict_pass": bool(verdict),
        "last_30_sessions": ser.tail(30).to_dict("records"),
    }
    save_json("diag/regime_v3_report.json", report)
    log.info("Report saved → output/diag/regime_v3_report.json")


if __name__ == "__main__":
    main()
