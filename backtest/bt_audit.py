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


# ══════════════════════════════════════════════════════════════════════
# AUDIT XẾP HẠNG TRONG NHÓM NGÀNH (thêm 23/07/2026)
# ══════════════════════════════════════════════════════════════════════
# BỐI CẢNH: walk-forward (23/07) cho thấy chấm điểm theo NGƯỠNG TUYỆT ĐỐI
# không tổng quát hóa được — hit ngoài mẫu 0.486 (5d) / 0.495 (1d), grid
# search tốt nhất 0.4943, tức thua tung xu ở MỌI cấu hình trọng số.
#
# GIẢ THUYẾT CÒN LẠI: xếp hạng CẮT NGANG trong nhóm ngành khác về bản chất
# — không hỏi "mã này mạnh hay yếu" mà hỏi "mã này đứng thứ mấy trong nhóm
# hôm nay". Forward 3 tuần cho +2.29%/5 phiên, hit 71%, dương 10/11 ngày.
# Đây là phép kiểm tra giả thuyết đó trên 16 tháng + walk-forward.
#
# KHÔNG đụng 3 audit cũ — kết quả các lần chạy trước vẫn so sánh được.

# Ngành con (icb_name) → 6 nhóm cấu trúc định giá đồng nhất.
# Đồng bộ với utils/v2f_industry_groups.py (production). KHÔNG import
# production code (luật cách ly backtest) → chép bảng sang đây.
SECTOR_GROUPS = {
    "Ngân hàng": "NGAN_HANG",
    "Bất động sản": "BAT_DONG_SAN",
    "Dịch vụ tài chính": "TAI_CHINH_PHI_NH",
    "Bảo hiểm": "TAI_CHINH_PHI_NH",
    "Xây dựng và Vật liệu": "CONG_NGHIEP",
    "Hàng & Dịch vụ Công nghiệp": "CONG_NGHIEP",
    "Tài nguyên Cơ bản": "NGUYEN_LIEU_NANG_LUONG",
    "Hóa chất": "NGUYEN_LIEU_NANG_LUONG",
    "Dầu khí": "NGUYEN_LIEU_NANG_LUONG",
    "Điện, nước & xăng dầu khí đốt": "NGUYEN_LIEU_NANG_LUONG",
    "Thực phẩm và đồ uống": "TIEU_DUNG_DICH_VU",
    "Bán lẻ": "TIEU_DUNG_DICH_VU",
    "Y tế": "TIEU_DUNG_DICH_VU",
    "Du lịch và Giải trí": "TIEU_DUNG_DICH_VU",
    "Hàng cá nhân & Gia dụng": "TIEU_DUNG_DICH_VU",
    "Ô tô và phụ tùng": "TIEU_DUNG_DICH_VU",
    "Công nghệ Thông tin": "TIEU_DUNG_DICH_VU",
    "Truyền thông": "TIEU_DUNG_DICH_VU",
    "Viễn thông": "TIEU_DUNG_DICH_VU",
}

# Chỉ báo đem xếp hạng. Cột phải có sẵn trong dataset.
RANK_FACTORS = [
    ("trend_rank",  "ema_cross_pct"),   # sức mạnh xu hướng tương đối
    ("adx_rank",    "adx"),
    ("rsi_rank",    "rsi"),
    ("mfi_rank",    "mfi"),
    ("bb_rank",     "bb_pos"),
    ("cmf_rank",    "cmf"),
    ("vol_rank",    "vol_ratio"),
]

MIN_GROUP_SIZE = 8      # nhóm nhỏ hơn → hạng vô nghĩa, bỏ qua
RANK_TOP = 0.70
RANK_BOT = 0.30


