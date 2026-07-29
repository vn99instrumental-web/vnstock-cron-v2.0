"""
scripts/diag_mr_survival_v2f.py — MR SURVIVAL CHECK trên universe V2F
=======================================================================
MỤC ĐÍCH (#1 trong review logic V3):
  Nền tảng của scoring V3 (registry 04/07) đặt cược nặng vào MEAN-REVERSION
  ở khung trade (weight MR = 0.30, nặng nhất). Nhưng phát hiện thị trường
  ngày 23/07 (toàn 422 mã) kết luận MR có edge ÂM, trend edge DƯƠNG, và edge
  chỉ sống ở mã KÉM thanh khoản.

  Câu hỏi sống-còn: trên RIÊNG universe V2F (thanh khoản cao — proxy = tier
  ADTV cao), 4 tín hiệu MR của V3 còn IC dương không? Nếu chết → nền tảng V3
  sai hướng, cần registry v2.

HAI NGUỒN (cách C — đã chốt với chủ dự án):
  PART A — backtest_output/dataset.parquet (đủ dày → KẾT LUẬN được HÔM NAY).
           Đây là "confirm 1 giả thuyết đã có", KHÔNG phải fishing test mới,
           nên không vi phạm rule #3 (chống false-positive khi tìm edge MỚI).
  PART B — sổ forward v3 (output/history/v2f_predictions_v3/*.jsonl).
           Out-of-sample thật, nhưng shadow mới chạy từ 04/07 → còn mỏng →
           mọi verdict Part B gắn INDICATIVE tới khi đủ MIN_DAYS_CONCLUSIVE.

ISOLATION (kỷ luật tuyệt đối — mirror diag_signal_ic.py):
  ✗ KHÔNG import utils/, steps/, config.py
  ✗ KHÔNG ghi vào output/ production
  ✓ Chỉ đọc : dataset.parquet + output/history/v2f_predictions_v3/*.jsonl
  ✓ Chỉ ghi : backtest_output/reports/mr_survival_{YYYYMMDD}.json

UNIVERSE V2F = tier ADTV CAO (tam phân vị trên, cắt ngang theo NGÀY) — proxy
  đã dùng trong bt_audit.py mode liquidity ngày 23/07 → nhất quán evidence cũ.

METRIC:
  sig_value được định hướng sao cho CAO = kỳ vọng forward return CAO
  (tức: IC DƯƠNG = tín hiệu ĐÚNG). Cụ thể MR = fade cực đoan:
    willr_mr   : sig = -willr_14            (quá bán → cao → bullish)
    bb_mr      : sig = -bb_position         (sát band dưới → cao → bullish)
    overext_mr : sig = -price_vs_ema200_pct (dưới EMA200 → cao → fade lên)
    rs_rev_mr  : sig = -rs_20d              (underperform → cao → fade lên)
  ĐỐI CHỨNG (trend, xác nhận phát hiện 23/07):
    trend_mom  : sig = +return_20d_pct      (IC dương = trend còn sống)

  IC   = mean daily cross-sectional Spearman(sig, ret_5d) trên tier CAO
  t    = mean(IC_daily) / std(IC_daily) * sqrt(n_days)   (ICIR-style)

TIÊU CHÍ VERDICT — ĐĂNG KÝ TRƯỚC (rule #1, #2), hard-code, KHÔNG sửa sau khi thấy số:
  Time-split hold-out: chia dải thời gian làm ĐÔI theo ngày.
    ALIVE  : IC_5d > 0 VÀ |t| >= IC_T_MIN ở CẢ HAI nửa
    DEAD   : IC_5d <= 0 ở toàn mẫu, HOẶC đảo dấu (âm) ở nửa SAU
    WEAK   : còn lại (dấu đúng nhưng |t| yếu / không nhất quán 2 nửa)
  Kinh tế (rule #4): gap = mean ret_5d(quintile bullish nhất) - (kém nhất).
    EXPLOITABLE nếu |gap| > chi phí vòng (0.30-0.50%); nếu không → "no edge".

TRIGGER: debug.yml → script = scripts/diag_mr_survival_v2f.py
YÊU CẦU: dataset.parquet đã build (bt_data.py). Nếu quá cũ, Part B (forward)
         sẽ thiếu giá tương lai cho pred gần đây → tự báo & giảm mẫu.

CHANGELOG:
  v1 (2026-07-29) — initial, phục vụ review logic V3 mục #1.
"""
import os
import sys
import json
import math
import glob
import logging
from datetime import datetime
from pathlib import Path

