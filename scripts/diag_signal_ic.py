"""
scripts/diag_signal_ic.py — Per-signal IC audit cho V2f scoring v2.3
=====================================================================
MỤC ĐÍCH: Đo Spearman IC (cross-sectional daily) của TỪNG tín hiệu trong
v2f_step_scoring.py để có evidence thiết kế batch v2.4:
  #2 trend cộng tuyến 9 tín hiệu   → intra-group corr matrix
  #8 momentum trộn regime          → cancellation check RSI-block vs MACD
  #9 CMF (mean-rev) vs MFI (TF)    → cancellation check
  #10 FairVal naive                → IC part A
  #11 prop_trade 5d nhiễu          → IC part A

HYBRID 2 NGUỒN:
  PART C — backtest_output/dataset.parquet (~281 mã × 15 tháng):
    * Base TA columns có sẵn (ema/rsi/macd/stoch/cmf/mfi/obv/bb_pos/vol_ratio/
      adx/supertrend/atr_pct) + OHLCV → tự tính extended (linreg, aroon,
      donchian, AD, EFI, WillR, ROC10, NR7, 52W-proxy, RS-proxy).
    * ZERO API call. Score transforms mirror ĐÚNG threshold production v2.3.
    * Tín hiệu chưa rõ threshold production (EFI, WillR, 52W, RS) → đo RAW
      (rank cross-sectional, direction theo quy ước production).
  PART A — git history của output/v2f_signals.json (~130 mã × N phiên v2.3):
    * Các tín hiệu KHÔNG tái tạo được từ giá: ext_prop, ext_insider, ext_room,
      ext_ba, ext_fv, ext_div, ext_eps + group order_flow/depth/ff/smart_money.
    * Forward return join từ close trong dataset.parquet (không fetch).
    * N nhỏ → mọi verdict gắn INDICATIVE.
    * BONUS: bảng order_flow/vol_spike theo snap_time (evidence bias intraday).

ISOLATION (kỷ luật):
  ✗ KHÔNG import utils/, steps/, config.py
  ✗ KHÔNG ghi vào output/ production
  ✓ Chỉ đọc: backtest_output/dataset.parquet + git history (read-only)
  ✓ Chỉ ghi: backtest_output/reports/signal_ic_{YYYYMMDD}.json

METRIC:
  IC = mean của daily cross-sectional Spearman(signal, ret_h) qua các phiên
  t_stat = mean(IC_daily) / std(IC_daily) * sqrt(n_days)   (ICIR-style)
  fire_rate = % obs có score != 0 (transform) hoặc non-NaN (raw)
  sign_bias = mean score, %pos vs %neg  (evidence bất đối xứng #3)

VERDICT RULES (chỉ cho src=C, N_days>=60):
  DEAD   : fire_rate < 1%
  DROP?  : |IC_5d| < 0.005 và |t| < 1.0
  FLIP?  : IC_5d ngược dấu kỳ vọng và |t| >= 2.0
  KEEP   : IC_5d đúng dấu kỳ vọng và |t| >= 2.0
  WEAK   : còn lại
  (src=A luôn = INDICATIVE)

TRIGGER: workflow_dispatch debug.yml → script = scripts/diag_signal_ic.py
YÊU CẦU: backtest_output/dataset.parquet đã build (chạy bt_data.py trước
         nếu chưa có / quá cũ — script sẽ cảnh báo ngày max của parquet).

CHANGELOG:
  v1 (2026-07-03) — initial. Evidence-gathering cho batch v2.4.
  v2 (2026-07-03) — Phase 0 Option C: IC stability theo quý + regime proxy
                    (up/flat/down từ median perf20d universe). Verdict
                    STABLE_POS/STABLE_NEG/UNSTABLE/INSUFFICIENT + gate_hint
                    làm input trực tiếp cho registry v3 & regime gate.
  v3 (2026-07-04) — Regime proxy chuyển từ ngưỡng cứng ±2% sang TERCILE
                    (phân vị 1/3) sau khi run thật cho thấy 301/301 phiên
                    đều rơi vào 'flat'. gate_hint giờ có ý nghĩa thực.
  v4 (2026-07-04) — Thêm horizon 10d/20d (khung HOLD ~1 tháng): ret tự tính
                    từ close, bảng chính thêm IC_10d/IC_20d + verdict kép
                    TRADE(5d)/HOLD(20d), stability chạy cho cả 5d và 20d.
                    Trả lời: tín hiệu TF bị off ở khung trade có sống ở khung
                    hold không → quyết định score_hold trong registry v3.
"""
import os
import sys
import json
import math
import logging
import subprocess
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

# ── Isolation guard: không cho production modules lọt vào ──────────────
for _mod in list(sys.modules.keys()):
    if _mod.startswith(("utils.", "steps.")) or _mod == "config":
        raise RuntimeError(f"ISOLATION VIOLATION: {_mod} đã được import")

REPO_ROOT   = Path(__file__).resolve().parent.parent
BT_DIR      = REPO_ROOT / "backtest_output"
REPORT_DIR  = BT_DIR / "reports"
PARQUET     = BT_DIR / "dataset.parquet"
SIGNALS_GIT = "output/v2f_signals.json"

HORIZONS      = [1, 3, 5, 10, 20]   # 1-5d = khung trade | 10-20d = khung hold
STABILITY_HZS = [5, 20]              # stability theo quý/regime cho 2 khung
MIN_SYM_DAY   = 30    # tối thiểu mã/ngày để tính 1 IC daily (Part C)
MIN_SYM_DAY_A = 30    # Part A (~130 mã → OK)
MIN_DAYS_VERDICT = 60

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(message)s",
                    datefmt="%H:%M:%S")
log = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════════════════
# HELPERS — IC & stats
# ══════════════════════════════════════════════════════════════════════

def daily_cs_ic(df: pd.DataFrame, sig_col: str, ret_col: str,
                min_sym: int = MIN_SYM_DAY) -> dict:
    """Mean daily cross-sectional Spearman IC + t-stat.

    Chỉ tính trên obs có signal != 0 & notna (với score transform, obs = 0
    là "không bắn" — đưa vào rank sẽ pha loãng IC về 0 một cách cơ học).
    Trả thêm 'series' = list[(Timestamp, ic)] cho phân tích stability.
    """
    sub = df.dropna(subset=[sig_col, ret_col])
    sub = sub[sub[sig_col] != 0]
    if sub.empty:
        return {"ic": None, "t": None, "n_days": 0, "n_obs": 0, "series": []}

    series = []
    for day, g in sub.groupby("time"):
        if len(g) < min_sym:
            continue
        if g[sig_col].nunique() < 2:
            continue
        ic = g[sig_col].rank().corr(g[ret_col].rank())
        if pd.notna(ic):
            series.append((day, float(ic)))

    if len(series) < 5:
        return {"ic": None, "t": None, "n_days": len(series),
                "n_obs": len(sub), "series": series}

    ics  = np.array([v for _, v in series])
    mean = float(np.mean(ics))
    std  = float(np.std(ics, ddof=1))
    t    = mean / std * math.sqrt(len(ics)) if std > 1e-12 else None
    return {"ic": round(mean, 4),
            "t": round(t, 2) if t is not None else None,
            "n_days": len(series), "n_obs": int(len(sub)),
            "series": series}


def sign_stats(s: pd.Series) -> dict:
    """Fire rate + sign bias của score transform."""
    valid = s.dropna()
    n = len(valid)
    if n == 0:
        return {"fire_rate": 0.0, "mean": None, "pct_pos": 0.0, "pct_neg": 0.0}
    nz = valid[valid != 0]
    return {
        "fire_rate": round(len(nz) / n * 100, 1),
        "mean":      round(float(valid.mean()), 3),
        "pct_pos":   round(float((valid > 0).mean() * 100), 1),
        "pct_neg":   round(float((valid < 0).mean() * 100), 1),
    }


def verdict(row: dict, expected_sign: int, src: str, hz: int = 5) -> str:
    if src == "A":
        return "INDICATIVE"
    if row["fire_rate"] is not None and row["fire_rate"] < 1.0:
        return "DEAD"
    ic = row.get(f"ic_{hz}d")
    t  = row.get(f"t_{hz}d")
    nd = row.get(f"n_days_{hz}d") or 0
    if ic is None or nd < MIN_DAYS_VERDICT:
        return "N/A"
    if abs(ic) < 0.005 and (t is None or abs(t) < 1.0):
        return "DROP?"
    if t is not None and abs(t) >= 2.0:
        if ic * expected_sign > 0:
            return "KEEP"
        return "FLIP?"
    return "WEAK"


# ══════════════════════════════════════════════════════════════════════
# PHASE 0 v2 — IC STABILITY (theo quý + theo regime proxy)
# ══════════════════════════════════════════════════════════════════════
MIN_DAYS_QUARTER = 15   # tối thiểu ngày IC hợp lệ để 1 quý được tính
MIN_DAYS_REGIME  = 20   # tối thiểu ngày IC hợp lệ để 1 regime được tính
STABLE_SHARE     = 0.8  # >=80% quý cùng dấu → STABLE
# Regime proxy v3 (TERCILE): chia phân phối median-perf20d của universe thành
# 3 phần bằng nhau theo PHÂN VỊ (không dùng ngưỡng cứng): 1/3 phiên yếu nhất
# = 'down', 1/3 mạnh nhất = 'up', giữa = 'flat'. Luôn phân tách được bất kể
# đặc tính thị trường — sửa lỗi v2 (ngưỡng cứng ±2% → 100% phiên rơi vào flat).


def build_regime_map(df: pd.DataFrame) -> tuple:
    """Trả (regime_by_date: dict, q33: float, q67: float)."""
    med = df.groupby("time")["_perf20"].median().dropna()
    if len(med) < 30:
        return {}, None, None
    q33 = float(med.quantile(1 / 3))
    q67 = float(med.quantile(2 / 3))
    def _cls(v):
        if v <= q33:
            return "down"
        if v >= q67:
            return "up"
        return "flat"
    return {d: _cls(v) for d, v in med.items()}, q33, q67