def _prepare_sector_ranks(df: pd.DataFrame) -> pd.DataFrame | None:
    """Gắn sector_group + hạng phần trăm trong (ngày, nhóm) cho từng factor.
    Trả None nếu dataset chưa có cột industry (bt_data.py bản cũ)."""
    if "industry" not in df.columns:
        log.warning("Dataset KHÔNG có cột 'industry' — bỏ qua audit theo ngành. "
                    "Chạy lại mode=full với bt_data.py bản mới (>=23/07).")
        return None

    d = df.copy()
    d["sector_group"] = d["industry"].map(SECTOR_GROUPS).fillna("KHAC")

    # Loại nhóm quá nhỏ theo từng ngày (hạng trong nhóm <8 mã = nhiễu)
    grp_size = d.groupby(["time", "sector_group"])["symbol"].transform("size")
    d = d[grp_size >= MIN_GROUP_SIZE].copy()
    if not len(d):
        log.warning("Không nhóm (ngày, ngành) nào đủ %d mã", MIN_GROUP_SIZE)
        return None

    for rank_name, col in RANK_FACTORS:
        if col not in d.columns:
            continue
        d[rank_name] = (d.groupby(["time", "sector_group"])[col]
                          .rank(pct=True, method="average"))
    return d


def audit_sector_ranks(df: pd.DataFrame, horizon: int) -> pd.DataFrame:
    """Top30% vs bot30% TRONG NHÓM NGÀNH, đo bằng lợi suất VƯỢT TRUNG BÌNH
    NHÓM cùng ngày (đã triệt tiêu hiệu ứng ngành và hiệu ứng thị trường)."""
    d = _prepare_sector_ranks(df)
    if d is None:
        return pd.DataFrame()

    ret_col = f"ret_{horizon}d"
    if ret_col not in d.columns:
        return pd.DataFrame()
    d = d.dropna(subset=[ret_col])
    if not len(d):
        return pd.DataFrame()

    # excess = ret - trung bình nhóm cùng ngày
    d["_base"] = d.groupby(["time", "sector_group"])[ret_col].transform("mean")
    d["_exc"] = d[ret_col] - d["_base"]

    rows = []
    for rank_name, col in RANK_FACTORS:
        if rank_name not in d.columns:
            continue
        sub = d.dropna(subset=[rank_name])
        top = sub[sub[rank_name] >= RANK_TOP]["_exc"]
        bot = sub[sub[rank_name] <= RANK_BOT]["_exc"]
        if len(top) < 500 or len(bot) < 500:
            continue
        rows.append({
            "factor":        rank_name,
            "n_top":         len(top),
            "n_bot":         len(bot),
            "top_exc_pct":   round(top.mean() * 100, 3),
            "bot_exc_pct":   round(bot.mean() * 100, 3),
            "gap_pct":       round((top.mean() - bot.mean()) * 100, 3),
            "hit_top":       round((top > 0).mean(), 3),
            "hit_bot":       round((bot > 0).mean(), 3),
        })
    out = pd.DataFrame(rows)
    if len(out):
        out = out.reindex(out["gap_pct"].abs().sort_values(ascending=False).index)
    return out.reset_index(drop=True)