# ── Isolation guard: KHÔNG cho production modules lọt vào ──────────────
for _mod in list(sys.modules.keys()):
    if _mod.startswith(("utils.", "steps.")) or _mod == "config":
        raise RuntimeError(f"ISOLATION VIOLATION: {_mod} đã được import — "
                           "diag không được đụng production modules.")

import numpy as np
import pandas as pd

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(message)s",
                    datefmt="%H:%M:%S")
log = logging.getLogger(__name__)

REPO_ROOT  = Path(__file__).resolve().parent.parent
BT_DIR     = REPO_ROOT / "backtest_output"
REPORT_DIR = BT_DIR / "reports"
PARQUET    = BT_DIR / "dataset.parquet"
LEDGER_DIR = REPO_ROOT / "output" / "history" / "v2f_predictions_v3"

# ══════════════════════════════════════════════════════════════════════
# THAM SỐ ĐĂNG KÝ TRƯỚC — KHÔNG sửa sau khi đã nhìn thấy kết quả
# ══════════════════════════════════════════════════════════════════════
HORIZON_PRIMARY   = 5      # khung trade
HORIZON_HOLD      = 10     # tham chiếu khung hold (chỉ report, không verdict)
ADTV_WINDOW       = 20     # phiên tính ADTV
HIGH_TIER_Q       = 2 / 3  # tier CAO = ADTV >= phân vị 66.7% trong NGÀY
MIN_SYM_TIER      = 15     # tối thiểu mã tier CAO/ngày mới tính 1 IC daily
IC_T_MIN          = 2.0    # |t| tối thiểu để coi có ý nghĩa
MIN_DAYS_CONCLUSIVE = 60   # < ngưỡng này → verdict INDICATIVE
COST_RT_LOW       = 0.30   # % chi phí vòng (round-trip) — cận dưới
COST_RT_HIGH      = 0.50   # % — cận trên
COST_RT_MID       = 0.40   # % — midpoint để tính net

# 4 tín hiệu MR của V3 + 1 đối chứng trend. exp_sign luôn = +1 vì sig đã
# được định hướng "cao = bullish" (IC dương = tín hiệu đúng).
MR_SIGNALS = ["willr_mr", "bb_mr", "overext_mr", "rs_rev_mr"]
CONTROL    = ["trend_mom"]
ALL_SIGS   = MR_SIGNALS + CONTROL


# ══════════════════════════════════════════════════════════════════════
# HELPERS — thống kê
# ══════════════════════════════════════════════════════════════════════

def _spearman(x: np.ndarray, y: np.ndarray) -> float:
    """Spearman = Pearson trên rank. Guard mẫu ngắn / hằng số."""
    if len(x) < 3:
        return np.nan
    rx = pd.Series(x).rank().to_numpy()
    ry = pd.Series(y).rank().to_numpy()
    if np.std(rx) == 0 or np.std(ry) == 0:
        return np.nan
    return float(np.corrcoef(rx, ry)[0, 1])


