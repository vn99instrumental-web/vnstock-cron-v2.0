"""
bt_audit.py — Audit từng indicator đơn lẻ
==========================================
Đo predictiveness của TỪNG indicator độc lập, không qua scoring logic.
Trả lời: indicator nào thật sự dự đoán được hướng giá? Đúng dấu không?

ISOLATION:
  ✗ Không import utils/, steps/, config.py
  ✓ Đọc backtest_output/dataset.parquet (do bt_data.py tạo)
  ✓ Ghi backtest_output/reports/indicator_audit_h{N}.csv

Run:
  python backtest/bt_audit.py --horizon 5
  python backtest/bt_audit.py --horizon 1
  python backtest/bt_audit.py --all-horizons

Mỗi indicator đo 3 cách:
  1. Threshold-based: theo ngưỡng production (RSI<30, CMF>0.1...) → hit khi long/short
  2. Sign correlation: corr giữa giá trị indicator (hoặc transform) và forward return
  3. Quintile spread: chia 5 nhóm theo giá trị → so return nhóm cao vs thấp
"""
import argparse
import logging
from pathlib import Path

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).parent.parent
BT_OUTPUT_DIR = REPO_ROOT / "backtest_output"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)


def load_dataset() -> pd.DataFrame:
    path = BT_OUTPUT_DIR / "dataset.parquet"
    if not path.exists():
        raise FileNotFoundError(
            f"Dataset không tìm thấy: {path}\nChạy bt_data.py (mode full) trước."
        )
    return pd.read_parquet(path)


# ══════════════════════════════════════════════════════════════════════
# ĐỊNH NGHĨA THRESHOLD CHO TỪNG INDICATOR
# direction: +1 nghĩa là "giá trị cao → kỳ vọng giá lên"
#            -1 nghĩa là "giá trị cao → kỳ vọng giá xuống" (mean-reversion)
# Mỗi rule: (tên, cột, điều kiện long, điều kiện short)
# ══════════════════════════════════════════════════════════════════════

def make_signal(df: pd.DataFrame, col: str, long_cond, short_cond) -> pd.Series:
    """Trả Series: +1 (long), -1 (short), 0 (no signal)."""
    sig = pd.Series(0, index=df.index)
    valid = df[col].notna()
    sig[valid & long_cond(df[col])]  =  1
    sig[valid & short_cond(df[col])] = -1
    return sig


# Mỗi entry: (tên hiển thị, hàm tạo signal). Signal: +1 long / -1 short / 0 none
INDICATOR_RULES = {
    # ── Trend ──
    "ema_cross (20>50 long)": lambda df: make_signal(
        df, "ema_cross_pct", lambda x: x > 0, lambda x: x < 0),
    "price>ema200 (long)": lambda df: (
        pd.Series(np.where(df["close"] > df["ema200"], 1,
                  np.where(df["close"] < df["ema200"], -1, 0)),
                  index=df.index).where(df["ema200"].notna(), 0)),
    "adx>25 + ema_cross dir": lambda df: pd.Series(
        np.where((df["adx"] > 25) & (df["ema_cross_pct"] > 0), 1,
        np.where((df["adx"] > 25) & (df["ema_cross_pct"] < 0), -1, 0)),
        index=df.index),
    "price>supertrend (long)": lambda df: (
        pd.Series(np.where(df["close"] > df["supertrend"], 1,
                  np.where(df["close"] < df["supertrend"], -1, 0)),
                  index=df.index).where(df["supertrend"].notna(), 0)),

    # ── Momentum ──
    "RSI<30 long / >70 short (mean-rev)": lambda df: make_signal(
        df, "rsi", lambda x: x < 30, lambda x: x > 70),
    "RSI>55 long / <45 short (trend)": lambda df: make_signal(
        df, "rsi", lambda x: x > 55, lambda x: x < 45),
    "MACD hist >0 long": lambda df: make_signal(
        df, "macd_hist", lambda x: x > 0, lambda x: x < 0),
    "Stoch K<20 long / >80 short (mean-rev)": lambda df: make_signal(
        df, "stoch_k", lambda x: x < 20, lambda x: x > 80),

    # ── Volume ──
    "CMF>0.1 long / <-0.1 short": lambda df: make_signal(
        df, "cmf", lambda x: x > 0.1, lambda x: x < -0.1),
    "MFI<20 long / >80 short (mean-rev)": lambda df: make_signal(
        df, "mfi", lambda x: x < 20, lambda x: x > 80),
    "MFI>60 long / <40 short (trend)": lambda df: make_signal(
        df, "mfi", lambda x: x > 60, lambda x: x < 40),

    # ── Volatility (BB) ──
    "BB<0.2 long / >0.8 short (mean-rev)": lambda df: make_signal(
        df, "bb_pos", lambda x: x < 0.2, lambda x: x > 0.8),
    "BB>0.8 long / <0.2 short (breakout)": lambda df: make_signal(
        df, "bb_pos", lambda x: x > 0.8, lambda x: x < 0.2),
}