def walkforward_sector_ranks(df: pd.DataFrame, horizon: int,
                             n_periods: int = 12) -> pd.DataFrame:
    """Kiểm ngoài mẫu: chia thời gian thành các kỳ ~1 tháng, đo gap của
    từng factor ở TỪNG kỳ. Factor thật sẽ dương ở đa số kỳ; factor khớp
    nhiễu sẽ nhảy dấu loạn xạ (bài học walk-forward caps 23/07)."""
    d = _prepare_sector_ranks(df)
    if d is None:
        return pd.DataFrame()

    ret_col = f"ret_{horizon}d"
    if ret_col not in d.columns:
        return pd.DataFrame()
    d = d.dropna(subset=[ret_col]).copy()
    if not len(d):
        return pd.DataFrame()

    d["_base"] = d.groupby(["time", "sector_group"])[ret_col].transform("mean")
    d["_exc"] = d[ret_col] - d["_base"]
    d["_period"] = pd.to_datetime(d["time"]).dt.to_period("M").astype(str)
    periods = sorted(d["_period"].unique())[-n_periods:]

    rows = []
    for rank_name, _ in RANK_FACTORS:
        if rank_name not in d.columns:
            continue
        gaps = []
        for p in periods:
            sub = d[(d["_period"] == p)].dropna(subset=[rank_name])
            top = sub[sub[rank_name] >= RANK_TOP]["_exc"]
            bot = sub[sub[rank_name] <= RANK_BOT]["_exc"]
            if len(top) < 100 or len(bot) < 100:
                continue
            gaps.append((top.mean() - bot.mean()) * 100)
        if len(gaps) < 6:
            continue
        pos = sum(1 for g in gaps if g > 0)
        rows.append({
            "factor":       rank_name,
            "n_periods":    len(gaps),
            "pos_periods":  pos,
            "pos_rate":     round(pos / len(gaps), 3),
            "mean_gap_pct": round(float(np.mean(gaps)), 3),
            "median_gap":   round(float(np.median(gaps)), 3),
            "std_gap":      round(float(np.std(gaps)), 3),
            "min_gap":      round(float(np.min(gaps)), 3),
            "max_gap":      round(float(np.max(gaps)), 3),
        })
    out = pd.DataFrame(rows)
    if len(out):
        out = out.sort_values("mean_gap_pct", ascending=False)
    return out.reset_index(drop=True)


def run_sector_audit(horizon: int):
    df = load_dataset()
    log.info(f"\n{'═'*64}")
    log.info(f"SECTOR-RANK AUDIT — horizon={horizon}d")
    log.info(f"{'═'*64}")
    log.info("  Xếp hạng CẮT NGANG trong nhóm ngành, đo bằng lợi suất vượt")
    log.info("  TRUNG BÌNH NHÓM cùng ngày (triệt tiêu hiệu ứng ngành + thị trường)")

    t4 = audit_sector_ranks(df, horizon)
    if not len(t4):
        log.warning("  Không đủ dữ liệu cho audit theo ngành")
        return
    log.info(f"\n── [4] SECTOR RANK: top30% vs bot30% (toàn mẫu) ──")
    log.info("\n" + t4.to_string(index=False))

    t5 = walkforward_sector_ranks(df, horizon)
    log.info(f"\n── [5] WALK-FORWARD theo tháng (kiểm ngoài mẫu) ──")
    log.info("   pos_rate = tỷ lệ kỳ có gap dương. Factor thật: >=0.70")
    if len(t5):
        log.info("\n" + t5.to_string(index=False))

    reports = BT_OUTPUT_DIR / "reports"
    reports.mkdir(parents=True, exist_ok=True)
    t4.to_csv(reports / f"audit_sector_rank_h{horizon}.csv", index=False)
    if len(t5):
        t5.to_csv(reports / f"audit_sector_wf_h{horizon}.csv", index=False)
    log.info(f"\nSaved sector audit CSVs → {reports}")

    log.info(f"\n── VERDICT SECTOR-RANK (horizon={horizon}d) ──")
    best = t4.iloc[0]
    log.info(f"  Gap lớn nhất: {best['factor']} = {best['gap_pct']:+.2f}% "
             f"(hit_top={best['hit_top']:.3f}, n={best['n_top']:,})")
    if len(t5):
        stable = t5[(t5["pos_rate"] >= 0.70) & (t5["mean_gap_pct"] > 0.10)]
        if len(stable):
            log.info(f"  ✓ BỀN qua walk-forward: "
                     f"{', '.join(stable['factor'].tolist())}")
            for _, r in stable.iterrows():
                log.info(f"      {r['factor']}: gap TB {r['mean_gap_pct']:+.2f}%, "
                         f"dương {r['pos_periods']}/{r['n_periods']} kỳ")
        else:
            log.info("  ⚠️ KHÔNG factor nào bền (pos_rate>=0.70 & gap>0.10%)")
            log.info("     → xếp hạng ngành cũng KHÔNG có edge ngoài mẫu")


