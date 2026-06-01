"""
bt_evaluate.py — Evaluation + Calibration
==========================================
ISOLATION:
  ✗ Không import utils/, steps/, config.py
  ✓ Đọc backtest_output/dataset.parquet (do bt_data.py tạo)
  ✓ Ghi kết quả vào backtest_output/reports/

Run standalone:
  python backtest/bt_evaluate.py                    # evaluate + grid search
  python backtest/bt_evaluate.py --horizon 3        # dùng 3d label
  python backtest/bt_evaluate.py --threshold 30     # score threshold
  python backtest/bt_evaluate.py --eval-only        # bỏ qua grid search
"""
import argparse
import logging
from itertools import product
from pathlib import Path

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).parent.parent
BT_OUTPUT_DIR = REPO_ROOT / "backtest_output"

from backtest.bt_config import (
    CURRENT_CAPS, CAP_SEARCH_SPACE,
    CURRENT_THRESHOLDS, MIN_SIGNALS,
    HORIZONS,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

GROUPS = ["trend", "momentum", "volume", "volatility"]


# ══════════════════════════════════════════════════════════════════════
# LOAD
# ══════════════════════════════════════════════════════════════════════

def load_dataset() -> pd.DataFrame:
    path = BT_OUTPUT_DIR / "dataset.parquet"
    if not path.exists():
        raise FileNotFoundError(
            f"Dataset không tìm thấy: {path}\n"
            "Chạy: python backtest/bt_data.py trước"
        )
    df = pd.read_parquet(path)
    log.info(
        f"Loaded dataset: {len(df):,} rows, "
        f"{df['symbol'].nunique()} symbols, "
        f"{df['time'].min().date()} → {df['time'].max().date()}"
    )
    return df


# ══════════════════════════════════════════════════════════════════════
# SECTION 1 — BASELINE EVALUATION
# ══════════════════════════════════════════════════════════════════════

def evaluate_baseline(df: pd.DataFrame, horizon: int = 5) -> dict:
    """
    Đánh giá hit rate với caps và weights HIỆN TẠI (production).
    Metric: % dự đoán đúng chiều giá (ignore FLAT labels).
    """
    label_col = f"label_{horizon}d"
    score_col = "tech_score_current"

    df_valid = df.dropna(subset=[label_col, score_col]).copy()
    df_nf    = df_valid[df_valid[label_col] != 0]   # bỏ FLAT

    n_total  = len(df_valid)
    n_flat   = (df_valid[label_col] == 0).sum()
    flat_pct = n_flat / n_total if n_total > 0 else 0

    log.info(f"\n{'═'*60}")
    log.info(f"BASELINE EVALUATION — horizon={horizon}d")
    log.info(f"{'═'*60}")
    log.info(f"Total rows    : {n_total:,}")
    log.info(f"Flat (±{0.5:.1f}%) : {n_flat:,} ({flat_pct:.1%})")
    log.info(f"Non-flat      : {len(df_nf):,}")

    results = {"horizon": horizon, "n_total": n_total}

    # ── 1. Hit rate theo decision bucket (production thresholds) ───────
    log.info(f"\n── Decision buckets (production thresholds) ──")
    thresholds = CURRENT_THRESHOLDS
    bins   = [
        -9999,
        thresholds["sell"],
        thresholds["neutral_low"],
        thresholds["buy"],
        thresholds["strong_buy"],
        9999,
    ]
    labels = ["STRONG SELL", "SELL", "NEUTRAL", "BUY", "STRONG BUY"]
    df_nf["decision"] = pd.cut(
        df_nf[score_col], bins=bins, labels=labels, right=False
    )

    bucket_results = {}
    for dec in ["STRONG BUY", "BUY", "SELL", "STRONG SELL"]:
        sub = df_nf[df_nf["decision"] == dec]
        if len(sub) < MIN_SIGNALS:
            log.info(f"  {dec:12s}: n={len(sub)} — quá ít (min {MIN_SIGNALS})")
            continue
        expected  = 1 if "BUY" in dec else -1
        hit_rate  = (sub[label_col] == expected).mean()
        avg_ret   = sub[f"ret_{horizon}d"].mean() * 100
        bucket_results[dec] = {
            "n": len(sub), "hit_rate": round(hit_rate, 3),
            "avg_ret_pct": round(avg_ret, 2),
        }
        log.info(
            f"  {dec:12s}: n={len(sub):4d}  "
            f"hit_rate={hit_rate:.3f}  "
            f"avg_ret={avg_ret:+.2f}%"
        )

    results["by_decision"] = bucket_results

    # ── 2. Group-level predictiveness ──────────────────────────────────
    log.info(f"\n── Group-level predictiveness ──")
    group_results = {}
    for g in GROUPS:
        raw_col   = f"{g}_raw"
        capped_col = f"{g}_capped"

        for col_name, label in [
            (capped_col, f"{g}_capped"),
            (raw_col,    f"{g}_raw"),
        ]:
            if col_name not in df_nf.columns:
                continue

            sub = df_nf[df_nf[col_name] != 0].dropna(subset=[col_name])
            if len(sub) < MIN_SIGNALS:
                continue

            pred     = sub[col_name].apply(lambda x: 1 if x > 0 else -1)
            hit_rate = (pred == sub[label_col]).mean()
            corr     = sub[col_name].corr(sub[label_col])
            avg_ret  = sub[f"ret_{horizon}d"].mean() * 100

            if label == f"{g}_capped":  # chỉ log capped (chính)
                log.info(
                    f"  {g:12s}: n={len(sub):5d}  "
                    f"hit={hit_rate:.3f}  "
                    f"corr={corr:+.3f}  "
                    f"avg_ret={avg_ret:+.2f}%"
                )

            group_results[label] = {
                "n": len(sub),
                "hit_rate": round(hit_rate, 3),
                "corr": round(corr, 3),
                "avg_ret_pct": round(avg_ret, 2),
            }

    results["by_group"] = group_results

    # ── 3. Hit rate theo score absolute threshold ───────────────────────
    log.info(f"\n── Score threshold sweep ──")
    thresh_results = {}
    for thresh in [10, 20, 30, 40, 50]:
        buy_mask  = df_nf[score_col] >= thresh
        sell_mask = df_nf[score_col] <= -thresh

        n_buy  = buy_mask.sum()
        n_sell = sell_mask.sum()

        if n_buy < MIN_SIGNALS or n_sell < MIN_SIGNALS:
            continue

        hit_buy  = (df_nf.loc[buy_mask,  label_col] ==  1).mean()
        hit_sell = (df_nf.loc[sell_mask, label_col] == -1).mean()
        n_both   = n_buy + n_sell
        hit_avg  = (hit_buy * n_buy + hit_sell * n_sell) / n_both
        coverage = n_both / len(df_nf)

        thresh_results[thresh] = {
            "n_buy": int(n_buy), "n_sell": int(n_sell),
            "hit_buy": round(hit_buy, 3),
            "hit_sell": round(hit_sell, 3),
            "hit_avg": round(hit_avg, 3),
            "coverage": round(coverage, 3),
        }
        log.info(
            f"  |score|≥{thresh:2d}: "
            f"hit_buy={hit_buy:.3f} hit_sell={hit_sell:.3f} "
            f"hit_avg={hit_avg:.3f} coverage={coverage:.1%}"
        )

    results["by_threshold"] = thresh_results

    # ── 4. Symbol-level hit rate (top/bottom predictable) ──────────────
    log.info(f"\n── Per-symbol hit rate (top/bottom 10) ──")
    sym_results = {}
    for sym, grp in df_nf.groupby("symbol"):
        sub = grp[grp[score_col].abs() >= 20].dropna(subset=[label_col])
        if len(sub) < 10:
            continue
        pred     = sub[score_col].apply(lambda x: 1 if x > 0 else -1)
        hit_rate = (pred == sub[label_col]).mean()
        sym_results[sym] = {
            "n": len(sub), "hit_rate": round(hit_rate, 3)
        }

    if sym_results:
        sym_df = pd.DataFrame(sym_results).T.sort_values("hit_rate", ascending=False)
        log.info(f"  Best  : {sym_df.head(5).to_dict('index')}")
        log.info(f"  Worst : {sym_df.tail(5).to_dict('index')}")
        results["by_symbol"] = sym_results

    return results


# ══════════════════════════════════════════════════════════════════════
# SECTION 2 — GRID SEARCH CAPS
# ══════════════════════════════════════════════════════════════════════

def replay_with_caps(df: pd.DataFrame, caps: dict) -> pd.Series:
    """
    Replay total technical score với caps mới.
    Dùng _raw cols (trước khi cap) để replay chính xác.
    """
    total = pd.Series(0.0, index=df.index)
    for g in GROUPS:
        raw_col = f"{g}_raw"
        if raw_col not in df.columns:
            continue
        cap     = caps.get(g, CURRENT_CAPS[g])
        total  += df[raw_col].clip(-cap, cap)
    return total


def grid_search_caps(
    df: pd.DataFrame,
    horizon: int    = 5,
    threshold: int  = 20,
    n_top: int      = 15,
) -> pd.DataFrame:
    """
    Grid search trên CAP_SEARCH_SPACE.
    ~240 combos — chạy <1 phút trên 37k rows.
    """
    label_col = f"label_{horizon}d"
    df_nf     = df.dropna(subset=[label_col]).copy()
    df_nf     = df_nf[df_nf[label_col] != 0]

    keys   = list(CAP_SEARCH_SPACE.keys())
    combos = list(product(*[CAP_SEARCH_SPACE[k] for k in keys]))

    log.info(f"\n{'═'*60}")
    log.info(f"GRID SEARCH — {len(combos)} combos, horizon={horizon}d, threshold={threshold}")
    log.info(f"{'═'*60}")

    baseline_hit = None
    rows = []

    for i, combo in enumerate(combos):
        caps = dict(zip(keys, combo))
        is_current = all(caps[k] == CURRENT_CAPS[k] for k in keys)

        df_nf["new_score"] = replay_with_caps(df_nf, caps)

        buy_mask  = df_nf["new_score"] >= threshold
        sell_mask = df_nf["new_score"] <= -threshold
        n_buy     = buy_mask.sum()
        n_sell    = sell_mask.sum()

        if n_buy < MIN_SIGNALS or n_sell < MIN_SIGNALS:
            continue

        hit_buy  = (df_nf.loc[buy_mask,  label_col] ==  1).mean()
        hit_sell = (df_nf.loc[sell_mask, label_col] == -1).mean()
        n_both   = n_buy + n_sell
        hit_avg  = (hit_buy * n_buy + hit_sell * n_sell) / n_both
        coverage = n_both / len(df_nf)

        row = {
            **caps,
            "hit_buy":   round(hit_buy,  4),
            "hit_sell":  round(hit_sell, 4),
            "hit_avg":   round(hit_avg,  4),
            "coverage":  round(coverage, 4),
            "n_signals": int(n_both),
            "is_current": is_current,
        }
        rows.append(row)

        if is_current:
            baseline_hit = hit_avg
            log.info(
                f"  [CURRENT] caps={caps} "
                f"→ hit_avg={hit_avg:.4f} coverage={coverage:.1%}"
            )

    df_results = (
        pd.DataFrame(rows)
        .sort_values("hit_avg", ascending=False)
        .reset_index(drop=True)
    )

    # Log top N
    log.info(f"\n── Top {n_top} cap combinations ──")
    log.info(
        df_results.head(n_top)[
            [*keys, "hit_buy", "hit_sell", "hit_avg", "coverage", "is_current"]
        ].to_string(index=True)
    )

    if baseline_hit is not None:
        best_hit = df_results["hit_avg"].iloc[0]
        improvement = (best_hit - baseline_hit) / baseline_hit * 100
        log.info(f"\n  Current hit_avg : {baseline_hit:.4f}")
        log.info(f"  Best hit_avg    : {best_hit:.4f}")
        log.info(f"  Improvement     : {improvement:+.2f}%")
        log.info(f"  Best caps       : {df_results[keys].iloc[0].to_dict()}")

    return df_results


# ══════════════════════════════════════════════════════════════════════
# SECTION 3 — WALK-FORWARD VALIDATION
# ══════════════════════════════════════════════════════════════════════

def walk_forward_validate(
    df: pd.DataFrame,
    best_caps: dict,
    horizon: int   = 5,
    threshold: int = 20,
    train_months: int = 3,
    test_months:  int = 1,
) -> pd.DataFrame:
    """
    Walk-forward: train trên 3 tháng, test 1 tháng tiếp.
    Với 12M data → ~9 periods, đủ để đánh giá độ ổn định.
    Xác nhận best_caps không overfit trên in-sample.
    """
    label_col = f"label_{horizon}d"
    df        = df.dropna(subset=[label_col, "time"]).copy()
    df        = df[df[label_col] != 0]
    df["time"] = pd.to_datetime(df["time"])

    log.info(f"\n{'═'*60}")
    log.info(f"WALK-FORWARD VALIDATION")
    log.info(f"  Best caps   : {best_caps}")
    log.info(f"  Train/Test  : {train_months}M / {test_months}M")
    log.info(f"{'═'*60}")

    min_date = df["time"].min()
    max_date = df["time"].max()

    wf_rows  = []
    start    = min_date

    while True:
        train_end = start + pd.DateOffset(months=train_months)
        test_end  = train_end + pd.DateOffset(months=test_months)

        if test_end > max_date:
            break

        train_df = df[(df["time"] >= start) & (df["time"] < train_end)].copy()
        test_df  = df[(df["time"] >= train_end) & (df["time"] < test_end)].copy()

        if len(train_df) < 100 or len(test_df) < 20:
            start += pd.DateOffset(months=test_months)
            continue

        # ── Grid search trên TRAIN window → tìm caps tốt nhất in-sample ──
        keys        = list(CAP_SEARCH_SPACE.keys())
        combos      = list(product(*[CAP_SEARCH_SPACE[k] for k in keys]))
        train_best  = None
        train_best_hit = -1

        for combo in combos:
            caps = dict(zip(keys, combo))
            train_df["score"] = replay_with_caps(train_df, caps)
            bm = train_df["score"] >= threshold
            sm = train_df["score"] <= -threshold
            nb, ns = bm.sum(), sm.sum()
            if nb < MIN_SIGNALS or ns < MIN_SIGNALS:
                continue
            hb = (train_df.loc[bm, label_col] ==  1).mean()
            hs = (train_df.loc[sm, label_col] == -1).mean()
            ha = (hb * nb + hs * ns) / (nb + ns)
            if ha > train_best_hit:
                train_best_hit = ha
                train_best     = caps

        if train_best is None:
            start += pd.DateOffset(months=test_months)
            continue

        # ── Test caps tốt nhất (từ train) trên TEST window (out-of-sample) ──
        test_df["score"] = replay_with_caps(test_df, train_best)

        buy_mask  = test_df["score"] >= threshold
        sell_mask = test_df["score"] <= -threshold
        n_buy, n_sell = buy_mask.sum(), sell_mask.sum()

        if n_buy + n_sell < MIN_SIGNALS:
            start += pd.DateOffset(months=test_months)
            continue

        hit_buy  = (test_df.loc[buy_mask,  label_col] ==  1).mean() if n_buy  else np.nan
        hit_sell = (test_df.loc[sell_mask, label_col] == -1).mean() if n_sell else np.nan
        n_both   = n_buy + n_sell
        hit_avg  = (
            (np.nan_to_num(hit_buy) * n_buy + np.nan_to_num(hit_sell) * n_sell) / n_both
        )

        wf_rows.append({
            "period":        f"{train_end.strftime('%Y-%m')} → {test_end.strftime('%Y-%m')}",
            "test_start":    train_end.strftime("%Y-%m-%d"),
            "test_end":      test_end.strftime("%Y-%m-%d"),
            "train_best_caps": str(train_best),
            "train_hit":     round(train_best_hit, 3),
            "n_signals":     int(n_both),
            "test_hit_avg":  round(hit_avg, 3),
        })

        log.info(
            f"  {wf_rows[-1]['period']}: "
            f"train_hit={train_best_hit:.3f} → test_hit={hit_avg:.3f}  "
            f"(n={n_both}, caps={train_best})"
        )

        start += pd.DateOffset(months=test_months)

    df_wf = pd.DataFrame(wf_rows)
    if len(df_wf) > 0:
        avg_test = df_wf["test_hit_avg"].mean()
        std_test = df_wf["test_hit_avg"].std()
        avg_train = df_wf["train_hit"].mean()
        overfit_gap = avg_train - avg_test
        log.info(f"\n  WF test hit_avg : {avg_test:.3f} ± {std_test:.3f}")
        log.info(f"  WF train hit_avg: {avg_train:.3f}")
        log.info(f"  Overfit gap     : {overfit_gap:+.3f}  (train - test)")
        log.info(f"  → gap < 0.05: tốt | 0.05-0.10: chấp nhận được | >0.10: overfit nặng")
        log.info(f"  → test std < 0.08: caps ổn định qua thời gian")
    return df_wf


# ══════════════════════════════════════════════════════════════════════
# SAVE REPORTS
# ══════════════════════════════════════════════════════════════════════

def save_reports(
    baseline: dict,
    grid_df:  pd.DataFrame,
    wf_df:    pd.DataFrame,
    horizon:  int,
) -> None:
    reports_dir = BT_OUTPUT_DIR / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)

    # Grid results CSV
    grid_path = reports_dir / f"grid_caps_h{horizon}.csv"
    grid_df.to_csv(grid_path, index=False)
    log.info(f"\nSaved: {grid_path}")

    # Walk-forward CSV
    if len(wf_df) > 0:
        wf_path = reports_dir / f"walk_forward_h{horizon}.csv"
        wf_df.to_csv(wf_path, index=False)
        log.info(f"Saved: {wf_path}")

    # Summary text
    summary_path = reports_dir / f"summary_h{horizon}.txt"
    lines = [
        f"=== Backtest Summary — horizon={horizon}d ===\n",
        f"Dataset: {baseline.get('n_total', '?')} rows\n\n",
        "── Baseline (production caps) ──\n",
    ]
    for dec, v in baseline.get("by_decision", {}).items():
        lines.append(
            f"  {dec:12s}: n={v['n']:4d}  "
            f"hit={v['hit_rate']:.3f}  "
            f"avg_ret={v['avg_ret_pct']:+.2f}%\n"
        )
    lines.append("\n── Group predictiveness ──\n")
    for g in GROUPS:
        k = f"{g}_capped"
        v = baseline.get("by_group", {}).get(k, {})
        if v:
            lines.append(
                f"  {g:12s}: n={v['n']:5d}  "
                f"hit={v['hit_rate']:.3f}  "
                f"corr={v['corr']:+.3f}\n"
            )
    lines.append("\n── Best caps (grid search) ──\n")
    if len(grid_df) > 0:
        best = grid_df.iloc[0]
        for g in GROUPS:
            curr = CURRENT_CAPS[g]
            best_cap = int(best[g])
            marker = " ←変更" if best_cap != curr else ""
            lines.append(f"  {g:12s}: {curr} → {best_cap}{marker}\n")
        lines.append(
            f"\n  hit_avg: {best['hit_avg']:.4f} "
            f"(coverage={best['coverage']:.1%})\n"
        )

    with open(summary_path, "w", encoding="utf-8") as f:
        f.writelines(lines)
    log.info(f"Saved: {summary_path}")