def stability_for_signal(series: list, regime_by_date: dict) -> dict:
    """series = list[(Timestamp, ic)] (horizon 5d). Trả quarter/regime/verdict."""
    if not series:
        return {"quarters": {}, "regimes": {}, "verdict": "INSUFFICIENT",
                "consistency": "—", "gate_hint": "—"}

    s = pd.DataFrame(series, columns=["time", "ic"])
    s["quarter"] = s["time"].dt.to_period("Q").astype(str)
    s["regime"]  = s["time"].map(regime_by_date)

    # ── theo quý ──
    q_agg = s.groupby("quarter")["ic"].agg(["mean", "count"])
    quarters = {q: {"ic": round(float(r["mean"]), 4), "n": int(r["count"])}
                for q, r in q_agg.iterrows()}
    valid = {q: v for q, v in quarters.items() if v["n"] >= MIN_DAYS_QUARTER}

    # ── theo regime ──
    r_agg = (s.dropna(subset=["regime"])
              .groupby("regime")["ic"].agg(["mean", "count"]))
    regimes = {rg: {"ic": round(float(r["mean"]), 4), "n": int(r["count"])}
               for rg, r in r_agg.iterrows() if r["count"] >= MIN_DAYS_REGIME}

    # ── verdict ──
    overall = float(s["ic"].mean())
    if len(valid) < 4:
        vd, cons = "INSUFFICIENT", f"{len(valid)}q hợp lệ"
    else:
        signs      = [np.sign(v["ic"]) for v in valid.values() if v["ic"] != 0]
        same       = sum(1 for x in signs if x == np.sign(overall))
        share      = same / len(signs) if signs else 0
        cons       = f"{same}/{len(signs)} {'dương' if overall > 0 else 'âm'}"
        if share >= STABLE_SHARE:
            vd = "STABLE_POS" if overall > 0 else "STABLE_NEG"
        else:
            vd = "UNSTABLE"

    # ── gate hint (input thiết kế regime gate Phase 2) ──
    gate = "—"
    if vd == "UNSTABLE":
        icu = regimes.get("up",   {}).get("ic")
        icd = regimes.get("down", {}).get("ic")
        icf = regimes.get("flat", {}).get("ic")
        cands = [x for x in (icu, icd, icf) if x is not None]
        if len(cands) >= 2 and (max(cands) - min(cands)) > 0.02:
            gate = "GATE?"
        else:
            gate = "DROP?"
    return {"quarters": quarters, "regimes": regimes, "verdict": vd,
            "consistency": cons, "gate_hint": gate}


def print_stability(stab: dict, order: list, hz: int = 5) -> None:
    tag = "TRADE" if hz <= 5 else "HOLD"
    all_q = sorted({q for r in stab.values() for q in r["quarters"]})
    log.info(f"\n{'═'*110}\n  IC STABILITY {hz}d [{tag}] — theo quý (chỉ quý ≥{MIN_DAYS_QUARTER} ngày IC được xét verdict)\n{'═'*110}")
    hdr = f"{'signal':<16}" + "".join(f"{q:>9}" for q in all_q) \
        + f"  {'consistency':<14} {'verdict':<13} {'gate':<6}"
    log.info(hdr)
    log.info("─" * 110)
    for sig in order:
        r = stab.get(sig)
        if not r:
            continue
        cells = ""
        for q in all_q:
            v = r["quarters"].get(q)
            if v is None:
                cells += f"{'—':>9}"
            else:
                mark = "" if v["n"] >= MIN_DAYS_QUARTER else "*"
                cells += f"{v['ic']:>+8.3f}{mark or ' '}"
        log.info(f"{sig:<16}{cells}  {r['consistency']:<14} "
                 f"{r['verdict']:<13} {r['gate_hint']:<6}")
    log.info("(* = quý dưới ngưỡng ngày, chỉ tham khảo)")

    log.info(f"\n{'═'*80}\n  IC STABILITY {hz}d [{tag}] — theo REGIME proxy "
             f"(tercile của median perf20d universe)\n{'═'*80}")
    log.info(f"{'signal':<16}{'up':>10}{'flat':>10}{'down':>10}"
             f"{'  n(u/f/d)':<16}{'verdict':<13}")
    log.info("─" * 80)
    for sig in order:
        r = stab.get(sig)
        if not r:
            continue
        def cell(rg):
            v = r["regimes"].get(rg)
            return f"{v['ic']:>+10.3f}" if v else f"{'—':>10}"
        ns = "/".join(str(r["regimes"].get(rg, {}).get("n", 0))
                      for rg in ("up", "flat", "down"))
        log.info(f"{sig:<16}{cell('up')}{cell('flat')}{cell('down')}"
                 f"  {ns:<14}{r['verdict']:<13}")


# ══════════════════════════════════════════════════════════════════════
# PART C — EXTENDED INDICATORS từ OHLCV trong parquet (per-symbol)
# ══════════════════════════════════════════════════════════════════════

def _rolling_linreg_endpoint(close: np.ndarray, window: int = 20) -> np.ndarray:
    """Giá trị fitted của linear regression tại điểm cuối mỗi cửa sổ
    (tương đương LINREG_20 của pandas-ta). Closed-form, O(n)."""
    n = len(close)
    out = np.full(n, np.nan)
    if n < window:
        return out
    x     = np.arange(window, dtype=float)
    x_m   = x.mean()
    denom = ((x - x_m) ** 2).sum()
    for i in range(window - 1, n):
        y = close[i - window + 1: i + 1]
        if np.isnan(y).any():
            continue
        y_m   = y.mean()
        slope = ((x - x_m) * (y - y_m)).sum() / denom
        out[i] = y_m + slope * (x[-1] - x_m)   # fitted tại bar cuối
    return out


