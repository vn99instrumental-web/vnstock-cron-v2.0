"""
bt_drift.py — Drift Detection cho scoring edge
================================================
Theo dõi edge của từng indicator + V2 score thay đổi qua thời gian.
Phát hiện khi nào logic mean-reversion bắt đầu suy yếu (market regime change).

ISOLATION:
  ✗ Không import utils/, steps/, config.py
  ✓ Đọc backtest_output/dataset.parquet (do bt_data.py tạo)
  ✓ Đọc/ghi backtest_output/drift_history.json (lịch sử các lần chạy)
  ✓ Ghi backtest_output/reports/drift_h{N}.csv

Cách hoạt động:
  1. Mỗi lần chạy → tính edge hiện tại (toàn dataset + 30 ngày gần nhất)
  2. Lưu snapshot vào drift_history.json với timestamp
  3. So sánh với các snapshot trước → báo indicator nào đang drift
  4. Cảnh báo nếu V2 edge tụt dưới ngưỡng (regime change)

Run:
  python backtest/bt_drift.py --horizon 5
"""
import argparse
import json
import logging
from datetime import datetime, timezone, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).parent.parent
BT_OUTPUT_DIR = REPO_ROOT / "backtest_output"
DRIFT_HISTORY = BT_OUTPUT_DIR / "drift_history.json"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

ICT = timezone(timedelta(hours=7))

# Indicator + cách tính signal (giống bt_audit, nhưng gọn cho drift)
# direction +1: giá trị thỏa điều kiện → kỳ vọng LONG
INDICATOR_SIGNALS = {
    # name: (column, long_condition, short_condition)
    "price_vs_ema200_meanrev": ("_dist_ema200",
                                 lambda x: x < -5, lambda x: x > 5),
    "cmf_meanrev":             ("cmf",
                                 lambda x: x < -0.1, lambda x: x > 0.1),
    "mfi_trend":               ("mfi",
                                 lambda x: x > 60, lambda x: x < 40),
    "rsi_meanrev":             ("rsi",
                                 lambda x: x < 30, lambda x: x > 70),
    "bb_meanrev":              ("bb_pos",
                                 lambda x: x < 0.2, lambda x: x > 0.8),
}


def load_dataset() -> pd.DataFrame:
    path = BT_OUTPUT_DIR / "dataset.parquet"
    if not path.exists():
        raise FileNotFoundError(
            f"Dataset không tìm thấy: {path}\nChạy bt_data.py (mode full) trước."
        )
    df = pd.read_parquet(path)
    # Tính distance EMA200 nếu chưa có
    if "_dist_ema200" not in df.columns and "ema200" in df.columns:
        df["_dist_ema200"] = (df["close"] - df["ema200"]) / df["ema200"] * 100
    return df


def compute_edge(df: pd.DataFrame, col: str, long_cond, short_cond,
                 horizon: int) -> dict:
    """Tính edge = ret_long - ret_short (dương = signal đúng hướng)."""
    ret_col = f"ret_{horizon}d"
    if col not in df.columns:
        return {}
    sub = df.dropna(subset=[col, ret_col])
    if len(sub) < 30:
        return {}

    long_mask  = long_cond(sub[col])
    short_mask = short_cond(sub[col])
    n_long  = long_mask.sum()
    n_short = short_mask.sum()
    if n_long < 10 or n_short < 10:
        return {}

    ret_long  = sub.loc[long_mask,  ret_col].mean() * 100
    ret_short = sub.loc[short_mask, ret_col].mean() * 100
    edge = ret_long - ret_short

    # Hit rate (bỏ flat)
    label_col = f"label_{horizon}d"
    if label_col in sub.columns:
        ln = sub.loc[long_mask  & (sub[label_col] != 0)]
        sn = sub.loc[short_mask & (sub[label_col] != 0)]
        hit_long  = (ln[label_col] ==  1).mean() if len(ln) else np.nan
        hit_short = (sn[label_col] == -1).mean() if len(sn) else np.nan
        n_hit = len(ln) + len(sn)
        hit = ((np.nan_to_num(hit_long)*len(ln) + np.nan_to_num(hit_short)*len(sn)) / n_hit
               if n_hit else np.nan)
    else:
        hit = np.nan

    return {
        "edge_pct": round(edge, 3),
        "hit_avg": round(hit, 3) if not np.isnan(hit) else None,
        "n": int(n_long + n_short),
    }


