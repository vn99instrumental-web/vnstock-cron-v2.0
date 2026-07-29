"""
scripts/diag_phase_a_gate.py — PHASE A: đo lấp ma trận GATE (V4 RCEG)
==============================================================================
Theo DESIGN_PHASE_A_GATE_MEASUREMENT.md (đã duyệt 2026-07-29).
CHỈ ĐO — không đụng registry/engine. Output = số + GATE v2 ĐỀ XUẤT.

Chốt tham số (đã duyệt):
  - A2 dùng ngưỡng phí BẢO THỦ 0.50% (bù survivorship bias — lỗ hổng D3).
  - Có probe backfill FF (3 mã mẫu, định giá chi phí).
  - Tái nhập adx/supertrend vào A1 (đo lại THEO REGIME — hợp lệ; tính vào sổ test).
  - Q3 (flow/fund) chỉ INDICATIVE (lỗ hổng D1: backtest không có FF/fund lịch sử).

CÁC PHÉP ĐO:
  A1 trend/breakout × regime   [backtest OHLCV — ĐỦ]   → ứng viên lấp UPTREND
  A2 kinh tế MR-down            [backtest OHLCV — ĐỦ]   → ô V4 đang bật có vượt phí?
  A3 flow/fund × regime         [sổ forward v3 — MỎNG]  → INDICATIVE, tự phát hiện s_*
  A4 whipsaw regime             [chuỗi VNINDEX — ĐỦ]    → có cần hysteresis?
  Probe FF backfill             [API 3 mã]              → khả thi & chi phí

ISOLATION: không import utils/steps/config. Được import vnstock (data lib).
  Chỉ đọc parquet + sổ forward; chỉ ghi backtest_output/reports/.

TIÊU CHÍ ĐĂNG KÝ TRƯỚC (hard-code):
  IC_T_MIN=2.0 · MIN_DAYS_BUCKET=30 · COST_RT=0.50% (A2, bảo thủ) / 0.30–0.50 (A1)
  ALIVE nếu IC>0 & |t|≥2.0 & n_days≥30 (+ UPTREND: dương CẢ 2 nửa).

GIẢ THUYẾT ĐỊNH HƯỚNG (viết trước → confirmation, không fishing):
  H_A1a: dist_52w IC>0 trong UPTREND (mạnh giữ mạnh)
  H_A1b: supertrend/adx/ema_align IC>0 trong UPTREND
  H_A1c: các tín hiệu trend ≈0/âm trong DOWN (đối xứng MR)
  H_A2 : MR-down gap>0.50%
Sổ test tích luỹ: Phase A thêm ~5 tín hiệu × 4 regime (A1) + 1 (A2) ≈ 21 test.

TRIGGER: debug.yml → script = scripts/diag_phase_a_gate.py

CHANGELOG: v1 (2026-07-29) initial.
"""
import sys
import json
import math
import glob
import logging
from datetime import datetime
from pathlib import Path

for _m in list(sys.modules.keys()):
    if _m.startswith(("utils.", "steps.")) or _m == "config":
        raise RuntimeError(f"ISOLATION VIOLATION: {_m}")

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

HORIZON         = 5
ADTV_WINDOW     = 20
HIGH_TIER_Q     = 2 / 3
MIN_SYM_TIER    = 15
MIN_DAYS_BUCKET = 30
IC_T_MIN        = 2.0
COST_A1_LO, COST_A1_HI = 0.30, 0.50
COST_A2         = 0.50           # bảo thủ (D3)
PROBE_SYMBOLS   = ["HPG", "VCB", "SSI"]
REGIME_ORDER    = ["UPTREND", "SIDEWAYS", "DOWNTREND", "DEEP_DOWN"]

# tín hiệu A1 (định hướng: CAO = bullish → IC dương = trend/breakout đúng)
TREND_SIGS = ["dist_52w", "ema_align", "trend_mom", "supertrend_dir", "adx_dir"]


# ══════════════════════════════════════════ STATS ══════════════════════
def _spearman(x, y):
    if len(x) < 3:
        return np.nan
    rx = pd.Series(x).rank().to_numpy(); ry = pd.Series(y).rank().to_numpy()
    if np.std(rx) == 0 or np.std(ry) == 0:
        return np.nan
    return float(np.corrcoef(rx, ry)[0, 1])