def compute_extended(g: pd.DataFrame) -> pd.DataFrame:
    """Tính extended indicators cho 1 symbol (đã sort theo time)."""
    g = g.sort_values("time").reset_index(drop=True)
    c, h, l, v = (g["close"].values.astype(float),
                  g["high"].values.astype(float),
                  g["low"].values.astype(float),
                  g["volume"].values.astype(float))
    n = len(g)

    # ── linreg slope % (5-bar change của LINREG_20) — mirror snapshot ──
    lr = _rolling_linreg_endpoint(c, 20)
    slope = np.full(n, np.nan)
    for i in range(5, n):
        if not np.isnan(lr[i]) and not np.isnan(lr[i - 5]) and lr[i - 5] != 0:
            slope[i] = (lr[i] - lr[i - 5]) / abs(lr[i - 5]) * 100
    g["x_linreg_slope"] = slope

    # ── Aroon Oscillator (14) ──
    W = 14
    osc = np.full(n, np.nan)
    for i in range(W, n):
        hh = h[i - W: i + 1]
        ll = l[i - W: i + 1]
        p_hi = int(np.nanargmax(hh))
        p_lo = int(np.nanargmin(ll))
        up   = (p_hi) / W * 100
        down = (p_lo) / W * 100
        osc[i] = up - down
    g["x_aroon_osc"] = osc

    # ── Donchian prev-day 20d high/low ──
    dcu = pd.Series(h).rolling(20).max().shift(1).values
    dcl = pd.Series(l).rolling(20).min().shift(1).values
    g["x_dcu_prev"] = dcu
    g["x_dcl_prev"] = dcl

    # ── A/D Line + slope 20d % ──
    rng  = np.where((h - l) > 0, h - l, np.nan)
    clv  = ((c - l) - (h - c)) / rng
    clv  = np.nan_to_num(clv, nan=0.0)
    ad   = np.cumsum(clv * v)
    ad_s = np.full(n, np.nan)
    for i in range(20, n):
        base = ad[i - 20]
        if abs(base) > 1e-9:
            ad_s[i] = (ad[i] - base) / abs(base) * 100
    g["x_ad_slope"] = ad_s

    # ── EFI(13) — RAW (chuẩn hóa theo rolling |EFI|) ──
    dclose = np.diff(c, prepend=np.nan)
    fi     = dclose * v
    efi    = pd.Series(fi).ewm(span=13, adjust=False).mean()
    scale  = efi.abs().rolling(60, min_periods=20).mean().replace(0, np.nan)
    g["x_efi_norm"] = (efi / scale).values

    # ── Williams %R (14) — RAW ──
    hh14 = pd.Series(h).rolling(14).max()
    ll14 = pd.Series(l).rolling(14).min()
    g["x_willr"] = ((hh14 - pd.Series(c)) / (hh14 - ll14).replace(0, np.nan) * -100).values

    # ── ROC(10) ──
    g["x_roc10"] = pd.Series(c).pct_change(10).values * 100

    # ── NR (5-day window, mirror score_nr7 proxy) ──
    tr = h - l
    is_nr = np.full(n, 0.0)
    comp  = np.full(n, np.nan)
    for i in range(4, n):
        prev = tr[i - 4: i]
        if np.isnan(prev).any() or tr[i] <= 0:
            continue
        comp[i]  = tr[i] / prev.mean() if prev.mean() > 0 else np.nan
        is_nr[i] = 1.0 if tr[i] <= prev.min() else 0.0
    g["x_nr_is"]   = is_nr
    g["x_nr_comp"] = comp

    # ── 52W-high proximity (proxy: max window có sẵn, tối đa 252) ──
    w52 = pd.Series(h).rolling(252, min_periods=120).max()
    g["x_dist_52w"] = ((pd.Series(c) - w52) / w52 * 100).values

    return g


# ── Score transforms — MIRROR ĐÚNG v2f_step_scoring.py v2.3 ────────────

def _steps(x, cuts, vals):
    """cuts giảm dần: x > cuts[0] → vals[0]; ... ; else vals[-1]. NaN giữ NaN."""
    res = np.full(len(x), np.nan)
    for i in range(len(x)):
        if np.isnan(x[i]):
            continue
        assigned = False
        for cut, val in zip(cuts, vals[:-1]):
            if x[i] > cut:
                res[i] = val
                assigned = True
                break
        if not assigned:
            res[i] = vals[-1]
    return res