# ══════════════════════════════════════════════════════════════════════
# AUDIT THANH KHOẢN (ADTV) — thêm 23/07/2026
# ══════════════════════════════════════════════════════════════════════
# BỐI CẢNH: 35 phép thử (7 factor × 5 khung) cho thấy ràng buộc thật KHÔNG
# phải "thiếu factor tốt" mà là BIÊN LÃI QUÁ NHỎ SO VỚI CHI PHÍ:
#   - mọi gap đo được 0.2-1.0%, chi phí vòng VN ~0.3-0.5%
#   - kéo dài khung KHÔNG cứu được (gap tăng dưới tuyến tính: 1.72x rồi 1.21x)
#
# GIẢ THUYẾT (đăng ký trước, KHÔNG quét biến thể):
#   Mã thanh khoản thấp có chi phí hiệu dụng cao hơn nhiều do trượt giá.
#   Nếu lọc chỉ giữ nhóm thanh khoản cao, gap phải RỘNG HƠN ĐÁNG KỂ.
#
# TIÊU CHÍ ĐẠT (cả 2, đăng ký trước):
#   (1) gap nhóm thanh khoản CAO >= 1.5 x gap toàn rổ
#   (2) >= 9/12 kỳ dương trong nhóm thanh khoản cao
#   Trượt => DỪNG, không thử ngưỡng khác.
#
# FACTOR KIỂM:
#   - trend_rank: giả thuyết GỐC (đã đăng ký từ đầu)
#   - adx_rank:   THĂM DÒ (hậu nghiệm, chọn từ 35 phép thử → độ tin thấp,
#                 báo cáo riêng, KHÔNG dùng để ra quyết định)

ADTV_WINDOW = 20        # phiên, tính giá trị giao dịch bình quân
LIQ_PRIMARY = "trend_rank"
LIQ_EXPLORATORY = "adx_rank"


def _add_adtv_tiers(d: pd.DataFrame) -> pd.DataFrame | None:
    """Thêm adtv (bình quân 20 phiên) + liq_tier (CAO/GIUA/THAP theo tam phân
    vị CẮT NGANG mỗi ngày). Cắt ngang theo ngày → tier ổn định qua thời gian,
    không bị lệch do thanh khoản toàn thị trường thay đổi."""
    if not {"volume", "close"}.issubset(d.columns):
        log.warning("Dataset thiếu volume/close — bỏ qua audit thanh khoản")
        return None

    d = d.sort_values(["symbol", "time"]).copy()
    d["_turnover"] = d["volume"] * d["close"]
    d["adtv"] = (d.groupby("symbol")["_turnover"]
                   .transform(lambda x: x.rolling(ADTV_WINDOW, min_periods=10).mean()))
    d = d.dropna(subset=["adtv"])
    if not len(d):
        return None

    # Tam phân vị cắt ngang theo từng ngày
    d["_adtv_pct"] = d.groupby("time")["adtv"].rank(pct=True, method="average")
    d["liq_tier"] = pd.cut(d["_adtv_pct"], bins=[0, 1/3, 2/3, 1.0],
                           labels=["THAP", "GIUA", "CAO"], include_lowest=True)
    return d