def daily_ic(df, sig, ret, exclude_zero=False, min_sym=MIN_SYM_TIER):
    series, n_obs = [], 0
    for d, g in df.groupby("date"):
        sub = g[[sig, ret]].dropna()
        if exclude_zero:
            sub = sub[sub[sig] != 0]
        if len(sub) < min_sym:
            continue
        ic = _spearman(sub[sig].to_numpy(), sub[ret].to_numpy())
        if not np.isnan(ic):
            series.append((d, ic)); n_obs += len(sub)
    if not series:
        return {"ic": np.nan, "t": np.nan, "n_days": 0, "n_obs": 0, "series": []}
    a = np.array([v for _, v in series]); m = float(a.mean())
    sd = float(a.std(ddof=1)) if len(a) > 1 else np.nan
    t = (m / sd * math.sqrt(len(a))) if sd and sd > 0 else np.nan
    return {"ic": m, "t": t, "n_days": len(a), "n_obs": n_obs, "series": series}


def time_split(series):
    if len(series) < 4:
        return None, None
    ss = sorted(series, key=lambda kv: kv[0]); mid = len(ss) // 2
    out = []
    for part in (ss[:mid], ss[mid:]):
        a = np.array([v for _, v in part]); m = float(a.mean())
        sd = float(a.std(ddof=1)) if len(a) > 1 else np.nan
        t = (m / sd * math.sqrt(len(a))) if sd and sd > 0 else np.nan
        out.append({"ic": m, "t": t, "n_days": len(a)})
    return out[0], out[1]


def quintile_gap(df, sig, ret, min_sym=MIN_SYM_TIER):
    gaps = []
    for _, g in df.groupby("date"):
        sub = g[[sig, ret]].dropna()
        if len(sub) < min_sym:
            continue
        sub = sub.sort_values(sig); k = max(1, int(len(sub) * 0.2))
        gaps.append(sub.tail(k)[ret].mean() - sub.head(k)[ret].mean())
    return (float(np.mean(gaps)) if gaps else np.nan, len(gaps))


def verdict_bucket(r):
    if r["n_days"] < MIN_DAYS_BUCKET:
        return f"THƯA(n={r['n_days']})"
    if np.isnan(r["ic"]) or r["ic"] <= 0:
        return "DEAD"
    return "ALIVE" if abs(r["t"]) >= IC_T_MIN else "WEAK"


def econ_tag(gap, lo=COST_A1_LO, hi=COST_A1_HI):
    if np.isnan(gap):
        return "n/a"
    if abs(gap) <= hi:
        return f"KHÔNG vượt phí (gap {gap:+.3f}% ≤ {hi}%)"
    return f"VƯỢT? gap {gap:+.3f}% (net ~{abs(gap)-(lo+hi)/2:+.3f}%)"


# ═══════════════════════════════════ INDICATORS ════════════════════════
def _wilder(s, n):
    return s.ewm(alpha=1 / n, adjust=False).mean()


def _atr(h, l, c, n):
    pc = c.shift(1)
    tr = pd.concat([h - l, (h - pc).abs(), (l - pc).abs()], axis=1).max(axis=1)
    return _wilder(tr, n)


def _adx(h, l, c, n=14):
    up = h.diff(); dn = -l.diff()
    plus_dm = np.where((up > dn) & (up > 0), up, 0.0)
    minus_dm = np.where((dn > up) & (dn > 0), dn, 0.0)
    atr = _atr(h, l, c, n)
    pdi = 100 * _wilder(pd.Series(plus_dm, index=h.index), n) / atr.replace(0, np.nan)
    mdi = 100 * _wilder(pd.Series(minus_dm, index=h.index), n) / atr.replace(0, np.nan)
    dx = 100 * (pdi - mdi).abs() / (pdi + mdi).replace(0, np.nan)
    return _wilder(dx, n)