# ══════════════════════════════════════════════════════════════════════
# AUDIT 1 — THRESHOLD-BASED HIT RATE
# ══════════════════════════════════════════════════════════════════════

def audit_thresholds(df: pd.DataFrame, horizon: int) -> pd.DataFrame:
    label_col = f"label_{horizon}d"
    ret_col   = f"ret_{horizon}d"
    df = df.dropna(subset=[label_col, ret_col]).copy()

    rows = []
    for name, rule_fn in INDICATOR_RULES.items():
        try:
            sig = rule_fn(df)
        except Exception as e:
            log.warning(f"  {name}: lỗi — {e}")
            continue

        # Long signals
        long_mask  = sig == 1
        short_mask = sig == -1
        n_long  = long_mask.sum()
        n_short = short_mask.sum()

        if n_long + n_short < 30:
            continue

        # Hit rate: long đúng nếu label=+1, short đúng nếu label=-1
        # Bỏ flat (label=0) khi tính hit
        long_nf  = df.loc[long_mask  & (df[label_col] != 0)]
        short_nf = df.loc[short_mask & (df[label_col] != 0)]

        hit_long  = (long_nf[label_col]  ==  1).mean() if len(long_nf)  else np.nan
        hit_short = (short_nf[label_col] == -1).mean() if len(short_nf) else np.nan

        # Avg forward return theo hướng signal
        ret_long  = df.loc[long_mask,  ret_col].mean() * 100 if n_long  else np.nan
        ret_short = df.loc[short_mask, ret_col].mean() * 100 if n_short else np.nan

        # Edge = (ret khi long) - (ret khi short). Dương = signal đúng hướng
        edge = (np.nan_to_num(ret_long) - np.nan_to_num(ret_short))

        # Combined hit (weighted)
        n_nf = len(long_nf) + len(short_nf)
        if n_nf > 0:
            combined_hit = (
                (np.nan_to_num(hit_long)  * len(long_nf) +
                 np.nan_to_num(hit_short) * len(short_nf)) / n_nf
            )
        else:
            combined_hit = np.nan

        rows.append({
            "indicator":   name,
            "n_long":      int(n_long),
            "n_short":     int(n_short),
            "hit_long":    round(hit_long,  3) if not np.isnan(hit_long)  else None,
            "hit_short":   round(hit_short, 3) if not np.isnan(hit_short) else None,
            "combined_hit": round(combined_hit, 3) if not np.isnan(combined_hit) else None,
            "ret_long_pct":  round(ret_long,  2) if not np.isnan(ret_long)  else None,
            "ret_short_pct": round(ret_short, 2) if not np.isnan(ret_short) else None,
            "edge_pct":      round(edge, 2),
        })

    df_out = pd.DataFrame(rows).sort_values("edge_pct", ascending=False)
    return df_out