def daily_cs_ic(df: pd.DataFrame, sig_col: str, ret_col: str,
                exclude_zero: bool = False, min_sym: int = MIN_SYM_TIER) -> dict:
    """Mean daily cross-sectional Spearman IC + t-stat trên df ĐÃ LỌC tier.

    df cần cột: date, <sig_col>, <ret_col>. Trả series=[(date, ic)] cho split.
    exclude_zero=True: bỏ obs sig==0 (dùng cho điểm nguyên s_* của sổ forward,
    vì 0 = "không bắn", đưa vào rank sẽ pha loãng IC về 0 một cách cơ học).
    """
    series = []
    n_obs_total = 0
    for date, g in df.groupby("date"):
        sub = g[[sig_col, ret_col]].dropna()
        if exclude_zero:
            sub = sub[sub[sig_col] != 0]
        if len(sub) < min_sym:
            continue
        ic = _spearman(sub[sig_col].to_numpy(), sub[ret_col].to_numpy())
        if not np.isnan(ic):
            series.append((date, ic))
            n_obs_total += len(sub)
    if not series:
        return {"ic": np.nan, "t": np.nan, "n_days": 0, "n_obs": 0, "series": []}
    ics = np.array([v for _, v in series])
    ic_mean = float(ics.mean())
    ic_std = float(ics.std(ddof=1)) if len(ics) > 1 else np.nan
    t = (ic_mean / ic_std * math.sqrt(len(ics))) if ic_std and ic_std > 0 else np.nan
    return {"ic": ic_mean, "t": t, "n_days": len(ics),
            "n_obs": n_obs_total, "series": series}


def time_split(series: list) -> dict:
    """Chia series [(date, ic)] làm đôi theo THỜI GIAN, trả IC+t mỗi nửa."""
    if len(series) < 4:
        return {"h1": None, "h2": None}
    ss = sorted(series, key=lambda kv: kv[0])
    mid = len(ss) // 2
    out = {}
    for name, part in (("h1", ss[:mid]), ("h2", ss[mid:])):
        ics = np.array([v for _, v in part])
        m = float(ics.mean())
        sd = float(ics.std(ddof=1)) if len(ics) > 1 else np.nan
        t = (m / sd * math.sqrt(len(ics))) if sd and sd > 0 else np.nan
        out[name] = {"ic": m, "t": t, "n_days": len(ics),
                     "date_min": str(part[0][0]), "date_max": str(part[-1][0])}
    return out


def quintile_gap(df: pd.DataFrame, sig_col: str, ret_col: str,
                 min_sym: int = MIN_SYM_TIER) -> dict:
    """Gap = mean ret(top 20% sig) - mean ret(bottom 20% sig), trung bình theo
    ngày. sig đã định hướng cao=bullish → gap DƯƠNG = tín hiệu tạo được tiền."""
    gaps = []
    for date, g in df.groupby("date"):
        sub = g[[sig_col, ret_col]].dropna()
        if len(sub) < min_sym:
            continue
        sub = sub.sort_values(sig_col)
        k = max(1, int(len(sub) * 0.2))
        bottom = sub.head(k)[ret_col].mean()   # sig thấp nhất = bearish nhất
        top = sub.tail(k)[ret_col].mean()       # sig cao nhất = bullish nhất
        gaps.append(top - bottom)
    if not gaps:
        return {"gap": np.nan, "n_days": 0}
    return {"gap": float(np.mean(gaps)), "n_days": len(gaps)}


# ══════════════════════════════════════════════════════════════════════
# INDICATORS — tự tính từ OHLCV (self-contained, không phụ thuộc cột parquet)
# ══════════════════════════════════════════════════════════════════════

def compute_indicators(g: pd.DataFrame) -> pd.DataFrame:
    """1 symbol, đã sort theo time. Tính đúng công thức production V3."""
    g = g.sort_values("time").copy()
    c, h, l, v = g["close"], g["high"], g["low"], g["volume"]

    # Williams %R 14
    hh = h.rolling(14).max()
    ll = l.rolling(14).min()
    rng = (hh - ll).replace(0, np.nan)
    g["willr_14"] = -100 * (hh - c) / rng

    # Bollinger position (20, 2std)
    mid = c.rolling(20).mean()
    sd = c.rolling(20).std(ddof=0)
    upper = mid + 2 * sd
    lower = mid - 2 * sd
    width = (upper - lower).replace(0, np.nan)
    g["bb_position"] = (c - lower) / width

    # price_vs_ema200_pct  (EMA200 chuẩn, cần ~200 bar → NaN đầu chuỗi)
    ema200 = c.ewm(span=200, adjust=False, min_periods=200).mean()
    g["price_vs_ema200_pct"] = (c - ema200) / ema200 * 100

    # return 20d (%)  — dùng cho rs_reversal + trend control
    g["return_20d_pct"] = (c / c.shift(20) - 1) * 100

    # forward returns
    g[f"ret_{HORIZON_PRIMARY}d"] = (c.shift(-HORIZON_PRIMARY) / c - 1) * 100
    g[f"ret_{HORIZON_HOLD}d"]    = (c.shift(-HORIZON_HOLD) / c - 1) * 100

    # ADTV (giá trị giao dịch TB, đơn vị = close*volume)
    g["adtv"] = (c * v).rolling(ADTV_WINDOW).mean()
    return g