def _supertrend_dir(h, l, c, period=10, mult=3.0):
    hl2 = (h + l) / 2
    atr = _atr(h, l, c, period)
    ub = (hl2 + mult * atr).to_numpy()
    lb = (hl2 - mult * atr).to_numpy()
    cc = c.to_numpy()
    n = len(cc)
    fub = np.full(n, np.nan); flb = np.full(n, np.nan); dir_ = np.full(n, 1.0)
    for i in range(n):
        if i == 0 or np.isnan(ub[i]):
            fub[i] = ub[i]; flb[i] = lb[i]; dir_[i] = 1.0; continue
        fub[i] = ub[i] if (ub[i] < fub[i-1] or cc[i-1] > fub[i-1]) else fub[i-1]
        flb[i] = lb[i] if (lb[i] > flb[i-1] or cc[i-1] < flb[i-1]) else flb[i-1]
        if cc[i] > fub[i-1]:
            dir_[i] = 1.0
        elif cc[i] < flb[i-1]:
            dir_[i] = -1.0
        else:
            dir_[i] = dir_[i-1]
    return pd.Series(dir_, index=c.index)


def compute_indicators(g):
    g = g.sort_values("time").copy()
    c, h, l, v = g["close"], g["high"], g["low"], g["volume"]
    hh = h.rolling(14).max(); ll = l.rolling(14).min()
    g["willr_14"] = -100 * (hh - c) / (hh - ll).replace(0, np.nan)
    mid = c.rolling(20).mean(); sd = c.rolling(20).std(ddof=0)
    g["bb_position"] = (c - (mid - 2*sd)) / ((mid + 2*sd) - (mid - 2*sd)).replace(0, np.nan)
    ema20 = c.ewm(span=20, adjust=False).mean()
    ema50 = c.ewm(span=50, adjust=False).mean()
    ema200 = c.ewm(span=200, adjust=False, min_periods=200).mean()
    g["price_vs_ema200_pct"] = (c - ema200) / ema200 * 100
    g["return_20d_pct"] = (c / c.shift(20) - 1) * 100
    g[f"ret_{HORIZON}d"] = (c.shift(-HORIZON) / c - 1) * 100
    g["adtv"] = (c * v).rolling(ADTV_WINDOW).mean()
    # ── trend/breakout (A1) ──
    high_52w = c.rolling(252, min_periods=60).max()
    g["dist_52w"] = (c - high_52w) / high_52w * 100            # cao(≈0)=gần đỉnh=bullish
    g["ema_align"] = (ema20 - ema50) / ema50 * 100             # dương=ngắn>dài=bullish
    g["trend_mom"] = g["return_20d_pct"]                       # momentum control
    stdir = _supertrend_dir(h, l, c)
    g["supertrend_dir"] = stdir                                # +1 up / -1 down
    adx = _adx(h, l, c, 14)
    g["adx_dir"] = adx * np.sign((ema20 - ema50).fillna(0))    # sức mạnh × hướng
    g["vol_ma_ratio"] = v / v.rolling(20).mean()
    return g


def _sc_willr(w):
    if pd.isna(w): return 0
    return 6 if w<=-90 else 4 if w<=-80 else 2 if w<=-60 else -6 if w>=-10 else -4 if w>=-20 else -2 if w>=-40 else 0
def _sc_bb(b):
    if pd.isna(b): return 0
    return 5 if b<0.10 else 3 if b<0.20 else -5 if b>0.90 else -3 if b>0.80 else 0
def _sc_overext(d):
    if pd.isna(d): return 0
    return -5 if d>15 else -3 if d>8 else -1 if d>3 else 5 if d<-15 else 3 if d<-8 else 1 if d<-3 else 0
def _sc_rs(rs):
    if pd.isna(rs): return 0
    return -4 if rs>1.30 else -2 if rs>1.10 else 4 if rs<0.70 else 2 if rs<0.90 else 0


def add_mr(df, vnret20):
    df = df.copy()
    df["s_willr"] = df["willr_14"].map(_sc_willr)
    df["s_bb"] = df["bb_position"].map(_sc_bb)
    df["s_overext"] = df["price_vs_ema200_pct"].map(_sc_overext)
    vr = df["date"].map(vnret20)
    rs = (1 + df["return_20d_pct"]/100) / (1 + vr/100)
    df["s_rs"] = rs.map(_sc_rs)
    df["s_mr"] = df[["s_willr","s_bb","s_overext","s_rs"]].sum(axis=1)
    return df