def audit_liquidity(df: pd.DataFrame, horizon: int) -> pd.DataFrame:
    """Gap của sector-rank TRONG TỪNG nhóm thanh khoản.
    Benchmark giữ nguyên: lợi suất vượt trung bình (ngày, nhóm ngành) tính
    trên TOÀN rổ — để so sánh được với các lần đo trước."""
    d = _prepare_sector_ranks(df)
    if d is None:
        return pd.DataFrame()
    d = _add_adtv_tiers(d)
    if d is None:
        return pd.DataFrame()

    ret_col = f"ret_{horizon}d"
    if ret_col not in d.columns:
        return pd.DataFrame()
    d = d.dropna(subset=[ret_col])
    if not len(d):
        return pd.DataFrame()

    d["_base"] = d.groupby(["time", "sector_group"])[ret_col].transform("mean")
    d["_exc"] = d[ret_col] - d["_base"]

    rows = []
    for factor in (LIQ_PRIMARY, LIQ_EXPLORATORY):
        if factor not in d.columns:
            continue
        for tier in ("TOAN_RO", "CAO", "GIUA", "THAP"):
            sub = d if tier == "TOAN_RO" else d[d["liq_tier"] == tier]
            sub = sub.dropna(subset=[factor])
            top = sub[sub[factor] >= RANK_TOP]["_exc"]
            bot = sub[sub[factor] <= RANK_BOT]["_exc"]
            if len(top) < 300 or len(bot) < 300:
                continue
            adtv_med = sub["adtv"].median() / 1e9
            rows.append({
                "factor":      factor,
                "tier":        tier,
                "adtv_med_ty": round(adtv_med, 2),
                "n_top":       len(top),
                "top_exc_pct": round(top.mean() * 100, 3),
                "bot_exc_pct": round(bot.mean() * 100, 3),
                "gap_pct":     round((top.mean() - bot.mean()) * 100, 3),
                "hit_top":     round((top > 0).mean(), 3),
                "hit_bot":     round((bot > 0).mean(), 3),
            })
    return pd.DataFrame(rows)


def walkforward_liquidity(df: pd.DataFrame, horizon: int,
                          n_periods: int = 12) -> pd.DataFrame:
    """Walk-forward theo tháng, riêng cho nhóm thanh khoản CAO."""
    d = _prepare_sector_ranks(df)
    if d is None:
        return pd.DataFrame()
    d = _add_adtv_tiers(d)
    if d is None:
        return pd.DataFrame()

    ret_col = f"ret_{horizon}d"
    if ret_col not in d.columns:
        return pd.DataFrame()
    d = d.dropna(subset=[ret_col]).copy()
    d["_base"] = d.groupby(["time", "sector_group"])[ret_col].transform("mean")
    d["_exc"] = d[ret_col] - d["_base"]
    d["_period"] = pd.to_datetime(d["time"]).dt.to_period("M").astype(str)
    periods = sorted(d["_period"].unique())[-n_periods:]

    rows = []
    for factor in (LIQ_PRIMARY, LIQ_EXPLORATORY):
        if factor not in d.columns:
            continue
        for tier in ("TOAN_RO", "CAO"):
            gaps = []
            for p in periods:
                sub = d[d["_period"] == p]
                if tier != "TOAN_RO":
                    sub = sub[sub["liq_tier"] == tier]
                sub = sub.dropna(subset=[factor])
                top = sub[sub[factor] >= RANK_TOP]["_exc"]
                bot = sub[sub[factor] <= RANK_BOT]["_exc"]
                if len(top) < 50 or len(bot) < 50:
                    continue
                gaps.append((top.mean() - bot.mean()) * 100)
            if len(gaps) < 6:
                continue
            pos = sum(1 for g in gaps if g > 0)
            rows.append({
                "factor":       factor,
                "tier":         tier,
                "n_periods":    len(gaps),
                "pos_periods":  pos,
                "pos_rate":     round(pos / len(gaps), 3),
                "mean_gap_pct": round(float(np.mean(gaps)), 3),
                "median_gap":   round(float(np.median(gaps)), 3),
                "std_gap":      round(float(np.std(gaps)), 3),
            })
    return pd.DataFrame(rows)