def build_score_transforms(df: pd.DataFrame) -> pd.DataFrame:
    """Thêm cột s_* (production score) và r_* (raw, direction-adjusted)."""
    flatw = np.where(df["atr_pct"].values < 0.5, 0.5, 1.0)

    # ── TREND ──
    ema_ok = df["ema20"].notna() & df["ema50"].notna()
    df["s_ema_cross"] = np.where(ema_ok,
        np.round(np.where(df["ema20"] > df["ema50"], 15, -15) * flatw), np.nan)

    dist = (df["close"] - df["ema200"]) / df["ema200"] * 100
    df["s_ema200_tf"] = _steps(dist.values, [5, 0, -5], [5, 3, -3, -5])

    adx_ok = df["adx"].notna() & df["ema200"].notna() & (df["adx"] > 25)
    df["s_adx_confirm"] = np.where(
        df["adx"].notna() & df["ema200"].notna(),
        np.where(adx_ok, np.where(df["close"] > df["ema200"], 5, -5), 0),
        np.nan)

    st_ok = df["supertrend"].notna()
    df["s_supertrend"] = np.where(st_ok,
        np.where(df["close"] > df["supertrend"], 5, -5), np.nan)

    df["s_linreg"]  = _steps(df["x_linreg_slope"].values,
                             [3.0, 1.0, -1.0, -3.0], [3, 1, 0, -1, -3])
    df["s_aroon"]   = _steps(df["x_aroon_osc"].values,
                             [60, 30, -30, -60], [3, 2, 0, -2, -3])
    dc_bo = (df["close"] > df["x_dcu_prev"])
    dc_bd = (df["close"] < df["x_dcl_prev"])
    df["s_donchian"] = np.where(df["x_dcu_prev"].notna(),
        np.where(dc_bo, 2, np.where(dc_bd, -2, 0)), np.nan)

    # ── MOMENTUM ──
    rsi = df["rsi"].values
    s_rsi = np.full(len(df), np.nan)
    m = ~np.isnan(rsi)
    s_rsi[m] = 0
    s_rsi[m & (rsi < 30)] = 15
    s_rsi[m & (rsi > 70)] = -10
    s_rsi[m & (rsi >= 40) & (rsi <= 60)] = 5
    df["s_rsi"] = s_rsi

    macd_ok = df["macd_hist"].notna()
    df["s_macd"] = np.where(macd_ok,
        np.round(np.where(df["macd_hist"] > 0, 10, -10) * flatw), np.nan)

    k, d = df["stoch_k"].values, df["stoch_d"].values
    s_st = np.full(len(df), np.nan)
    mk = ~np.isnan(k)
    s_st[mk] = 0
    s_st[mk & (k < 20)] = 5
    s_st[mk & (k > 80)] = -5
    both = mk & ~np.isnan(d)
    s_st[both & (k > d) & (k < 80)] = np.where(
        k[both & (k > d) & (k < 80)] < 20, 5 + 3, 3)
    s_st[both & (k < d) & (k > 20)] = np.where(
        k[both & (k < d) & (k > 20)] > 80, -5 - 3, -3)
    df["s_stoch"] = s_st

    df["s_roc10"] = _steps(df["x_roc10"].values,
                           [5, 2, -2, -5], [3, 1, 0, -1, -3])
    df["r_willr"] = -df["x_willr"]          # RAW: willr thấp (oversold) → kỳ vọng +

    # ── VOLUME ──
    cmf = df["cmf"].values
    s_cmf = np.full(len(df), np.nan)
    mc = ~np.isnan(cmf)
    s_cmf[mc] = 0
    s_cmf[mc & (cmf > 0.1)]  = -8
    s_cmf[mc & (cmf < -0.1)] = 8
    df["s_cmf"] = s_cmf

    mfi = df["mfi"].values
    s_mfi = np.full(len(df), np.nan)
    mm = ~np.isnan(mfi)
    s_mfi[mm] = 0
    s_mfi[mm & (mfi > 60)] = 6
    s_mfi[mm & (mfi < 40)] = -6
    df["s_mfi"] = s_mfi

    obv_ok = df["obv"].notna() & df["ema_cross_pct"].notna()
    agree  = (np.sign(df["obv"]) == np.sign(df["ema_cross_pct"]))
    df["s_obv_confirm"] = np.where(obv_ok, np.where(agree, 4, -4), np.nan)

    vr = df["vol_ratio"].values
    s_vr = np.full(len(df), np.nan)
    mv = ~np.isnan(vr)
    s_vr[mv] = 0
    s_vr[mv & (vr > 2.0)]                = 5
    s_vr[mv & (vr > 1.5) & (vr <= 2.0)]  = 3
    s_vr[mv & (vr < 0.5)]                = -3
    df["s_vol_ratio"] = s_vr

    df["s_ad_slope"] = _steps(df["x_ad_slope"].values,
                              [5.0, 1.0, -1.0, -5.0], [2, 1, 0, -1, -2])
    df["r_efi"] = df["x_efi_norm"]          # RAW

    # ── VOLATILITY ──
    bb = df["bb_pos"].values
    s_bb = np.full(len(df), np.nan)
    mb = ~np.isnan(bb)
    s_bb[mb] = 0
    s_bb[mb & (bb < 0.2)] = 5
    s_bb[mb & (bb > 0.8)] = -5
    df["s_bb"] = s_bb

    nr, cp = df["x_nr_is"].values, df["x_nr_comp"].values
    s_nr = np.full(len(df), np.nan)
    mn = ~np.isnan(cp)
    s_nr[mn] = 0
    s_nr[mn & (cp < 0.7)] = 1
    s_nr[mn & (nr == 1) & (cp < 0.8)] = 2
    s_nr[mn & (nr == 1) & (cp < 0.6)] = 3
    df["s_nr7"] = s_nr

    df["r_dist_52w"] = df["x_dist_52w"]     # RAW: gần đỉnh 52W → kỳ vọng +

    # ── RS proxy (vs equal-weight universe) ──
    perf20 = df.groupby("symbol")["close"].pct_change(20)
    df["_perf20"] = perf20
    mkt = df.groupby("time")["_perf20"].transform("median")
    df["r_rs_proxy"] = df["_perf20"] - mkt   # RAW: outperform → kỳ vọng +
    return df