def compute_v2_edge(df: pd.DataFrame, horizon: int, threshold: int = 20) -> dict:
    """Edge của tech_score_v2 tổng hợp."""
    if "tech_score_v2" not in df.columns:
        return {}
    label_col = f"label_{horizon}d"
    sub = df.dropna(subset=[label_col])
    sub = sub[sub[label_col] != 0]
    buy  = sub["tech_score_v2"] >= threshold
    sell = sub["tech_score_v2"] <= -threshold
    nb, ns = buy.sum(), sell.sum()
    if nb < 20 or ns < 20:
        return {}
    hb = (sub.loc[buy,  label_col] ==  1).mean()
    hs = (sub.loc[sell, label_col] == -1).mean()
    ha = (hb*nb + hs*ns) / (nb+ns)
    corr = sub["tech_score_v2"].corr(sub[label_col])
    return {
        "hit_avg": round(ha, 3),
        "corr": round(corr, 4),
        "n": int(nb + ns),
    }


def snapshot_current(df: pd.DataFrame, horizon: int) -> dict:
    """Tính edge hiện tại: toàn dataset + cửa sổ 30 ngày gần nhất."""
    df = df.copy()
    df["time"] = pd.to_datetime(df["time"])
    max_date = df["time"].max()
    recent_cutoff = max_date - pd.Timedelta(days=30)
    df_recent = df[df["time"] >= recent_cutoff]

    snap = {
        "timestamp": datetime.now(ICT).isoformat(),
        "data_date_max": max_date.strftime("%Y-%m-%d"),
        "horizon": horizon,
        "n_total": len(df),
        "n_recent_30d": len(df_recent),
        "indicators_full": {},
        "indicators_recent": {},
        "v2_full": compute_v2_edge(df, horizon),
        "v2_recent": compute_v2_edge(df_recent, horizon),
    }

    for name, (col, lc, sc) in INDICATOR_SIGNALS.items():
        snap["indicators_full"][name]   = compute_edge(df, col, lc, sc, horizon)
        snap["indicators_recent"][name] = compute_edge(df_recent, col, lc, sc, horizon)

    return snap