# ═══════════════════════════════ VNINDEX / REGIME ══════════════════════
def _imp(name):
    for p in ("vnstock", "vnstock_data"):
        try:
            return getattr(__import__(p, fromlist=[name]), name)
        except Exception:
            continue
    return None


def fetch_vnindex():
    Quote = _imp("Quote")
    if Quote is None:
        return None
    for ln in ("36M", "24M", "18M"):
        try:
            df = Quote(source="VCI", symbol="VNINDEX").history(length=ln, interval="1D")
            if df is not None and not df.empty and "close" in df.columns:
                df = df.copy()
                tc = "time" if "time" in df.columns else df.columns[0]
                df["time"] = pd.to_datetime(df[tc])
                df["close"] = pd.to_numeric(df["close"], errors="coerce")
                df = df.dropna(subset=["close"]).sort_values("time")
                log.info(f"VNINDEX: {len(df)} phiên {df['time'].min().date()}→{df['time'].max().date()}")
                return df[["time", "close"]]
        except Exception as e:
            log.warning(f"fetch VNINDEX {ln} lỗi: {e}")
    return None


def build_regime(vn):
    c = vn["close"].reset_index(drop=True)
    e50 = c.ewm(span=50, adjust=False).mean()
    e200 = c.ewm(span=200, adjust=False, min_periods=200).mean()
    c5 = (c / c.shift(5) - 1) * 100; c20 = (c / c.shift(20) - 1) * 100
    reg, r20 = {}, {}
    t = vn["time"].reset_index(drop=True)
    for i in range(len(c)):
        d = t.iloc[i].strftime("%Y-%m-%d")
        r20[d] = float(c20.iloc[i]) if not pd.isna(c20.iloc[i]) else np.nan
        a50 = c.iloc[i] > e50.iloc[i]
        a200 = (c.iloc[i] > e200.iloc[i]) if not pd.isna(e200.iloc[i]) else a50
        x5 = c5.iloc[i] if not pd.isna(c5.iloc[i]) else 0.0
        x20 = c20.iloc[i] if not pd.isna(c20.iloc[i]) else 0.0
        if ((not a50) and (not a200)) or x20 <= -8:
            g = "DEEP_DOWN"
        elif (not a50) and (x20 <= -2 or x5 <= -3):
            g = "DOWNTREND"
        elif a50 and a200 and x20 > 0:
            g = "UPTREND"
        else:
            g = "SIDEWAYS"
        reg[d] = g
    return reg, r20


# ═══════════════════════════════════ A1 ════════════════════════════════
def run_a1(report, hi):
    ret = f"ret_{HORIZON}d"
    log.info(f"\n{'═'*90}\n  A1 — TREND/BREAKOUT × REGIME (IC {HORIZON}d, tier liquid)\n"
             f"  Kỳ vọng: dương ở UPTREND, ≈0/âm ở DOWN (đối xứng MR)\n{'═'*90}")
    out = {}
    for sig in TREND_SIGS:
        log.info(f"\n  ▸ {sig}")
        log.info(f"    {'regime':<11}{'IC':>9}{'t':>7}{'n_d':>6}{'gap%':>9}  verdict")
        rows = {}
        for rg in REGIME_ORDER:
            sub = hi[hi["regime"] == rg]
            r = daily_ic(sub, sig, ret)
            gap, _ = quintile_gap(sub, sig, ret)
            extra = ""
            both_pos = None
            h1, h2 = (None, None)
            if rg in ("UPTREND", "SIDEWAYS"):     # cả 2 regime "ALIVE" cần soi 2 nửa
                h1, h2 = time_split(r["series"])
                if h1 and h2:
                    both_pos = (h1["ic"] > 0 and h2["ic"] > 0)
                    conf = "✓2nửa" if both_pos else "✗FLIP"
                    extra = (f"  [2 nửa: {h1['ic']:+.3f}(n{h1['n_days']})/"
                             f"{h2['ic']:+.3f}(n{h2['n_days']}) {conf}]")
            rows[rg] = {"ic": r["ic"], "t": r["t"], "n_days": r["n_days"],
                        "gap": gap, "verdict": verdict_bucket(r),
                        "h1_ic": (h1["ic"] if h1 else None),
                        "h2_ic": (h2["ic"] if h2 else None),
                        "both_pos": both_pos}
            log.info(f"    {rg:<11}{r['ic']:>+9.4f}{r['t']:>+7.2f}{r['n_days']:>6}"
                     f"{gap:>+9.3f}  {rows[rg]['verdict']}{extra}")
        out[sig] = rows
    report["A1"] = out
    return out