def build_signals(df: pd.DataFrame) -> pd.DataFrame:
    """Định hướng mọi sig sao cho CAO = bullish (IC dương = tín hiệu đúng).
    rs_20d dùng median return_20d của TOÀN universe/ngày làm proxy 'thị trường'
    (thay VNINDEX — không có trong parquet per-symbol)."""
    df = df.copy()
    mkt = df.groupby("date")["return_20d_pct"].transform("median")
    rs = (1 + df["return_20d_pct"] / 100) / (1 + mkt / 100)

    df["willr_mr"]   = -df["willr_14"]
    df["bb_mr"]      = -df["bb_position"]
    df["overext_mr"] = -df["price_vs_ema200_pct"]
    df["rs_rev_mr"]  = -rs
    df["trend_mom"]  = df["return_20d_pct"]      # đối chứng: cao=trend tiếp diễn
    return df


def tag_high_tier(df: pd.DataFrame) -> pd.DataFrame:
    """Gắn cờ tier ADTV CAO theo tam phân vị TRONG NGÀY."""
    df = df.copy()
    thr = df.groupby("date")["adtv"].transform(
        lambda s: s.quantile(HIGH_TIER_Q))
    df["is_high_tier"] = df["adtv"] >= thr
    return df


# ══════════════════════════════════════════════════════════════════════
# VERDICT — theo tiêu chí ĐĂNG KÝ TRƯỚC
# ══════════════════════════════════════════════════════════════════════

def verdict(full_ic: float, split: dict, n_days: int) -> str:
    h1, h2 = split.get("h1"), split.get("h2")
    if n_days < 4 or h1 is None or h2 is None:
        return "INSUFFICIENT"
    both_pos = (h1["ic"] > 0 and h2["ic"] > 0)
    both_sig = (abs(h1["t"]) >= IC_T_MIN and abs(h2["t"]) >= IC_T_MIN
                if not (np.isnan(h1["t"]) or np.isnan(h2["t"])) else False)
    if full_ic <= 0 or h2["ic"] < 0:
        return "DEAD"
    if both_pos and both_sig:
        return "ALIVE"
    return "WEAK"


def econ_tag(gap: float) -> str:
    if np.isnan(gap):
        return "n/a"
    if abs(gap) <= COST_RT_HIGH:
        return f"NO EDGE (gap {gap:+.3f}% <= chi phí {COST_RT_LOW}-{COST_RT_HIGH}%)"
    net = abs(gap) - COST_RT_MID
    return f"EXPLOITABLE? gap {gap:+.3f}% | net sau phí ~{net:+.3f}%"


# ══════════════════════════════════════════════════════════════════════
# PART A — backtest (kết luận được)
# ══════════════════════════════════════════════════════════════════════