# ══════════════════════════════════════════════════════════════════════
# AUDIT 2 — CONTINUOUS CORRELATION
# Corr giữa giá trị indicator thô và forward return
# ══════════════════════════════════════════════════════════════════════

def audit_correlation(df: pd.DataFrame, horizon: int) -> pd.DataFrame:
    ret_col = f"ret_{horizon}d"
    df = df.dropna(subset=[ret_col]).copy()

    # Các indicator dạng continuous + transform hợp lý
    continuous = {
        "ema_cross_pct":        df.get("ema_cross_pct"),
        "rsi":                  df.get("rsi"),
        "rsi_dist_50":          (df["rsi"] - 50) if "rsi" in df else None,  # distance from neutral
        "macd_hist":            df.get("macd_hist"),
        "stoch_k":              df.get("stoch_k"),
        "cmf":                  df.get("cmf"),
        "mfi":                  df.get("mfi"),
        "mfi_dist_50":          (df["mfi"] - 50) if "mfi" in df else None,
        "bb_pos":               df.get("bb_pos"),
        "bb_pos_dist_0.5":      (df["bb_pos"] - 0.5) if "bb_pos" in df else None,
        "adx":                  df.get("adx"),
        "atr_pct":              df.get("atr_pct"),
        "vol_ratio":            df.get("vol_ratio"),
        "price_vs_supertrend":  ((df["close"] - df["supertrend"]) / df["supertrend"] * 100)
                                if "supertrend" in df else None,
        "price_vs_ema200":      ((df["close"] - df["ema200"]) / df["ema200"] * 100)
                                if "ema200" in df else None,
    }

    rows = []
    for name, series in continuous.items():
        if series is None:
            continue
        s = pd.Series(series, index=df.index) if not isinstance(series, pd.Series) else series
        mask = s.notna() & df[ret_col].notna()
        if mask.sum() < 100:
            continue
        corr = s[mask].corr(df.loc[mask, ret_col])
        # Spearman (rank) — bắt quan hệ phi tuyến
        spearman = s[mask].corr(df.loc[mask, ret_col], method="spearman")
        rows.append({
            "indicator": name,
            "n": int(mask.sum()),
            "pearson":  round(corr, 4),
            "spearman": round(spearman, 4),
            "abs_spearman": round(abs(spearman), 4),
        })

    df_out = pd.DataFrame(rows).sort_values("abs_spearman", ascending=False)
    return df_out


# ══════════════════════════════════════════════════════════════════════
# AUDIT 3 — QUINTILE SPREAD
# Chia indicator thành 5 nhóm, so avg return nhóm cao nhất vs thấp nhất
# Spread lớn + monotonic = indicator có giá trị
# ══════════════════════════════════════════════════════════════════════

def audit_quintiles(df: pd.DataFrame, horizon: int) -> pd.DataFrame:
    ret_col = f"ret_{horizon}d"
    df = df.dropna(subset=[ret_col]).copy()

    indicators = ["rsi", "macd_hist", "cmf", "mfi", "bb_pos", "adx",
                  "ema_cross_pct", "vol_ratio", "stoch_k"]

    rows = []
    for ind in indicators:
        if ind not in df.columns:
            continue
        sub = df.dropna(subset=[ind])
        if len(sub) < 500:
            continue

        try:
            sub = sub.copy()
            sub["q"] = pd.qcut(sub[ind], 5, labels=False, duplicates="drop")
        except Exception:
            continue

        q_rets = sub.groupby("q")[ret_col].mean() * 100
        if len(q_rets) < 5:
            continue

        q_low  = q_rets.iloc[0]    # nhóm giá trị thấp nhất
        q_high = q_rets.iloc[-1]   # nhóm cao nhất
        spread = q_high - q_low    # >0: giá trị cao→return cao (momentum)
                                   # <0: giá trị cao→return thấp (mean-rev)

        # Monotonic check: xu hướng tăng/giảm đều qua các quintile
        diffs = q_rets.diff().dropna()
        monotonic_up   = (diffs > 0).all()
        monotonic_down = (diffs < 0).all()
        mono = "↑" if monotonic_up else ("↓" if monotonic_down else "mixed")

        rows.append({
            "indicator": ind,
            "n": len(sub),
            "q1_ret_pct":  round(q_low,  2),
            "q5_ret_pct":  round(q_high, 2),
            "spread_pct":  round(spread, 2),
            "abs_spread":  round(abs(spread), 2),
            "monotonic":   mono,
        })

    df_out = pd.DataFrame(rows).sort_values("abs_spread", ascending=False)
    return df_out