# Danh mục signal Part C: (cột, group, expected_sign, note)
PART_C_SIGNALS = [
    ("s_ema_cross",   "trend",      +1, "score v2.3"),
    ("s_ema200_tf",   "trend",      +1, "score v2.3 (TF Option A)"),
    ("s_adx_confirm", "trend",      +1, "score v2.3"),
    ("s_supertrend",  "trend",      +1, "score v2.3"),
    ("s_linreg",      "trend",      +1, "score v2.2"),
    ("s_aroon",       "trend",      +1, "score v2.2"),
    ("s_donchian",    "trend",      +1, "score v2.2"),
    ("r_rs_proxy",    "trend",      +1, "RAW proxy (median universe)"),
    ("r_dist_52w",    "trend",      +1, "RAW (proximity 52W-high)"),
    ("s_rsi",         "momentum",   +1, "score v2.3 (mean-rev)"),
    ("s_macd",        "momentum",   +1, "score v2.3 (TF)"),
    ("s_stoch",       "momentum",   +1, "score v2.3 (mean-rev)"),
    ("s_roc10",       "momentum",   +1, "score v2.1 (TF)"),
    ("r_willr",       "momentum",   +1, "RAW (oversold→+)"),
    ("s_cmf",         "volume",     +1, "score v2.3 (đảo, mean-rev)"),
    ("s_mfi",         "volume",     +1, "score v2.3 (TF)"),
    ("s_obv_confirm", "volume",     +1, "score v2.3"),
    ("s_vol_ratio",   "volume",     +1, "score v2.3"),
    ("s_ad_slope",    "volume",     +1, "score v2.2"),
    ("r_efi",         "volume",     +1, "RAW (norm |EFI| 60d)"),
    ("s_bb",          "volatility", +1, "score v2.3 (mean-rev)"),
    ("s_nr7",         "volatility", +1, "score v2.1 (chỉ +, setup)"),
]

CORR_GROUPS = {
    "trend":    ["s_ema_cross", "s_ema200_tf", "s_adx_confirm", "s_supertrend",
                 "s_linreg", "s_aroon", "s_donchian"],
    "momentum": ["s_rsi", "s_macd", "s_stoch", "s_roc10"],
    "volume":   ["s_cmf", "s_mfi", "s_obv_confirm", "s_vol_ratio", "s_ad_slope"],
}

CANCEL_PAIRS = [
    ("s_rsi", "s_macd",  "momentum: mean-rev(RSI) vs TF(MACD)"),
    ("s_stoch", "s_roc10", "momentum: mean-rev(Stoch) vs TF(ROC)"),
    ("s_cmf", "s_mfi",   "volume: CMF(đảo) vs MFI(TF)"),
]


def run_part_c(report: dict) -> None:
    if not PARQUET.exists():
        log.error(f"❌ {PARQUET} không tồn tại — chạy backtest/bt_data.py trước. SKIP Part C.")
        report["part_c"] = {"error": "dataset.parquet missing"}
        return

    df = pd.read_parquet(PARQUET)
    df["time"] = pd.to_datetime(df["time"])
    log.info(f"[C] dataset: {len(df):,} rows, {df['symbol'].nunique()} symbols, "
             f"{df['time'].min().date()} → {df['time'].max().date()}")
    report["part_c_meta"] = {
        "rows": int(len(df)), "symbols": int(df["symbol"].nunique()),
        "date_min": str(df["time"].min().date()),
        "date_max": str(df["time"].max().date()),
    }

    need = {"open", "high", "low", "close", "volume"}
    if not need.issubset(df.columns):
        log.error(f"❌ parquet thiếu OHLCV {need - set(df.columns)} — rebuild bt_data. SKIP Part C.")
        report["part_c"] = {"error": "parquet missing OHLCV"}
        return

    # Tự tính forward return cho horizon chưa có sẵn trong parquet (10d, 20d)
    df = df.sort_values(["symbol", "time"]).reset_index(drop=True)
    for hz in HORIZONS:
        col = f"ret_{hz}d"
        if col not in df.columns:
            df[col] = (df.groupby("symbol")["close"].shift(-hz)
                       / df["close"] - 1)
            log.info(f"[C] Tính bổ sung {col} từ close (parquet không có sẵn)")

    log.info("[C] Tính extended indicators per-symbol (pure pandas/numpy)...")
    parts = []
    for sym, g in df.groupby("symbol"):
        ge = compute_extended(g)
        ge["symbol"] = sym          # đảm bảo giữ cột qua mọi pandas version
        parts.append(ge)
    df = pd.concat(parts, ignore_index=True)
    df = build_score_transforms(df)

    rows = []
    series_hz = {h: {} for h in STABILITY_HZS}
    for col, grp, exp_sign, note in PART_C_SIGNALS:
        if col not in df.columns:
            continue
        st = sign_stats(df[col])
        row = {"signal": col, "group": grp, "src": "C", "note": note, **st}
        for hz in HORIZONS:
            r = daily_cs_ic(df, col, f"ret_{hz}d")
            row[f"ic_{hz}d"] = r["ic"]
            row[f"t_{hz}d"]  = r["t"]
            row[f"n_days_{hz}d"] = r["n_days"]
            row[f"n_obs_{hz}d"]  = r["n_obs"]
            if hz in STABILITY_HZS:
                series_hz[hz][col] = r["series"]
        row["verdict"]     = verdict(row, exp_sign, "C", hz=5)   # khung TRADE
        row["verdict_20d"] = verdict(row, exp_sign, "C", hz=20)  # khung HOLD
        rows.append(row)
    report["signals_c"] = rows

    # ── PHASE 0 v2: IC stability theo quý & regime proxy ────────────
    regime_by_date, q33, q67 = build_regime_map(df)
    dist = pd.Series([v for v in regime_by_date.values() if v]).value_counts()
    log.info(f"\n[C] Regime proxy TERCILE — ngưỡng thực tế: "
             f"down ≤ {q33:+.2f}% < flat < {q67:+.2f}% ≤ up | "
             f"phân bố phiên: {dist.to_dict()}")
    report["regime_distribution"] = dist.to_dict()
    report["regime_terciles"] = {"q33_pct": q33, "q67_pct": q67}

    for hz in STABILITY_HZS:
        stab = {sig: stability_for_signal(series_hz[hz].get(sig, []),
                                          regime_by_date)
                for sig in series_hz[hz]}
        print_stability(stab,
                        [c for c, _, _, _ in PART_C_SIGNALS if c in stab],
                        hz=hz)
        report[f"ic_stability_{hz}d"] = stab

    # Intra-group correlation (evidence #2)
    corr_out = {}
    for gname, cols in CORR_GROUPS.items():
        cols_ok = [c for c in cols if c in df.columns]
        sub = df[cols_ok].dropna()
        if len(sub) < 100:
            continue
        cm = sub.corr(method="spearman").round(3)
        corr_out[gname] = cm.to_dict()
        log.info(f"\n[C] Intra-group Spearman corr — {gname.upper()} "
                 f"(n={len(sub):,}):\n{cm.to_string()}")
    report["intra_group_corr"] = corr_out

    # Cancellation pairs (evidence #8, #9)
    canc = []
    for a, b, desc in CANCEL_PAIRS:
        sub = df[[a, b]].dropna()
        sub = sub[(sub[a] != 0) & (sub[b] != 0)]
        if len(sub) < 100:
            continue
        corr = float(sub[a].corr(sub[b], method="spearman"))
        opp  = float((np.sign(sub[a]) != np.sign(sub[b])).mean() * 100)
        canc.append({"pair": desc, "spearman": round(corr, 3),
                     "pct_opposite_sign": round(opp, 1), "n": int(len(sub))})
        log.info(f"[C] CANCEL {desc}: corr={corr:+.3f}, "
                 f"ngược dấu={opp:.1f}% (n={len(sub):,})")
    report["cancellation"] = canc

    _print_table(rows, "PART C — per-signal IC (dataset.parquet)")