# ══════════════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════════════

def compare_v1_v2(df: pd.DataFrame, horizon: int = 5, threshold: int = 20) -> None:
    """
    So sánh trực tiếp bản hiện tại (tech_score_current) vs v2 sửa dấu (tech_score_v2).
    Chỉ chạy nếu dataset có cột tech_score_v2.
    """
    if "tech_score_v2" not in df.columns:
        log.info("\n(Dataset chưa có tech_score_v2 — rebuild full để so sánh v1/v2)")
        return

    label_col = f"label_{horizon}d"
    df = df.dropna(subset=[label_col]).copy()
    df = df[df[label_col] != 0]

    log.info(f"\n{'═'*64}")
    log.info(f"SO SÁNH V1 (hiện tại) vs V2 (sửa dấu) — horizon={horizon}d")
    log.info(f"{'═'*64}")

    for ver, col in [("V1 hiện tại", "tech_score_current"),
                     ("V2 sửa dấu",  "tech_score_v2")]:
        if col not in df.columns:
            continue
        # Correlation score vs label
        corr = df[col].corr(df[label_col])

        # Hit rate ở threshold
        buy  = df[col] >= threshold
        sell = df[col] <= -threshold
        nb, ns = buy.sum(), sell.sum()
        if nb >= MIN_SIGNALS and ns >= MIN_SIGNALS:
            hb = (df.loc[buy,  label_col] ==  1).mean()
            hs = (df.loc[sell, label_col] == -1).mean()
            ha = (hb * nb + hs * ns) / (nb + ns)
            cov = (nb + ns) / len(df)
            log.info(
                f"  {ver:14s}: corr={corr:+.4f}  "
                f"hit_buy={hb:.3f} hit_sell={hs:.3f} "
                f"hit_avg={ha:.3f} coverage={cov:.1%} "
                f"(n_buy={nb}, n_sell={ns})"
            )
        else:
            log.info(f"  {ver:14s}: corr={corr:+.4f}  (không đủ signals ở threshold {threshold})")

    log.info(f"\n  → V2 tốt hơn nếu hit_avg > 0.50 VÀ corr dương rõ rệt")
    log.info(f"  → Nếu cả 2 vẫn ~0.50: technical không tạo alpha, cần hướng khác")

    # ── Walk-forward theo tháng cho V2 (kiểm ổn định out-of-sample) ────
    # V2 dùng dấu cố định (không có caps để tune) → chỉ đo hit_avg mỗi tháng.
    if "tech_score_v2" in df.columns and "time" in df.columns:
        log.info(f"\n── V2 hit_avg theo tháng (out-of-sample stability) ──")
        dfm = df.copy()
        dfm["time"]  = pd.to_datetime(dfm["time"])
        dfm["month"] = dfm["time"].dt.to_period("M").astype(str)

        monthly = []
        for month, grp in dfm.groupby("month"):
            buy  = grp["tech_score_v2"] >= threshold
            sell = grp["tech_score_v2"] <= -threshold
            nb, ns = buy.sum(), sell.sum()
            if nb + ns < MIN_SIGNALS:
                continue
            hb = (grp.loc[buy,  label_col] ==  1).mean() if nb else np.nan
            hs = (grp.loc[sell, label_col] == -1).mean() if ns else np.nan
            ha = (np.nan_to_num(hb) * nb + np.nan_to_num(hs) * ns) / (nb + ns)
            monthly.append({"month": month, "n": int(nb + ns), "hit_avg": round(ha, 3)})
            log.info(f"  {month}: n={nb+ns:4d}  hit_avg={ha:.3f}")

        if monthly:
            hits = [m["hit_avg"] for m in monthly]
            avg  = np.mean(hits)
            std  = np.std(hits)
            n_above = sum(1 for h in hits if h > 0.50)
            log.info(f"\n  V2 monthly: {avg:.3f} ± {std:.3f} "
                     f"({n_above}/{len(hits)} tháng > 0.50)")
            log.info(f"  → ổn định nếu std < 0.06 và đa số tháng > 0.50")