def load_history() -> list:
    if not DRIFT_HISTORY.exists():
        return []
    try:
        with open(DRIFT_HISTORY, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []


def save_history(history: list) -> None:
    BT_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    with open(DRIFT_HISTORY, "w", encoding="utf-8") as f:
        json.dump(history, f, ensure_ascii=False, indent=2)


def detect_drift(history: list, current: dict) -> None:
    """So sánh snapshot hiện tại với các snapshot trước."""
    log.info(f"\n{'═'*64}")
    log.info(f"DRIFT DETECTION — horizon={current['horizon']}d")
    log.info(f"{'═'*64}")
    log.info(f"Data đến: {current['data_date_max']}, "
             f"{current['n_total']:,} rows ({current['n_recent_30d']} trong 30d)")

    # ── V2 edge: full vs recent ──
    v2f = current.get("v2_full", {})
    v2r = current.get("v2_recent", {})
    log.info(f"\n── V2 score edge ──")
    if v2f:
        log.info(f"  Toàn bộ : hit_avg={v2f.get('hit_avg')} corr={v2f.get('corr')} (n={v2f.get('n')})")
    if v2r:
        log.info(f"  30d gần : hit_avg={v2r.get('hit_avg')} corr={v2r.get('corr')} (n={v2r.get('n')})")
        # Cảnh báo nếu recent tụt dưới 0.50
        if v2r.get("hit_avg") is not None and v2r["hit_avg"] < 0.50:
            log.warning(f"  ⚠️ V2 hit_avg 30d gần = {v2r['hit_avg']} < 0.50 "
                        f"→ logic đang suy yếu (có thể regime change)")
        elif v2r.get("hit_avg") is not None and v2r["hit_avg"] < 0.52:
            log.warning(f"  ⚠️ V2 hit_avg 30d gần = {v2r['hit_avg']} sát ngưỡng — theo dõi")

    # ── So sánh với lần chạy trước ──
    if history:
        prev = history[-1]
        log.info(f"\n── So với lần trước ({prev.get('data_date_max', '?')}) ──")
        prev_v2 = prev.get("v2_full", {})
        if prev_v2.get("hit_avg") is not None and v2f.get("hit_avg") is not None:
            delta = v2f["hit_avg"] - prev_v2["hit_avg"]
            arrow = "↑" if delta > 0.01 else ("↓" if delta < -0.01 else "→")
            log.info(f"  V2 hit_avg: {prev_v2['hit_avg']} → {v2f['hit_avg']} ({arrow} {delta:+.3f})")
            if delta < -0.03:
                log.warning(f"  ⚠️ V2 edge giảm {abs(delta):.3f} so với lần trước — kiểm tra")

    # ── Per-indicator drift: full vs recent (dấu có đảo không?) ──
    log.info(f"\n── Indicator edge: toàn bộ vs 30d gần (phát hiện đảo dấu) ──")
    log.info(f"  {'indicator':<28} {'full_edge':>10} {'recent_edge':>12} {'cảnh báo'}")
    for name in INDICATOR_SIGNALS:
        ef = current["indicators_full"].get(name, {})
        er = current["indicators_recent"].get(name, {})
        edge_f = ef.get("edge_pct")
        edge_r = er.get("edge_pct")
        if edge_f is None or edge_r is None:
            continue
        warn = ""
        # Đảo dấu giữa full và recent = drift nghiêm trọng
        if edge_f * edge_r < 0 and abs(edge_r) > 0.2:
            warn = "⚠️ ĐẢO DẤU (drift!)"
        elif edge_r < edge_f - 0.5:
            warn = "↓ suy yếu"
        log.info(f"  {name:<28} {edge_f:>10.3f} {edge_r:>12.3f}  {warn}")


def build_drift_csv(history: list, horizon: int) -> pd.DataFrame:
    """Tạo bảng time-series của V2 edge qua các lần chạy."""
    rows = []
    for snap in history:
        if snap.get("horizon") != horizon:
            continue
        v2f = snap.get("v2_full", {})
        v2r = snap.get("v2_recent", {})
        rows.append({
            "timestamp": snap.get("timestamp", "")[:10],
            "data_date": snap.get("data_date_max", ""),
            "v2_hit_full": v2f.get("hit_avg"),
            "v2_corr_full": v2f.get("corr"),
            "v2_hit_recent30d": v2r.get("hit_avg"),
            "n_total": snap.get("n_total"),
        })
    return pd.DataFrame(rows)


def main(horizon: int = 5):
    df = load_dataset()
    history = load_history()

    # Tính snapshot hiện tại
    current = snapshot_current(df, horizon)

    # Detect drift (so với lịch sử)
    detect_drift(history, current)

    # Lưu snapshot mới vào lịch sử
    history.append(current)
    # Giữ tối đa 24 snapshots gần nhất (2 năm nếu chạy hàng tháng)
    history = history[-24:]
    save_history(history)
    log.info(f"\nSnapshot saved → {DRIFT_HISTORY.name} ({len(history)} kỳ lưu)")

    # Xuất time-series CSV
    drift_df = build_drift_csv(history, horizon)
    if len(drift_df) > 0:
        reports = BT_OUTPUT_DIR / "reports"
        reports.mkdir(parents=True, exist_ok=True)
        out_path = reports / f"drift_h{horizon}.csv"
        drift_df.to_csv(out_path, index=False)
        log.info(f"Time-series → {out_path.name}")
        if len(drift_df) >= 2:
            log.info("\n── V2 edge qua các kỳ ──")
            log.info("\n" + drift_df.to_string(index=False))

    log.info(f"\n── HƯỚNG DẪN ĐỌC ──")
    log.info(f"  • V2 hit_recent30d < 0.50 → logic suy yếu, cân nhắc re-audit")
    log.info(f"  • Indicator 'ĐẢO DẤU' → chế độ thị trường đổi, cần đảo lại dấu")
    log.info(f"  • V2 hit giảm dần qua nhiều kỳ → xu hướng drift, không phải nhiễu")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Drift detection cho scoring edge")
    parser.add_argument("--horizon", type=int, default=5, choices=[1, 3, 5])
    args = parser.parse_args()
    main(horizon=args.horizon)