def run_part_a(report: dict) -> pd.DataFrame:
    if not PARQUET.exists():
        log.error(f"❌ {PARQUET} không tồn tại — chạy bt_data.py trước. SKIP Part A.")
        report["part_a"] = {"error": "dataset.parquet missing"}
        return pd.DataFrame()

    df = pd.read_parquet(PARQUET)
    if "time" not in df.columns or "symbol" not in df.columns:
        log.error("❌ parquet thiếu cột time/symbol. SKIP.")
        report["part_a"] = {"error": "parquet missing time/symbol"}
        return pd.DataFrame()
    need = {"open", "high", "low", "close", "volume"}
    if not need.issubset(df.columns):
        log.error(f"❌ parquet thiếu OHLCV {need - set(df.columns)}. SKIP.")
        report["part_a"] = {"error": "parquet missing OHLCV"}
        return pd.DataFrame()

    df["time"] = pd.to_datetime(df["time"])
    log.info(f"[A] parquet: {len(df):,} rows, {df['symbol'].nunique()} mã, "
             f"{df['time'].min().date()} → {df['time'].max().date()}")

    parts = [compute_indicators(g) for _, g in df.groupby("symbol")]
    df = pd.concat(parts, ignore_index=True)
    df["date"] = df["time"].dt.strftime("%Y-%m-%d")
    df = build_signals(df)
    df = tag_high_tier(df)

    hi = df[df["is_high_tier"]].copy()
    log.info(f"[A] tier CAO (ADTV top {HIGH_TIER_Q:.0%}): {len(hi):,} obs, "
             f"{hi['date'].nunique()} ngày")

    ret_col = f"ret_{HORIZON_PRIMARY}d"
    rows = []
    log.info(f"\n{'═'*92}")
    log.info(f"  PART A — IC {HORIZON_PRIMARY}d trên tier THANH KHOẢN CAO (proxy V2F)")
    log.info(f"{'═'*92}")
    log.info(f"{'signal':<12}{'IC_5d':>9}{'t':>7}{'|':>3}"
             f"{'IC_h1':>9}{'t_h1':>7}{'IC_h2':>9}{'t_h2':>7}"
             f"{'  gap%':>8}{'  n_d':>6}  verdict")
    log.info("─" * 92)
    for sig in ALL_SIGS:
        r = daily_cs_ic(hi, sig, ret_col, exclude_zero=False)
        sp = time_split(r["series"])
        vd = verdict(r["ic"], sp, r["n_days"])
        gp = quintile_gap(hi, sig, ret_col)
        h1 = sp.get("h1") or {"ic": np.nan, "t": np.nan}
        h2 = sp.get("h2") or {"ic": np.nan, "t": np.nan}
        tag = "MR" if sig in MR_SIGNALS else "TREND"
        rows.append({
            "signal": sig, "family": tag,
            "ic_5d": r["ic"], "t_5d": r["t"], "n_days": r["n_days"],
            "n_obs": r["n_obs"],
            "ic_h1": h1["ic"], "t_h1": h1["t"],
            "ic_h2": h2["ic"], "t_h2": h2["t"],
            "gap_pct": gp["gap"], "verdict": vd, "econ": econ_tag(gp["gap"]),
        })
        log.info(f"{sig:<12}{r['ic']:>+9.4f}{r['t']:>+7.2f}{'|':>3}"
                 f"{h1['ic']:>+9.4f}{h1['t']:>+7.2f}"
                 f"{h2['ic']:>+9.4f}{h2['t']:>+7.2f}"
                 f"{gp['gap']:>+8.3f}{r['n_days']:>6}  {vd}")
    log.info("─" * 92)
    for row in rows:
        log.info(f"  {row['signal']:<12} {row['econ']}")

    report["part_a"] = {
        "meta": {"rows": int(len(df)), "high_tier_obs": int(len(hi)),
                 "n_days": int(hi["date"].nunique()),
                 "date_min": str(df["time"].min().date()),
                 "date_max": str(df["time"].max().date()),
                 "horizon": HORIZON_PRIMARY, "adtv_window": ADTV_WINDOW},
        "signals": rows,
    }
    return df   # trả về để Part B join forward return


# ══════════════════════════════════════════════════════════════════════
# PART B — sổ forward v3 (INDICATIVE)
# ══════════════════════════════════════════════════════════════════════

_LEDGER_SIG_MAP = {   # tên field trong sổ ↔ tín hiệu MR
    "willr_mr":   "s_willr_mr",
    "bb_mr":      "s_bb_mr",
    "overext_mr": "s_overext_ema",
    "rs_rev_mr":  "s_rs_reversal",
}