def run_liquidity_audit(horizon: int):
    df = load_dataset()
    log.info(f"\n{'═'*64}")
    log.info(f"LIQUIDITY (ADTV) AUDIT — horizon={horizon}d")
    log.info(f"{'═'*64}")
    log.info(f"  Tam phân vị ADTV {ADTV_WINDOW} phiên, cắt ngang theo NGÀY")
    log.info(f"  Giả thuyết: lọc thanh khoản cao → gap RỘNG HƠN >= 1.5 lần")

    t6 = audit_liquidity(df, horizon)
    if not len(t6):
        log.warning("  Không đủ dữ liệu cho audit thanh khoản")
        return
    log.info(f"\n── [6] GAP THEO NHÓM THANH KHOẢN (toàn mẫu) ──")
    log.info("\n" + t6.to_string(index=False))

    t7 = walkforward_liquidity(df, horizon)
    log.info(f"\n── [7] WALK-FORWARD nhóm thanh khoản CAO ──")
    if len(t7):
        log.info("\n" + t7.to_string(index=False))

    reports = BT_OUTPUT_DIR / "reports"
    reports.mkdir(parents=True, exist_ok=True)
    t6.to_csv(reports / f"audit_liquidity_h{horizon}.csv", index=False)
    if len(t7):
        t7.to_csv(reports / f"audit_liquidity_wf_h{horizon}.csv", index=False)
    log.info(f"\nSaved liquidity CSVs → {reports}")

    # ── VERDICT theo tiêu chí ĐĂNG KÝ TRƯỚC ──
    log.info(f"\n── VERDICT THANH KHOẢN (horizon={horizon}d) ──")
    for factor, tag in ((LIQ_PRIMARY, "CHÍNH (đăng ký trước)"),
                        (LIQ_EXPLORATORY, "THĂM DÒ (hậu nghiệm — độ tin THẤP)")):
        f6 = t6[t6["factor"] == factor]
        all_row = f6[f6["tier"] == "TOAN_RO"]
        cao_row = f6[f6["tier"] == "CAO"]
        if not len(all_row) or not len(cao_row):
            continue
        g_all = float(all_row.iloc[0]["gap_pct"])
        g_cao = float(cao_row.iloc[0]["gap_pct"])
        ratio = g_cao / g_all if g_all != 0 else float("nan")
        wf = t7[(t7["factor"] == factor) & (t7["tier"] == "CAO")]
        pos = int(wf.iloc[0]["pos_periods"]) if len(wf) else 0
        npd = int(wf.iloc[0]["n_periods"]) if len(wf) else 0

        c1 = ratio >= 1.5
        c2 = (pos >= 9)
        log.info(f"  [{tag}] {factor}:")
        log.info(f"    gap toàn rổ {g_all:+.3f}% → thanh khoản CAO {g_cao:+.3f}% "
                 f"(tỷ lệ {ratio:.2f}x) — ĐK1 (>=1.5x): {'ĐẠT' if c1 else 'TRƯỢT'}")
        log.info(f"    kỳ dương {pos}/{npd} — ĐK2 (>=9/12): "
                 f"{'ĐẠT' if c2 else 'TRƯỢT'}")
        if factor == LIQ_PRIMARY:
            if c1 and c2:
                log.info(f"    ✓ ĐẠT CẢ 2 → cổng thanh khoản có giá trị")
                log.info(f"    Kinh tế: mua nhóm đầu thu {cao_row.iloc[0]['top_exc_pct']:+.3f}% "
                         f"| chi phí vòng ~0.30-0.50%")
            else:
                log.info(f"    ✗ TRƯỢT → theo luật đăng ký trước: DỪNG, "
                         f"không thử ngưỡng khác")


def main():
    parser = argparse.ArgumentParser(description="Audit từng indicator đơn lẻ")
    parser.add_argument("--horizon", type=int, default=5,
                        choices=[1, 3, 5, 10, 20])
    parser.add_argument("--all-horizons", action="store_true")
    parser.add_argument("--sector", action="store_true",
                        help="Chạy THÊM audit xếp hạng trong nhóm ngành")
    parser.add_argument("--sector-only", action="store_true",
                        help="CHỈ chạy audit theo ngành (bỏ 3 audit cũ)")
    parser.add_argument("--liquidity-only", action="store_true",
                        help="CHỈ chạy audit thanh khoản ADTV")
    args = parser.parse_args()

    horizons = [1, 3, 5, 10, 20] if args.all_horizons else [args.horizon]
    for h in horizons:
        if not args.sector_only and not args.liquidity_only:
            run_audit(h)
        if args.sector or args.sector_only:
            run_sector_audit(h)
        if args.liquidity_only:
            run_liquidity_audit(h)


if __name__ == "__main__":
    main()