# ═══════════════════════════════════ A2 ════════════════════════════════
def run_a2(report, hi):
    ret = f"ret_{HORIZON}d"
    down = hi[hi["regime"].isin(["DOWNTREND", "DEEP_DOWN"])]
    r = daily_ic(down, "s_mr", ret, exclude_zero=True)
    gap, nd = quintile_gap(down, "s_mr", ret)
    tag = econ_tag(gap, COST_A2, COST_A2)
    log.info(f"\n{'═'*90}\n  A2 — KINH TẾ MR-DOWN (DOWNTREND+DEEP_DOWN gộp)\n{'═'*90}")
    log.info(f"  n_days={r['n_days']}  IC={r['ic']:+.4f} t={r['t']:+.2f}")
    log.info(f"  gap={gap:+.3f}% vs phí bảo thủ {COST_A2}% → {tag}")
    report["A2"] = {"ic": r["ic"], "t": r["t"], "n_days": r["n_days"],
                    "gap": gap, "cost": COST_A2,
                    "exploitable": (not np.isnan(gap)) and abs(gap) > COST_A2}
    return report["A2"]


# ═══════════════════════════════════ A3 ════════════════════════════════
def run_a3(report, ret_lut, regime_map):
    files = sorted(glob.glob(str(LEDGER_DIR / "*.jsonl")))
    if not files:
        log.info(f"\n  A3 — sổ forward chưa có ({LEDGER_DIR}) → SKIP (bình thường).")
        report["A3"] = {"error": "no ledger"}; return
    recs = []
    for fp in files:
        with open(fp, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    try: recs.append(json.loads(line))
                    except json.JSONDecodeError: pass
    if not recs:
        report["A3"] = {"error": "empty ledger"}; return
    rd = pd.DataFrame(recs)
    s_keys = sorted([k for k in rd.columns if k.startswith("s_")])
    log.info(f"\n{'═'*90}\n  A3 — FLOW/FUND × REGIME (sổ forward — INDICATIVE, D1)\n{'═'*90}")
    log.info(f"  s_* keys phát hiện trong sổ: {s_keys}")
    if "signal_date" not in rd.columns:
        report["A3"] = {"error": "no signal_date"}; return
    rd["date"] = rd["signal_date"].astype(str)
    rd = rd.sort_values(rd.columns[rd.columns.get_loc("snap_time")] if "snap_time" in rd.columns else "date")
    rd = rd.groupby(["symbol", "date"], as_index=False).last()
    rd["ret"] = [ret_lut.get((s, d), np.nan) for s, d in zip(rd["symbol"], rd["date"])]
    rd["regime"] = rd["date"].map(regime_map)
    rd = rd.dropna(subset=["ret"])
    if rd.empty:
        log.info("  Không obs nào có forward return (parquet cũ hơn ngày record) → INDICATIVE trống.")
        report["A3"] = {"error": "no matured returns", "s_keys": s_keys}; return
    if "adtv_bil" in rd.columns:
        thr = rd.groupby("date")["adtv_bil"].transform(lambda s: s.quantile(HIGH_TIER_Q))
        rd = rd[rd["adtv_bil"] >= thr]
    flow_hint = ("ff", "prop", "insider", "of")
    fund_hint = ("fund", "growth")
    res = {}
    log.info(f"  {'signal':<14}{'fam':<6}" + "".join(f"{r[:8]:>10}" for r in REGIME_ORDER))
    for k in s_keys:
        rd[k] = pd.to_numeric(rd[k], errors="coerce")
        fam = "flow" if any(x in k for x in flow_hint) else ("fund" if any(x in k for x in fund_hint) else "-")
        cells, rr = "", {}
        for rg in REGIME_ORDER:
            sub = rd[rd["regime"] == rg]
            r = daily_ic(sub, k, "ret", exclude_zero=True)
            rr[rg] = {"ic": r["ic"], "n_days": r["n_days"]}
            mark = "" if r["n_days"] >= MIN_DAYS_BUCKET else "*"
            cells += (f"{r['ic']:>+9.3f}{mark}" if not np.isnan(r["ic"]) else f"{'·':>10}")
        res[k] = {"family": fam, "by_regime": rr}
        log.info(f"  {k:<14}{fam:<6}{cells}")
    log.info("  (* = <30 ngày, KHÔNG TIN — theo D1 mọi ô A3 là indicative)")
    report["A3"] = {"signals": res, "note": "INDICATIVE only (D1)"}


# ═══════════════════════════════════ A4 ════════════════════════════════
def run_a4(report, regime_map):
    ser = pd.Series(regime_map).sort_index()
    vals = ser.tolist()
    changes, runs, cur = 0, [], 1
    for i in range(1, len(vals)):
        if vals[i] != vals[i-1]:
            changes += 1; runs.append(cur); cur = 1
        else:
            cur += 1
    runs.append(cur)
    short = sum(1 for r in runs if r <= 2)
    pct_short = short / len(runs) * 100 if runs else 0
    need_hyst = pct_short > 20
    log.info(f"\n{'═'*90}\n  A4 — WHIPSAW REGIME\n{'═'*90}")
    log.info(f"  {len(vals)} ngày, {changes} lần đổi regime, {len(runs)} run")
    log.info(f"  độ dài run TB={np.mean(runs):.1f} phiên, run≤2 phiên: {short}/{len(runs)} ({pct_short:.0f}%)")
    log.info(f"  → {'CẦN hysteresis (>20% run ngắn)' if need_hyst else 'KHÔNG cần hysteresis'}")
    report["A4"] = {"changes": changes, "n_runs": len(runs),
                    "mean_run": float(np.mean(runs)), "pct_short": pct_short,
                    "need_hysteresis": need_hyst}


# ═══════════════════════════════ PROBE FF ══════════════════════════════
def run_probe_ff(report):
    Trading = _imp("Trading")
    log.info(f"\n{'═'*90}\n  PROBE — backfill FF lịch sử khả thi?\n{'═'*90}")
    if Trading is None:
        log.info("  Không import được Trading → bỏ probe.")
        report["probe_ff"] = {"error": "no Trading"}; return
    out = {}
    for sym in PROBE_SYMBOLS:
        info = {"ok": False}
        for src in ("VCI", "CafeF"):
            try:
                df = Trading(source=src, symbol=sym).foreign_trade()
                if df is not None and not df.empty:
                    tc = next((x for x in ("time","date","ngay","trading_date") if x in df.columns), None)
                    span = "?"
                    if tc:
                        dt = pd.to_datetime(df[tc], errors="coerce").dropna()
                        if len(dt):
                            span = f"{dt.min().date()}→{dt.max().date()} ({len(dt)} phiên)"
                    info = {"ok": True, "source": src, "rows": int(len(df)),
                            "cols": list(df.columns)[:8], "span": span}
                    break
            except Exception as e:
                info["err_" + src] = str(e)[:80]
        out[sym] = info
        log.info(f"  {sym}: {info}")
    feasible = any(v.get("ok") for v in out.values())
    log.info(f"  → backfill 16 tháng {'KHẢ THI' if feasible else 'CHƯA rõ'}; "
             f"chi phí ~1 call/mã × ~130 mã = ~130 call (1 lần, cache lại được).")
    report["probe_ff"] = {"symbols": out, "feasible": feasible}


# ═══════════════════════════ GATE v2 ĐỀ XUẤT ═══════════════════════════
def _breakout_alive(a1, regime, need_both_halves):
    """Đếm tín hiệu breakout SỐNG trong regime: verdict ALIVE + gap vượt phí +
    (nếu need_both_halves) dương CẢ 2 nửa. Trả (list qua, list ALIVE-nhưng-flip)."""
    passed, flip = [], []
    for sig in ("dist_52w", "ema_align", "supertrend_dir", "adx_dir"):
        v = a1.get(sig, {}).get(regime, {})
        if v.get("verdict") != "ALIVE":
            continue
        gap_ok = (not np.isnan(v.get("gap", np.nan))) and abs(v["gap"]) > COST_A1_HI
        if not gap_ok:
            continue
        if need_both_halves and v.get("both_pos") is False:
            flip.append(sig)
        else:
            passed.append(sig)
    return passed, flip


def suggest_gate(report):
    log.info(f"\n{'█'*72}\n  GATE v2 ĐỀ XUẤT (luật đăng ký trước + XÁC NHẬN 2 NỬA)\n{'█'*72}")
    a1 = report.get("A1", {}); a2 = report.get("A2", {}); a4 = report.get("A4", {})

    # ── SIDEWAYS breakout (phát hiện chính) ──
    sw_pass, sw_flip = _breakout_alive(a1, "SIDEWAYS", need_both_halves=True)
    if len(sw_pass) >= 2:
        g_break_side = 1.0
        log.info(f"  • SIDEWAYS: breakout SỐNG + vượt phí + dương 2 nửa ({sw_pass}) "
                 f"→ gate breakout SIDEWAYS = 1.0 (bằng chứng vững nhất bảng).")
    elif sw_pass:
        g_break_side = 1.0
        log.info(f"  • SIDEWAYS: chỉ {sw_pass} qua đủ chuẩn (số ít) → gate=1.0 nhưng theo dõi.")
    else:
        g_break_side = 0.5
        log.info(f"  • SIDEWAYS: breakout chưa qua 2-nửa (flip: {sw_flip}) → tạm 0.5, chờ thêm.")

    # ── UPTREND breakout ──
    up_pass, up_flip = _breakout_alive(a1, "UPTREND", need_both_halves=True)
    if up_pass:
        g_break_up = 1.0
        log.info(f"  • UPTREND: {up_pass} qua CẢ 2 nửa → gate UP = 1.0.")
        up_verdict = "edge"
    elif up_flip:
        g_break_up = 0.5
        log.info(f"  • UPTREND: {up_flip} ALIVE nhưng CHỈ dương nửa sau (chưa chắc) "
                 f"→ gate UP = 0.5 (nửa liều, không nhồi).")
        up_verdict = "half"
    else:
        g_break_up = 0.5
        log.info("  • UPTREND: không tín hiệu trend nào qua 2 nửa → gate UP = 0.5 (dist_52w "
                 "vốn đã trong V3, giữ nửa liều); uptrend gần như im lặng (Cách B).")
        up_verdict = "silent"

    # ── DOWN breakout: tắt nếu trend âm rõ (t≤-2) ──
    down_neg = all((a1.get(s, {}).get("DOWNTREND", {}).get("t") or 0) <= -2
                   for s in ("ema_align", "adx_dir", "trend_mom"))
    g_break_down = 0.0 if down_neg else 1.0
    log.info(f"  • DOWN/DEEP: breakout {'ÂM rõ → gate = 0.0 (đối xứng MR)' if down_neg else 'chưa rõ → giữ 1.0'}.")

    # ── MR-down ──
    mr_ok = a2.get("exploitable")
    log.info(f"  • MR-down: gap {a2.get('gap'):+.3f}% "
             f"{'> ' if mr_ok else '≤ '}{COST_A2}% → "
             f"{'PHÁT LỆNH được, gate DOWN/DEEP=1.0' if mr_ok else 'chỉ screening'}.")

    # ── hysteresis ──
    hyst = a4.get("need_hysteresis")
    log.info(f"  • Regime: {a4.get('pct_short',0):.0f}% run ngắn → "
             f"{'THÊM hysteresis 2 phiên' if hyst else 'không cần hysteresis'}.")

    # ── in ma trận GATE v2 cụ thể ──
    log.info(f"\n  ┌─ MA TRẬN GATE v2 ĐỀ XUẤT ─────────────────────────────")
    log.info(f"  │ {'factor':<15}{'UP':>6}{'SIDE':>6}{'DOWN':>6}{'DEEP':>6}")
    log.info(f"  │ {'mean_reversion':<15}{0.0:>6}{0.0:>6}"
             f"{(1.0 if mr_ok else 1.0):>6}{(1.0 if mr_ok else 1.0):>6}   ← A2")
    log.info(f"  │ {'breakout':<15}{g_break_up:>6}{g_break_side:>6}"
             f"{g_break_down:>6}{g_break_down:>6}   ← A1")
    log.info(f"  │ {'flow/fund/growth':<15}{1.0:>6}{1.0:>6}{1.0:>6}{1.0:>6}   inherited (A3 trống)")
    log.info(f"  └────────────────────────────────────────────────────────")

    report["gate_v2_suggestion"] = {
        "mean_reversion": {"UPTREND": 0.0, "SIDEWAYS": 0.0,
                           "DOWNTREND": 1.0, "DEEP_DOWN": 1.0},
        "breakout": {"UPTREND": g_break_up, "SIDEWAYS": g_break_side,
                     "DOWNTREND": g_break_down, "DEEP_DOWN": g_break_down},
        "uptrend_verdict": up_verdict, "mr_down_exploitable": mr_ok,
        "hysteresis": hyst,
        "sideways_breakout_pass": sw_pass, "sideways_breakout_flip": sw_flip}
    log.info(f"{'█'*72}")


# ═══════════════════════════════════ MAIN ══════════════════════════════
def main():
    log.info("=" * 72)
    log.info("  PHASE A — đo lấp ma trận GATE (V4 RCEG)")
    log.info(f"  Sổ test tích luỹ: +~21 test | ngưỡng: |t|≥{IC_T_MIN}, n≥{MIN_DAYS_BUCKET}, "
             f"phí A2={COST_A2}%")
    log.info("=" * 72)
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    report = {"generated_at": datetime.now().isoformat(timespec="seconds"),
              "params": {"horizon": HORIZON, "cost_a2": COST_A2,
                         "min_days": MIN_DAYS_BUCKET, "t_min": IC_T_MIN}}
    if not PARQUET.exists():
        log.error(f"❌ {PARQUET} thiếu."); return
    df = pd.read_parquet(PARQUET)
    df["time"] = pd.to_datetime(df["time"])
    parts = [compute_indicators(g) for _, g in df.groupby("symbol")]
    df = pd.concat(parts, ignore_index=True)
    df["date"] = df["time"].dt.strftime("%Y-%m-%d")

    vn = fetch_vnindex()
    if vn is None:
        log.error("❌ Không có VNINDEX → không gán regime → dừng."); return
    regime_map, vnret20 = build_regime(vn)
    df = add_mr(df, vnret20)
    df["regime"] = df["date"].map(regime_map)

    thr = df.groupby("date")["adtv"].transform(lambda s: s.quantile(HIGH_TIER_Q))
    hi = df[df["adtv"] >= thr].dropna(subset=["regime"]).copy()
    dist = pd.Series({d: regime_map[d] for d in hi["date"].unique()}).value_counts()
    log.info(f"tier liquid: {len(hi):,} obs, {hi['date'].nunique()} ngày | regime days: {dist.to_dict()}")

    ret = f"ret_{HORIZON}d"
    ret_lut = {(r.symbol, r.date): getattr(r, ret)
               for r in df[["symbol", "date", ret]].itertuples(index=False)}

    run_a1(report, hi)
    run_a2(report, hi)
    run_a3(report, ret_lut, regime_map)
    run_a4(report, regime_map)
    run_probe_ff(report)
    suggest_gate(report)

    out = REPORT_DIR / f"phase_a_{datetime.now():%Y%m%d}.json"
    with open(out, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2, default=str)
    log.info(f"\nĐã ghi → {out}")


if __name__ == "__main__":
    main()
