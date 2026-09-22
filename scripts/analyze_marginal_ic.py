#!/usr/bin/env python3
"""
analyze_marginal_ic.py — [phân tích tham chiếu] Đóng góp BIÊN của từng chỉ báo con.

Mục đích: IC đơn biến (v4_ic_by_indicator) chỉ nói "chỉ báo X có tương quan với
lợi nhuận", NHƯNG các chỉ báo trùng lặp tín hiệu (Williams %R, overext EMA,
RS-reversal đều đo 'quá bán'). Hồi quy ĐA BIẾN tách đóng góp RIÊNG của từng chỉ
báo khi đã kiểm soát các chỉ báo còn lại → biết chỉ báo nào thật sự thêm sức dự
báo (để combine version mới, khử trùng lặp).

Phương pháp (cross-sectional, chuẩn học thuật kiểu Fama-MacBeth rút gọn):
  1) daily-last: 1 dòng / (symbol, signal_date) — bỏ đếm trùng snap.
  2) DEMEAN trong từng phiên (cross-sectional): trừ trung bình ngày khỏi mỗi chỉ
     báo & khỏi lợi nhuận → khử biến động toàn thị trường theo ngày (yếu tố
     market-wide như s_mkt_context tự triệt tiêu, đúng bản chất).
  3) Chuẩn hoá (z-score) mỗi chỉ báo & lợi nhuận → hệ số so sánh được, cùng thang IC.
  4) OLS đa biến y ~ X (không hệ số chặn vì đã demean). coef = đóng góp biên;
     t-stat = độ tin (|t|≥2 ~ có ý nghĩa). Kèm R² (phần biến thiên giải thích được).
  5) univar_ic = IC đơn biến (Spearman gộp) từng chỉ báo — để đối chiếu corr vs biên.

Chạy per VERSION (chỉ version đủ mẫu). GỘP toàn kỳ trong version — ước lượng tham
chiếu, KHÔNG phải IC chính thức evaluator.

Ghi bảng public.v4_marginal_ic (version, indicator, factor, horizon, coef, tstat,
univar_ic, n) + dòng đặc biệt indicator='_model_r2' (coef=R², n=obs).

Chạy:
  python3 scripts/analyze_marginal_ic.py --dry-run     # tính + in, KHÔNG ghi
  python3 scripts/analyze_marginal_ic.py --json OUT.json
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from eval_forward_ic import daily_last, _load, _f  # noqa: E402
from sync_supabase import Supabase  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("marginal_ic")

PRED_GLOB = str(Path(__file__).resolve().parent.parent / "output/history/v2f_predictions_v4/*.jsonl")
OUT_GLOB = str(Path(__file__).resolve().parent.parent / "output/history/v2f_outcomes_v4/*.jsonl")

# 17 chỉ báo con → nhóm nhân tố (khớp migration 0013 & lib/interpret.ts).
IND_FACTOR = [
    ("s_willr_mr", "mean_reversion"), ("s_bb_mr", "mean_reversion"),
    ("s_overext_ema", "mean_reversion"), ("s_rs_reversal", "mean_reversion"),
    ("s_deep_dd", "mean_reversion"),
    ("s_dist_52w", "breakout"), ("s_vol_ratio_h", "breakout"), ("s_trend_st", "breakout"),
    ("s_ff_net", "flow"), ("s_of_phasefix", "flow"), ("s_prop_5d", "flow"),
    ("s_insider", "flow"), ("s_depth_wall", "flow"),
    ("s_fund_core", "fundamental"), ("s_cf_core", "fundamental"),
    ("s_growth_core", "growth"),
    ("s_mkt_context", "context"),
]
INDICATORS = [k for k, _ in IND_FACTOR]
FACTOR_OF = dict(IND_FACTOR)
HORIZONS = [1, 3, 5, 10]

MIN_DAY_STOCKS = 5     # phiên cần ≥5 mã mới demean được
MIN_OBS = 150          # version×horizon cần ≥150 quan sát mới hồi quy
MIN_COVERAGE = 0.40    # chỉ báo cần có mặt ≥40% dòng mới đưa vào X


def _spearman_ic(x: np.ndarray, y: np.ndarray) -> float | None:
    """IC đơn biến = corr hạng (Spearman) gộp."""
    if len(x) < 5:
        return None
    rx = np.argsort(np.argsort(x)).astype(float)
    ry = np.argsort(np.argsort(y)).astype(float)
    if rx.std() == 0 or ry.std() == 0:
        return None
    return float(np.corrcoef(rx, ry)[0, 1])


def analyze_version(vpreds: list[dict], ret_by_pid: dict, horizon: int) -> list[dict] | None:
    """Trả list row cho 1 (version, horizon), hoặc None nếu thiếu mẫu."""
    ret_key = f"ret_{horizon}d"
    # gom theo ngày
    by_day: dict[str, list[dict]] = defaultdict(list)
    for p in vpreds:
        o = ret_by_pid.get(p.get("pred_id"))
        if not o:
            continue
        rt = _f(o.get(ret_key))
        if rt is None:
            continue
        row = {"ret": rt}
        for ind in INDICATORS:
            row[ind] = _f(p.get(ind))
        by_day[p.get("signal_date")].append(row)

    # demean trong ngày; gom lại
    Xrows: list[list[float]] = []
    yrows: list[float] = []
    cover: dict[str, int] = {ind: 0 for ind in INDICATORS}
    for d, rows in by_day.items():
        if len(rows) < MIN_DAY_STOCKS:
            continue
        rmean = np.mean([r["ret"] for r in rows])
        # trung bình ngày mỗi chỉ báo (bỏ None)
        dmean = {}
        for ind in INDICATORS:
            vals = [r[ind] for r in rows if r[ind] is not None]
            dmean[ind] = np.mean(vals) if vals else 0.0
        for r in rows:
            xr = []
            for ind in INDICATORS:
                v = r[ind]
                if v is None:
                    xr.append(0.0)  # thiếu → 0 (= trung bình ngày sau demean → trung tính)
                else:
                    xr.append(v - dmean[ind])
                    cover[ind] += 1
            Xrows.append(xr)
            yrows.append(r["ret"] - rmean)

    n = len(yrows)
    if n < MIN_OBS:
        return None

    X = np.array(Xrows, dtype=float)   # (n, 17) đã demean
    y = np.array(yrows, dtype=float)   # (n,) đã demean

    # chọn chỉ báo đủ phủ + có phương sai
    keep = [i for i, ind in enumerate(INDICATORS)
            if cover[ind] >= MIN_COVERAGE * n and X[:, i].std() > 1e-9]
    if len(keep) < 2:
        return None
    Xk = X[:, keep]
    kept_inds = [INDICATORS[i] for i in keep]

    # chuẩn hoá z-score (cột & y) để hệ số cùng thang, so sánh được
    Xz = Xk / Xk.std(axis=0, keepdims=True)
    ysd = y.std()
    if ysd < 1e-12:
        return None
    yz = y / ysd

    # OLS: yz = Xz beta  (không chặn — đã demean)
    beta, _res, _rank, _sv = np.linalg.lstsq(Xz, yz, rcond=None)
    resid = yz - Xz @ beta
    dof = max(1, n - len(kept_inds))
    sigma2 = float(resid @ resid) / dof
    XtX_inv = np.linalg.inv(Xz.T @ Xz)
    se = np.sqrt(np.maximum(np.diag(XtX_inv) * sigma2, 0.0))
    tstat = np.where(se > 0, beta / se, 0.0)
    ss_tot = float(yz @ yz)
    r2 = 1.0 - float(resid @ resid) / ss_tot if ss_tot > 0 else 0.0

    out: list[dict] = []
    for j, ind in enumerate(kept_inds):
        out.append({
            "indicator": ind, "factor": FACTOR_OF[ind], "horizon": horizon,
            "coef": round(float(beta[j]), 4), "tstat": round(float(tstat[j]), 2),
            "univar_ic": None, "n": n,
        })
    # univar IC (Spearman gộp: chỉ báo thô vs ret thô, cùng dòng, x non-null) — đối chiếu
    for ind in kept_inds:
        xs, ys = [], []
        for rows in by_day.values():
            if len(rows) < MIN_DAY_STOCKS:
                continue
            for r in rows:
                if r[ind] is not None:
                    xs.append(r[ind]); ys.append(r["ret"])
        uic = _spearman_ic(np.array(xs), np.array(ys)) if len(xs) >= 5 else None
        for row in out:
            if row["indicator"] == ind:
                row["univar_ic"] = None if uic is None else round(uic, 3)
    out.append({"indicator": "_model_r2", "factor": None, "horizon": horizon,
                "coef": round(r2, 4), "tstat": None, "univar_ic": None, "n": n})
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--json", default=None, help="ghi kết quả ra file JSON")
    args = ap.parse_args()

    preds = _load(PRED_GLOB)
    outs = _load(OUT_GLOB)
    ret_by_pid = {o.get("pred_id"): o for o in outs if o.get("pred_id")}
    by_version: dict[str, list[dict]] = defaultdict(list)
    for p in preds:
        by_version[p.get("scoring_version") or "?"].append(p)

    all_rows: list[dict] = []
    for ver, vpreds in by_version.items():
        vp = daily_last(vpreds)
        vrows: list[dict] = []
        for h in HORIZONS:
            res = analyze_version(vp, ret_by_pid, h)
            if res:
                for r in res:
                    r["version"] = ver
                vrows.extend(res)
        if vrows:
            all_rows.extend(vrows)
            r2_5 = next((r["coef"] for r in vrows if r["indicator"] == "_model_r2" and r["horizon"] == 5), None)
            n5 = next((r["n"] for r in vrows if r["horizon"] == 5), None)
            print(f"{ver}: {len(vrows)} rows | R²(5d)={r2_5} | n(5d)={n5}")

    log.info("Tính xong: %d dòng, %d version.", len(all_rows), len(set(r["version"] for r in all_rows)))
    if args.json:
        json.dump(all_rows, open(args.json, "w"))
        log.info("Đã ghi JSON %s", args.json)
    if args.dry_run:
        # in top marginal cho version nhiều mẫu nhất @5d
        best = max(by_version, key=lambda v: len(by_version[v]))
        print(f"\n--- {best} · marginal coef @5d (sort |coef|) ---")
        r5 = [r for r in all_rows if r["version"] == best and r["horizon"] == 5 and r["indicator"] != "_model_r2"]
        for r in sorted(r5, key=lambda x: -abs(x["coef"])):
            print(f"  {r['indicator']:15} [{r['factor']:14}] coef={r['coef']:+.3f} t={r['tstat']:+.1f} | univarIC={r['univar_ic']}")
        log.info("DRY-RUN: bỏ qua ghi Supabase.")
        return 0
    if not all_rows:
        log.info("Không có dòng nào đủ mẫu — không ghi.")
        return 0

    url = os.environ.get("SUPABASE_URL") or os.environ.get("NEXT_PUBLIC_SUPABASE_URL")
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
    if not url or not key:
        log.error("Thiếu env SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY (server-only).")
        return 2
    sb = Supabase(url, key)
    sb.upsert("v4_marginal_ic", all_rows, on_conflict="version,indicator,horizon")
    log.info("=== MARGINAL IC DONE === %d dòng.", len(all_rows))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