# ══════════════════════════════════════════════════════════════════════
# PART A — git history của output/v2f_signals.json
# ══════════════════════════════════════════════════════════════════════

A_EXT_SIGNALS = [
    ("ext_prop_score",    "smart_money", +1),
    ("ext_insider_score", "smart_money", +1),
    ("ext_room_score",    "ff",          +1),
    ("ext_ba_score",      "depth",       +1),
    ("ext_fv_score",      "fundamental", +1),
    ("ext_div_score",     "fundamental", +1),
    ("ext_eps_score",     "growth",      +1),
]
A_GROUP_NORMS = [
    ("norm_order_flow",  "order_flow",  +1),
    ("norm_depth",       "depth",       +1),
    ("norm_ff",          "ff",          +1),
    ("norm_smart_money", "smart_money", +1),
]


def _git(*args) -> str:
    r = subprocess.run(["git", *args], cwd=REPO_ROOT,
                       capture_output=True, text=True, timeout=300)
    if r.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)}: {r.stderr.strip()[:300]}")
    return r.stdout


def _ensure_history() -> None:
    try:
        shallow = _git("rev-parse", "--is-shallow-repository").strip()
        if shallow == "true":
            log.info("[A] Repo shallow — git fetch --unshallow ...")
            try:
                _git("fetch", "--unshallow", "--quiet")
            except Exception:
                _git("fetch", "--deepen=1000", "--quiet")
    except Exception as e:
        log.warning(f"[A] Không unshallow được ({e}) — dùng history hiện có")


def load_signals_history() -> pd.DataFrame:
    _ensure_history()
    try:
        out = _git("log", "--format=%H|%cI", "--", SIGNALS_GIT)
    except Exception as e:
        log.error(f"[A] git log fail ({e}) — SKIP Part A")
        return pd.DataFrame()
    commits = []
    for line in out.strip().splitlines():
        if "|" not in line:
            continue
        sha, iso = line.split("|", 1)
        commits.append((sha, iso))
    log.info(f"[A] {len(commits)} commits chạm {SIGNALS_GIT}")
    if not commits:
        return pd.DataFrame()

    frames = []
    for sha, iso in commits:
        try:
            raw = _git("show", f"{sha}:{SIGNALS_GIT}")
            data = json.loads(raw)
        except Exception:
            continue
        if not isinstance(data, list) or not data:
            continue
        sv = str(data[0].get("scoring_version", ""))
        if sv != "v2.3":
            continue
        f = pd.DataFrame(data)
        f["_commit"] = sha
        frames.append(f)

    if not frames:
        log.warning("[A] Không có snapshot v2.3 nào trong git history")
        return pd.DataFrame()

    hist = pd.concat(frames, ignore_index=True)
    keep = (["symbol", "date", "snap_time", "total_score", "_of_vol_spike",
             "_of_pattern", "_commit"]
            + [c for c, _, _ in A_EXT_SIGNALS]
            + [c for c, _, _ in A_GROUP_NORMS])
    keep = [c for c in keep if c in hist.columns]
    hist = hist[keep].copy()
    log.info(f"[A] Panel: {len(hist):,} rows, "
             f"{hist['symbol'].nunique()} symbols, "
             f"{hist['date'].nunique()} ngày (mọi run)")
    return hist