def run_part_b(report: dict, df_bt: pd.DataFrame) -> None:
    files = sorted(glob.glob(str(LEDGER_DIR / "*.jsonl")))
    if not files:
        log.info(f"[B] Sổ forward v3 chưa có ({LEDGER_DIR}) — SKIP (bình thường "
                 "nếu shadow chưa ghi record nào).")
        report["part_b"] = {"error": "ledger empty"}
        return
    if df_bt is None or df_bt.empty:
        log.info("[B] Không có parquet để join forward return — SKIP Part B.")
        report["part_b"] = {"error": "no parquet for forward return"}
        return

    # Bảng tra forward return từ parquet: (symbol, date) → ret_5d
    ret_col = f"ret_{HORIZON_PRIMARY}d"
    ret_lut = {(r.symbol, r.date): getattr(r, ret_col)
               for r in df_bt[["symbol", "date", ret_col]].itertuples(index=False)}

    recs = []
    for fp in files:
        with open(fp, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    recs.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    if not recs:
        report["part_b"] = {"error": "ledger has no valid records"}
        return

    rd = pd.DataFrame(recs)
    keep = ["symbol", "signal_date", "snap_time", "adtv_bil"] + \
           list(_LEDGER_SIG_MAP.values())
    for k in keep:
        if k not in rd.columns:
            rd[k] = np.nan
    rd = rd[keep].copy()

    # 1 obs / (symbol, ngày): lấy snap MUỘN NHẤT trong ngày
    rd = rd.sort_values("snap_time").groupby(
        ["symbol", "signal_date"], as_index=False).last()
    rd["date"] = rd["signal_date"].astype(str)

    # join forward return
    rd["ret"] = [ret_lut.get((s, d), np.nan)
                 for s, d in zip(rd["symbol"], rd["date"])]
    n_before = len(rd)
    rd = rd.dropna(subset=["ret"])
    log.info(f"[B] sổ forward: {n_before} obs (symbol×ngày) → {len(rd)} có "
             f"forward ret_{HORIZON_PRIMARY}d từ parquet")
    if rd.empty:
        log.info("[B] Không obs nào có forward return (parquet có thể quá cũ so "
                 "với ngày record). Rebuild dataset.parquet để Part B chạy.")
        report["part_b"] = {"error": "no matured forward returns",
                            "n_records": n_before}
        return

    # tier CAO theo adtv_bil trong ngày
    thr = rd.groupby("date")["adtv_bil"].transform(
        lambda s: s.quantile(HIGH_TIER_Q))
    hi = rd[rd["adtv_bil"] >= thr].copy()

    rows = []
    log.info(f"\n{'═'*80}")
    log.info(f"  PART B — IC {HORIZON_PRIMARY}d sổ forward v3 (tier CAO) — INDICATIVE")
    log.info(f"{'═'*80}")
    log.info(f"{'signal':<12}{'IC_5d':>9}{'t':>7}{'n_days':>8}{'n_obs':>8}  note")
    log.info("─" * 80)
    for sig, col in _LEDGER_SIG_MAP.items():
        hi[col] = pd.to_numeric(hi[col], errors="coerce")
        r = daily_cs_ic(hi, col, "ret", exclude_zero=True)
        conclusive = r["n_days"] >= MIN_DAYS_CONCLUSIVE
        note = "đủ dày" if conclusive else f"INDICATIVE (<{MIN_DAYS_CONCLUSIVE} ngày)"
        rows.append({"signal": sig, "ledger_field": col,
                     "ic_5d": r["ic"], "t_5d": r["t"], "n_days": r["n_days"],
                     "n_obs": r["n_obs"], "conclusive": conclusive})
        ic_s = f"{r['ic']:>+9.4f}" if not np.isnan(r["ic"]) else f"{'n/a':>9}"
        t_s = f"{r['t']:>+7.2f}" if not np.isnan(r["t"]) else f"{'n/a':>7}"
        log.info(f"{sig:<12}{ic_s}{t_s}{r['n_days']:>8}{r['n_obs']:>8}  {note}")
    log.info("─" * 80)

    report["part_b"] = {
        "meta": {"n_records_symday": int(n_before),
                 "n_matured": int(len(rd)),
                 "high_tier_obs": int(len(hi)),
                 "n_days": int(hi["date"].nunique()),
                 "min_days_conclusive": MIN_DAYS_CONCLUSIVE},
        "signals": rows,
    }


# ══════════════════════════════════════════════════════════════════════
# SUMMARY — kết luận dễ hiểu
# ══════════════════════════════════════════════════════════════════════

def plain_summary(report: dict) -> None:
    a = report.get("part_a", {})
    if "signals" not in a:
        log.info("\n[KẾT LUẬN] Part A không chạy được — không kết luận được.")
        return
    mr = [s for s in a["signals"] if s["family"] == "MR"]
    tr = [s for s in a["signals"] if s["family"] == "TREND"]
    n_alive = sum(1 for s in mr if s["verdict"] == "ALIVE")
    n_dead = sum(1 for s in mr if s["verdict"] == "DEAD")

    log.info(f"\n{'█'*72}")
    log.info("  KẾT LUẬN (dễ hiểu)")
    log.info(f"{'█'*72}")
    log.info(f"  Trên rổ thanh khoản cao (proxy V2F), {len(mr)} tín hiệu MR:")
    log.info(f"    • SỐNG (IC dương, chắc, 2 nửa)  : {n_alive}")
    log.info(f"    • CHẾT (IC âm / đảo dấu nửa sau): {n_dead}")
    log.info(f"    • Còn lại (yếu)                 : {len(mr) - n_alive - n_dead}")
    for s in mr:
        log.info(f"      - {s['signal']:<11} {s['verdict']:<12} "
                 f"IC={s['ic_5d']:+.4f} t={s['t_5d']:+.2f} | {s['econ']}")
    if tr:
        t = tr[0]
        log.info(f"  Đối chứng trend (trend_mom): IC={t['ic_5d']:+.4f} "
                 f"t={t['t_5d']:+.2f} → phát hiện 23/07 "
                 f"{'TÁI LẬP (trend âm/yếu ở tier cao)' if t['ic_5d'] <= 0.02 else 'KHÔNG tái lập (trend dương ở tier cao)'}")
    log.info("")
    if n_alive == 0:
        log.info("  ⇒ NỀN TẢNG V3 SAI HƯỚNG trên V2F: MR không sống. Cần bàn "
                 "registry v2 (giảm/đảo weight MR khung trade).")
    elif n_dead == 0 and n_alive >= 2:
        log.info("  ⇒ NỀN TẢNG V3 CÒN ĐÚNG trên V2F: MR vẫn sống trên rổ liquid "
                 "(khác kết luận 23/07 vì đó là toàn 422 mã). Giữ hướng, chuyển "
                 "sang các fix #2-#4.")
    else:
        log.info("  ⇒ HỖN HỢP: một số MR sống, một số chết. Cần soi từng tín "
                 "hiệu — có thể tỉa bớt tín hiệu MR yếu thay vì đảo cả nhóm.")
    log.info(f"{'█'*72}")


def main():
    log.info("=" * 72)
    log.info("  MR SURVIVAL CHECK trên universe V2F (#1 review logic V3)")
    log.info(f"  Tiêu chí đăng ký trước: |t|>={IC_T_MIN}, split 2 nửa, "
             f"chi phí vòng {COST_RT_LOW}-{COST_RT_HIGH}%")
    log.info("=" * 72)
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    report = {"generated_at": datetime.now().isoformat(timespec="seconds"),
              "registered_params": {
                  "horizon_primary": HORIZON_PRIMARY, "adtv_window": ADTV_WINDOW,
                  "high_tier_q": HIGH_TIER_Q, "ic_t_min": IC_T_MIN,
                  "min_days_conclusive": MIN_DAYS_CONCLUSIVE,
                  "cost_rt_pct": [COST_RT_LOW, COST_RT_HIGH]}}

    df_bt = run_part_a(report)
    run_part_b(report, df_bt)
    plain_summary(report)

    stamp = datetime.now().strftime("%Y%m%d")
    out = REPORT_DIR / f"mr_survival_{stamp}.json"
    with open(out, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2, default=str)
    log.info(f"\nĐã ghi report → {out}")


if __name__ == "__main__":
    main()