def main(horizon: int = 5, threshold: int = 20, eval_only: bool = False):
    import sys
    sys.path.insert(0, str(REPO_ROOT))

    df = load_dataset()

    # 1. Baseline
    baseline = evaluate_baseline(df, horizon=horizon)

    # 1b. So sánh v1 vs v2 (sửa dấu)
    compare_v1_v2(df, horizon=horizon, threshold=threshold)

    if eval_only:
        log.info("--eval-only: bỏ qua grid search")
        return

    # 2. Grid search
    grid_df = grid_search_caps(df, horizon=horizon, threshold=threshold)

    # 3. Walk-forward với best caps
    best_caps = {}
    if len(grid_df) > 0:
        for g in GROUPS:
            best_caps[g] = int(grid_df[g].iloc[0])
    else:
        best_caps = CURRENT_CAPS.copy()
        log.warning("Grid search không có kết quả — dùng current caps")

    wf_df = walk_forward_validate(
        df, best_caps, horizon=horizon, threshold=threshold
    )

    # 4. Save
    save_reports(baseline, grid_df, wf_df, horizon=horizon)

    log.info("\n=== DONE ===")
    log.info(f"Xem kết quả tại: {BT_OUTPUT_DIR / 'reports'}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Evaluate + calibrate scoring")
    parser.add_argument("--horizon",   type=int,  default=5)
    parser.add_argument("--threshold", type=int,  default=20)
    parser.add_argument("--eval-only", action="store_true")
    args = parser.parse_args()
    main(
        horizon   = args.horizon,
        threshold = args.threshold,
        eval_only = args.eval_only,
    )