def run_part_a(report: dict) -> None:
    hist = load_signals_history()
    if hist.empty:
        report["part_a"] = {"error": "no v2.3 snapshots in git history"}
        return

    # ── BONUS: order flow bias theo snap_time (evidence #1) — dùng MỌI run ──
    if "_of_vol_spike" in hist.columns and "snap_time" in hist.columns:
        hist["_of_vol_spike"] = pd.to_numeric(hist["_of_vol_spike"], errors="coerce")
        by_time = (hist.groupby("snap_time")
                   .agg(n=("symbol", "size"),
                        vol_spike_mean=("_of_vol_spike", "mean"),
                        pct_weak=("_of_pattern",
                                  lambda s: (s == "WEAK").mean() * 100))
                   .round(1).reset_index())
        log.info(f"\n[A] ORDER FLOW theo snap_time (evidence bias intraday #1):\n"
                 f"{by_time.to_string(index=False)}")
        report["of_by_snaptime"] = by_time.to_dict(orient="records")

    # ── Panel EOD: run cuối mỗi ngày ──
    hist = hist.sort_values(["date", "snap_time"])
    eod  = hist.groupby(["date", "symbol"], as_index=False).tail(1).copy()
    log.info(f"[A] EOD panel: {len(eod):,} rows / {eod['date'].nunique()} ngày")

    # ── Forward return từ close trong parquet ──
    if not PARQUET.exists():
        report["part_a"] = {"error": "parquet missing — no forward returns"}
        return
    px = pd.read_parquet(PARQUET, columns=["symbol", "time", "close"])
    px["time"] = pd.to_datetime(px["time"])
    px = px.sort_values(["symbol", "time"])
    pmax = px["time"].max().date()
    log.info(f"[A] Giá đến {pmax} — signal sau {pmax} sẽ không có ret "
             f"(rebuild bt_data.py nếu cần fresh)")

    for hz in HORIZONS:
        px[f"a_ret_{hz}d"] = (px.groupby("symbol")["close"].shift(-hz)
                              / px["close"] - 1)

    eod["time"] = pd.to_datetime(eod["date"])
    panel = eod.merge(
        px[["symbol", "time"] + [f"a_ret_{h}d" for h in HORIZONS]],
        on=["symbol", "time"], how="left")
    n_ret = panel[f"a_ret_1d"].notna().sum()
    log.info(f"[A] Join returns: {n_ret}/{len(panel)} rows có ret_1d")

    rows = []
    sig_list = ([(c, g, e) for c, g, e in A_EXT_SIGNALS if c in panel.columns]
                + [(c, g, e) for c, g, e in A_GROUP_NORMS if c in panel.columns])
    for col, grp, exp_sign in sig_list:
        panel[col] = pd.to_numeric(panel[col], errors="coerce")
        st = sign_stats(panel[col])
        row = {"signal": col, "group": grp, "src": "A", "note": "forward v2.3", **st}
        for hz in HORIZONS:
            r = daily_cs_ic(panel.rename(columns={f"a_ret_{hz}d": "ret"}),
                            col, "ret", min_sym=MIN_SYM_DAY_A)
            row[f"ic_{hz}d"] = r["ic"]
            row[f"t_{hz}d"]  = r["t"]
            row[f"n_days_{hz}d"] = r["n_days"]
            row[f"n_obs_{hz}d"]  = r["n_obs"]
        row["verdict"] = verdict(row, exp_sign, "A")
        rows.append(row)
    report["signals_a"] = rows
    _print_table(rows, "PART A — per-signal IC (git history, INDICATIVE)")


# ══════════════════════════════════════════════════════════════════════
# OUTPUT
# ══════════════════════════════════════════════════════════════════════

def _print_table(rows: list, title: str) -> None:
    log.info(f"\n{'═'*100}\n  {title}\n{'═'*100}")
    hdr = (f"{'signal':<18} {'group':<11} {'fire%':>6} "
           f"{'IC_1d':>7} {'IC_5d':>7} {'IC_10d':>7} {'IC_20d':>7} "
           f"{'t_5d':>6} {'t_20d':>6} {'v_TRADE(5d)':<12} {'v_HOLD(20d)':<12}")
    log.info(hdr)
    log.info("─" * 112)
    for r in sorted(rows, key=lambda x: (x["group"], x["signal"])):
        def fmt(v, spec):
            return format(v, spec) if v is not None else "  —"
        log.info(
            f"{r['signal']:<18} {r['group']:<11} "
            f"{fmt(r.get('fire_rate'), '6.1f')} "
            f"{fmt(r.get('ic_1d'), '7.3f')} {fmt(r.get('ic_5d'), '7.3f')} "
            f"{fmt(r.get('ic_10d'), '7.3f')} {fmt(r.get('ic_20d'), '7.3f')} "
            f"{fmt(r.get('t_5d'), '6.1f')} {fmt(r.get('t_20d'), '6.1f')} "
            f"{r.get('verdict', '—'):<12} {r.get('verdict_20d', '—'):<12}")


def main():
    log.info("=" * 70)
    log.info("  DIAG SIGNAL IC — V2f v2.3 per-signal audit (Hybrid C+A)")
    log.info("  Zero production change | reports → backtest_output/reports/")
    log.info("=" * 70)
    REPORT_DIR.mkdir(parents=True, exist_ok=True)

    report = {"generated_at": datetime.now().isoformat(timespec="seconds"),
              "scoring_version_audited": "v2.3"}

    run_part_c(report)
    run_part_a(report)

    out = REPORT_DIR / f"signal_ic_{datetime.now():%Y%m%d}.json"
    with out.open("w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2, default=str)
    log.info(f"\n✅ Report saved: {out}")
    log.info("Nhắc kỷ luật: kết quả CHỈ dùng thiết kế v2.4 — "
             "KHÔNG chỉnh weights/caps production trước khi round 1 close.")


if __name__ == "__main__":
    main()