# ══════════════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════════════

def run_audit(horizon: int):
    df = load_dataset()
    log.info(f"\n{'═'*64}")
    log.info(f"INDICATOR AUDIT — horizon={horizon}d, {len(df):,} rows")
    log.info(f"{'═'*64}")

    # ── Audit 1: Threshold hit rate ──
    log.info(f"\n── [1] THRESHOLD-BASED (sorted by edge) ──")
    log.info(f"   edge = ret_long - ret_short (dương = signal đúng hướng)")
    t1 = audit_thresholds(df, horizon)
    if len(t1):
        log.info("\n" + t1.to_string(index=False))

    # ── Audit 2: Correlation ──
    log.info(f"\n── [2] CONTINUOUS CORRELATION (sorted by |spearman|) ──")
    t2 = audit_correlation(df, horizon)
    if len(t2):
        log.info("\n" + t2.to_string(index=False))

    # ── Audit 3: Quintile spread ──
    log.info(f"\n── [3] QUINTILE SPREAD (sorted by |spread|) ──")
    log.info(f"   spread>0: cao→lên (momentum) | spread<0: cao→xuống (mean-rev)")
    t3 = audit_quintiles(df, horizon)
    if len(t3):
        log.info("\n" + t3.to_string(index=False))

    # ── Save ──
    reports = BT_OUTPUT_DIR / "reports"
    reports.mkdir(parents=True, exist_ok=True)
    t1.to_csv(reports / f"audit_threshold_h{horizon}.csv", index=False)
    t2.to_csv(reports / f"audit_correlation_h{horizon}.csv", index=False)
    t3.to_csv(reports / f"audit_quintile_h{horizon}.csv", index=False)
    log.info(f"\nSaved 3 audit CSVs → {reports}")

    # ── Verdict ──
    log.info(f"\n── VERDICT (horizon={horizon}d) ──")
    if len(t2):
        best = t2.iloc[0]
        log.info(f"  Indicator predictive nhất: {best['indicator']} "
                 f"(spearman={best['spearman']:+.4f}, n={best['n']:,})")
        strong = t2[t2["abs_spearman"] > 0.03]
        if len(strong):
            log.info(f"  Có |spearman|>0.03: {', '.join(strong['indicator'].tolist())}")
        else:
            log.info(f"  ⚠️ KHÔNG indicator nào có |spearman|>0.03 — tất cả ~nhiễu")
    if len(t1):
        best_edge = t1.iloc[0]
        if best_edge["edge_pct"] > 0.3:
            log.info(f"  Best edge: {best_edge['indicator']} = {best_edge['edge_pct']:+.2f}%")
        else:
            log.info(f"  ⚠️ Best edge chỉ {best_edge['edge_pct']:+.2f}% — không đáng kể")


def main():
    parser = argparse.ArgumentParser(description="Audit từng indicator đơn lẻ")
    parser.add_argument("--horizon", type=int, default=5, choices=[1, 3, 5])
    parser.add_argument("--all-horizons", action="store_true")
    args = parser.parse_args()

    horizons = [1, 3, 5] if args.all_horizons else [args.horizon]
    for h in horizons:
        run_audit(h)


if __name__ == "__main__":
    main()
