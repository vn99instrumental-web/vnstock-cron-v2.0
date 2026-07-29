"""
scripts/diag_mr_regime_v2f.py — MR theo CHẾ ĐỘ THỊ TRƯỜNG (regime × valuation)
==============================================================================
MỤC ĐÍCH (#1 nối tiếp): survival check đã chứng minh MR CHẾT toàn cục trên
rổ liquid, nhưng chết vì "sai mùa" (dương nửa đầu, âm nửa sau). Câu hỏi kế:
  MR có sống trong ĐÚNG chế độ của nó (SIDEWAYS) không? Nếu có → GATE theo
  regime (giữ MR, chỉ bật khi ngang) thay vì đưa weight về 0.

ĐO 3 CÁCH GỘP (kèm ĐẾM NGÀY mỗi ô — để tự thấy ô nào quá thưa, khỏi đoán):
  (a) regime đơn      : 4 ô  (UPTREND/SIDEWAYS/DOWNTREND/DEEP_DOWN)
  (b) valuation đơn   : 3 ô  (CHEAP/FAIR/EXPENSIVE)
  (c) combined        : tối đa 12 ô (regime × valuation)

NHÃN = THẬT (tái tạo đúng logic production, KHÔNG proxy):
  regime    : VNINDEX close vs EMA50/EMA200 + đà 5d/20d — copy nguyên luật
              step3_context._vnindex_trend() (bản refined 2026-06-04)
  valuation : percentile PE+PB 5Y của VNINDEX, point-in-time (trailing 5Y
              tính tới từng ngày, KHÔNG nhìn tương lai) — copy luật
              _valuation_label (<30% CHEAP / >70% EXPENSIVE / else FAIR)
  → cần 2 lần fetch VNINDEX (OHLCV + evaluation 5Y). Fetch lỗi → degrade:
    VNINDEX OHLCV lỗi  → bỏ toàn bộ Part R (regime là trục chính, không có
                         thì vô nghĩa).
    evaluation lỗi/không có cột ngày → chỉ chạy (a) regime, bỏ (b)(c).

ĐIỂM MR = ĐÚNG điểm production (số nguyên), gộp 4 tín hiệu:
  s_mr = sc_willr + sc_bb + sc_overext + sc_rs_rev   (∈ ~[-20, +20])
  Đo IC của CHÍNH thứ engine cộng vào score → quyết định trực tiếp việc gate.

ISOLATION: KHÔNG import utils/steps/config. Được phép import vnstock (thư viện
  data, không phải production module) để fetch VNINDEX — giống bt_data.py.
  Chỉ đọc parquet, chỉ ghi backtest_output/reports/.

TIÊU CHÍ ĐĂNG KÝ TRƯỚC (hard-code, không sửa sau khi thấy số):
  MIN_DAYS_BUCKET = 30  → ô < 30 ngày IC = "THƯA — KHÔNG TIN"
  Trong ô đủ dày:  ALIVE nếu IC>0 & |t|>=2.0 ; DEAD nếu IC<=0 ; else WEAK
  Kết luận gate: chỉ đề xuất GATE regime nếu MR ALIVE ở SIDEWAYS VÀ
                 DEAD/không-ALIVE ở các regime trending (đủ dày).

TRIGGER: debug.yml → script = scripts/diag_mr_regime_v2f.py

CHANGELOG:
  v1 (2026-07-29) — initial.
"""
import sys
import json
import math
import logging
from datetime import datetime
from pathlib import Path

for _mod in list(sys.modules.keys()):
    if _mod.startswith(("utils.", "steps.")) or _mod == "config":
        raise RuntimeError(f"ISOLATION VIOLATION: {_mod} đã import.")

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

# ── Tham số đăng ký trước ─────────────────────────────────────────────
HORIZON         = 5
ADTV_WINDOW     = 20
HIGH_TIER_Q     = 2 / 3
MIN_SYM_TIER    = 15
MIN_DAYS_BUCKET = 30
IC_T_MIN        = 2.0

REGIME_ORDER = ["UPTREND", "SIDEWAYS", "DOWNTREND", "DEEP_DOWN"]
VAL_ORDER    = ["CHEAP", "FAIR", "EXPENSIVE"]


# ══════════════════════════════════════════════════════════════════════
# THỐNG KÊ
# ══════════════════════════════════════════════════════════════════════

def _spearman(x, y):
    if len(x) < 3:
        return np.nan
    rx = pd.Series(x).rank().to_numpy()
    ry = pd.Series(y).rank().to_numpy()
    if np.std(rx) == 0 or np.std(ry) == 0:
        return np.nan
    return float(np.corrcoef(rx, ry)[0, 1])


def daily_ic(df, sig, ret, exclude_zero=True, min_sym=MIN_SYM_TIER):
    ics = []
    n_obs = 0
    for _, g in df.groupby("date"):
        sub = g[[sig, ret]].dropna()
        if exclude_zero:
            sub = sub[sub[sig] != 0]
        if len(sub) < min_sym:
            continue
        ic = _spearman(sub[sig].to_numpy(), sub[ret].to_numpy())
        if not np.isnan(ic):
            ics.append(ic)
            n_obs += len(sub)
    if not ics:
        return {"ic": np.nan, "t": np.nan, "n_days": 0, "n_obs": 0}
    a = np.array(ics)
    m = float(a.mean())
    sd = float(a.std(ddof=1)) if len(a) > 1 else np.nan
    t = (m / sd * math.sqrt(len(a))) if sd and sd > 0 else np.nan
    return {"ic": m, "t": t, "n_days": len(a), "n_obs": n_obs}


def bucket_verdict(r):
    if r["n_days"] < MIN_DAYS_BUCKET:
        return f"THƯA (n={r['n_days']}<{MIN_DAYS_BUCKET}) — KHÔNG TIN"
    if np.isnan(r["ic"]):
        return "n/a"
    if r["ic"] <= 0:
        return "DEAD"
    if abs(r["t"]) >= IC_T_MIN:
        return "ALIVE"
    return "WEAK"


# ══════════════════════════════════════════════════════════════════════
# INDICATORS + ĐIỂM MR SỐ NGUYÊN (đúng ngưỡng production)
# ══════════════════════════════════════════════════════════════════════

def compute_indicators(g):
    g = g.sort_values("time").copy()
    c, h, l, v = g["close"], g["high"], g["low"], g["volume"]
    hh = h.rolling(14).max(); ll = l.rolling(14).min()
    g["willr_14"] = -100 * (hh - c) / (hh - ll).replace(0, np.nan)
    mid = c.rolling(20).mean(); sd = c.rolling(20).std(ddof=0)
    g["bb_position"] = (c - (mid - 2 * sd)) / ((mid + 2 * sd) - (mid - 2 * sd)).replace(0, np.nan)
    ema200 = c.ewm(span=200, adjust=False, min_periods=200).mean()
    g["price_vs_ema200_pct"] = (c - ema200) / ema200 * 100
    g["return_20d_pct"] = (c / c.shift(20) - 1) * 100
    g[f"ret_{HORIZON}d"] = (c.shift(-HORIZON) / c - 1) * 100
    g["adtv"] = (c * v).rolling(ADTV_WINDOW).mean()
    return g


def _sc_willr(wr):
    if pd.isna(wr): return 0
    if wr <= -90: return 6
    if wr <= -80: return 4
    if wr <= -60: return 2
    if wr >= -10: return -6
    if wr >= -20: return -4
    if wr >= -40: return -2
    return 0


def _sc_bb(bb):
    if pd.isna(bb): return 0
    if bb < 0.10: return 5
    if bb < 0.20: return 3
    if bb > 0.90: return -5
    if bb > 0.80: return -3
    return 0


def _sc_overext(d):
    if pd.isna(d): return 0
    if d > 15: return -5
    if d > 8:  return -3
    if d > 3:  return -1
    if d < -15: return 5
    if d < -8:  return 3
    if d < -3:  return 1
    return 0


def _sc_rs_rev(rs):
    if pd.isna(rs): return 0
    if rs > 1.30: return -4
    if rs > 1.10: return -2
    if rs < 0.70: return 4
    if rs < 0.90: return 2
    return 0


def add_mr_scores(df, vnidx_ret20_map):
    """Thêm điểm production số nguyên cho 4 tín hiệu MR + s_mr tổng.
    rs dùng return VNINDEX THẬT theo ngày (không proxy median)."""
    df = df.copy()
    df["s_willr"]   = df["willr_14"].map(_sc_willr)
    df["s_bb"]      = df["bb_position"].map(_sc_bb)
    df["s_overext"] = df["price_vs_ema200_pct"].map(_sc_overext)
    vr = df["date"].map(vnidx_ret20_map)
    rs = (1 + df["return_20d_pct"] / 100) / (1 + vr / 100)
    df["s_rs_rev"]  = rs.map(_sc_rs_rev)
    df["s_mr"] = df[["s_willr", "s_bb", "s_overext", "s_rs_rev"]].sum(axis=1)
    return df


# ══════════════════════════════════════════════════════════════════════
# FETCH + NHÃN VNINDEX (regime + valuation) — tái tạo đúng production
# ══════════════════════════════════════════════════════════════════════

def _import_quote():
    try:
        from vnstock import Quote
        return Quote
    except Exception:
        try:
            from vnstock_data import Quote
            return Quote
        except Exception:
            return None


def _import_analytics():
    for path in ("vnstock_data", "vnstock"):
        try:
            mod = __import__(path, fromlist=["Analytics"])
            return getattr(mod, "Analytics")
        except Exception:
            continue
    return None


def fetch_vnindex_ohlcv():
    Quote = _import_quote()
    if Quote is None:
        log.warning("[R] Không import được Quote — bỏ Part R.")
        return None
    for length in ("36M", "24M", "18M"):
        try:
            df = Quote(source="VCI", symbol="VNINDEX").history(
                length=length, interval="1D")
            if df is not None and not df.empty and "close" in df.columns:
                df = df.copy()
                tcol = "time" if "time" in df.columns else df.columns[0]
                df["time"] = pd.to_datetime(df[tcol])
                df["close"] = pd.to_numeric(df["close"], errors="coerce")
                df = df.dropna(subset=["close"]).sort_values("time")
                log.info(f"[R] VNINDEX OHLCV: {len(df)} phiên "
                         f"{df['time'].min().date()} → {df['time'].max().date()}")
                return df[["time", "close"]]
        except Exception as e:
            log.warning(f"[R] fetch VNINDEX length={length} lỗi: {e}")
    return None


def build_regime_map(vnidx):
    """Copy nguyên luật step3_context._vnindex_trend (refined 2026-06-04),
    áp cho TỪNG ngày (EWM adjust=False là causal → nhãn point-in-time đúng)."""
    v = vnidx.copy().reset_index(drop=True)
    c = v["close"]
    ema50  = c.ewm(span=50, adjust=False).mean()
    ema200 = c.ewm(span=200, adjust=False, min_periods=200).mean()
    chg5   = (c / c.shift(5) - 1) * 100
    chg20  = (c / c.shift(20) - 1) * 100
    regime, ret20 = {}, {}
    for i in range(len(v)):
        d = v["time"].iloc[i].strftime("%Y-%m-%d")
        ret20[d] = float(chg20.iloc[i]) if not pd.isna(chg20.iloc[i]) else np.nan
        cl = c.iloc[i]; e50 = ema50.iloc[i]; e200 = ema200.iloc[i]
        above_50 = cl > e50
        above_200 = (cl > e200) if not pd.isna(e200) else above_50
        c5 = chg5.iloc[i] if not pd.isna(chg5.iloc[i]) else 0.0
        c20 = chg20.iloc[i] if not pd.isna(chg20.iloc[i]) else 0.0
        if ((not above_50) and (not above_200)) or c20 <= -8:
            rg = "DEEP_DOWN"
        elif (not above_50) and (c20 <= -2 or c5 <= -3):
            rg = "DOWNTREND"
        elif above_50 and above_200 and c20 > 0:
            rg = "UPTREND"
        else:
            rg = "SIDEWAYS"
        regime[d] = rg
    return regime, ret20


def fetch_valuation_map(dates_needed):
    """Percentile PE+PB 5Y point-in-time cho từng ngày. Trả {} nếu không
    lấy được chuỗi có cột ngày (khi đó bỏ (b)(c), giữ (a))."""
    Analytics = _import_analytics()
    if Analytics is None:
        log.warning("[R] Không import được Analytics — bỏ valuation (b)(c).")
        return {}
    try:
        dfe = Analytics().valuation("VNINDEX").evaluation(duration="5Y")
    except Exception as e:
        log.warning(f"[R] fetch valuation lỗi: {e} — bỏ (b)(c).")
        return {}
    if dfe is None or dfe.empty or "pe" not in dfe.columns or "pb" not in dfe.columns:
        log.warning("[R] evaluation thiếu cột pe/pb — bỏ (b)(c).")
        return {}
    # tìm cột ngày
    dcol = next((x for x in ("time", "date", "ngay", "trading_date")
                 if x in dfe.columns), None)
    if dcol is None:
        log.warning("[R] evaluation KHÔNG có cột ngày → không point-in-time "
                    "được → bỏ (b)(c).")
        return {}
    dfe = dfe.copy()
    dfe["time"] = pd.to_datetime(dfe[dcol])
    dfe["pe"] = pd.to_numeric(dfe["pe"], errors="coerce")
    dfe["pb"] = pd.to_numeric(dfe["pb"], errors="coerce")
    dfe = dfe.dropna(subset=["pe", "pb"]).sort_values("time").reset_index(drop=True)
    WIN = 1250  # ~5 năm giao dịch
    labels = {}
    for i in range(len(dfe)):
        lo = max(0, i - WIN + 1)
        pe_w = dfe["pe"].iloc[lo:i + 1]
        pb_w = dfe["pb"].iloc[lo:i + 1]
        pe_pct = float((pe_w <= dfe["pe"].iloc[i]).mean())
        pb_pct = float((pb_w <= dfe["pb"].iloc[i]).mean())
        avg = (pe_pct + pb_pct) / 2
        lab = "CHEAP" if avg < 0.30 else ("EXPENSIVE" if avg > 0.70 else "FAIR")
        labels[dfe["time"].iloc[i].strftime("%Y-%m-%d")] = lab
    # forward-fill sang mọi ngày backtest cần (valuation ít đổi)
    ser = pd.Series(labels).sort_index()
    out = {}
    for d in sorted(dates_needed):
        prior = ser[ser.index <= d]
        if len(prior):
            out[d] = prior.iloc[-1]
    log.info(f"[R] valuation gán được {len(out)}/{len(dates_needed)} ngày backtest")
    return out


# ══════════════════════════════════════════════════════════════════════
# PART R — IC theo ô
# ══════════════════════════════════════════════════════════════════════

def _bucket_table(df, group_col, order, ret, sig="s_mr"):
    rows = []
    for b in order:
        sub = df[df[group_col] == b]
        r = daily_ic(sub, sig, ret, exclude_zero=True)
        rows.append({"bucket": b, **r, "verdict": bucket_verdict(r)})
    return rows


def run_part_r(report, df_hi, regime_map, val_map):
    ret = f"ret_{HORIZON}d"
    df = df_hi.copy()
    df["regime"] = df["date"].map(regime_map)
    df = df[df["regime"].notna()]
    has_val = bool(val_map)
    if has_val:
        df["valuation"] = df["date"].map(val_map)

    # (a) regime đơn
    log.info(f"\n{'═'*84}\n  (a) MR theo REGIME — điểm s_mr, IC {HORIZON}d, tier CAO\n{'═'*84}")
    log.info(f"{'regime':<12}{'IC':>9}{'t':>7}{'n_days':>8}{'n_obs':>8}  verdict")
    log.info("─" * 84)
    ta = _bucket_table(df, "regime", REGIME_ORDER, ret)
    for r in ta:
        log.info(f"{r['bucket']:<12}{r['ic']:>+9.4f}{r['t']:>+7.2f}"
                 f"{r['n_days']:>8}{r['n_obs']:>8}  {r['verdict']}")

    # per-signal theo regime (chi tiết — để biết gate cả nhóm hay tỉa lẻ)
    log.info(f"\n{'─'*84}\n  Chi tiết per-signal theo regime (IC {HORIZON}d)\n{'─'*84}")
    hdr = f"{'signal':<10}" + "".join(f"{rg[:8]:>11}" for rg in REGIME_ORDER)
    log.info(hdr); log.info("─" * 84)
    per_sig = {}
    for sig in ["s_willr", "s_bb", "s_overext", "s_rs_rev"]:
        cells, rowrec = "", {}
        for rg in REGIME_ORDER:
            sub = df[df["regime"] == rg]
            r = daily_ic(sub, sig, ret, exclude_zero=True)
            rowrec[rg] = r
            mark = "" if r["n_days"] >= MIN_DAYS_BUCKET else "*"
            cells += f"{r['ic']:>+10.4f}{mark}" if not np.isnan(r["ic"]) else f"{'n/a':>11}"
        per_sig[sig] = rowrec
        log.info(f"{sig:<10}{cells}")
    log.info("(* = ô < 30 ngày, không tin)")

    # (b) valuation đơn + (c) combined
    tb, tc = [], []
    if has_val:
        log.info(f"\n{'═'*84}\n  (b) MR theo VALUATION — s_mr, IC {HORIZON}d\n{'═'*84}")
        log.info(f"{'valuation':<12}{'IC':>9}{'t':>7}{'n_days':>8}{'n_obs':>8}  verdict")
        log.info("─" * 84)
        tb = _bucket_table(df, "valuation", VAL_ORDER, ret)
        for r in tb:
            log.info(f"{r['bucket']:<12}{r['ic']:>+9.4f}{r['t']:>+7.2f}"
                     f"{r['n_days']:>8}{r['n_obs']:>8}  {r['verdict']}")

        log.info(f"\n{'═'*84}\n  (c) COMBINED regime × valuation — s_mr (CẢNH BÁO: nhiều ô THƯA)\n{'═'*84}")
        log.info(f"{'regime':<12}{'valuation':<11}{'IC':>9}{'t':>7}{'n_days':>8}  verdict")
        log.info("─" * 84)
        df["combo"] = df["regime"] + " | " + df["valuation"]
        for rg in REGIME_ORDER:
            for val in VAL_ORDER:
                sub = df[(df["regime"] == rg) & (df["valuation"] == val)]
                r = daily_ic(sub, "s_mr", ret, exclude_zero=True)
                vd = bucket_verdict(r)
                tc.append({"regime": rg, "valuation": val, **r, "verdict": vd})
                log.info(f"{rg:<12}{val:<11}{r['ic']:>+9.4f}{r['t']:>+7.2f}"
                         f"{r['n_days']:>8}  {vd}")
    else:
        log.info("\n[R] (b)(c) BỎ QUA — không lấy được nhãn valuation point-in-time.")

    report["part_r"] = {
        "regime": ta,
        "per_signal_by_regime": {
            s: {rg: {k: rr[rg][k] for k in ("ic", "t", "n_days", "n_obs")}
                for rg in REGIME_ORDER}
            for s, rr in per_sig.items()},
        "valuation": tb,
        "combined": tc,
        "has_valuation": has_val,
    }
    return ta


def plain_summary(ta):
    def find(rg):
        return next((r for r in ta if r["bucket"] == rg), None)
    sw = find("SIDEWAYS")
    trending = [find(x) for x in ("UPTREND", "DOWNTREND", "DEEP_DOWN")]
    log.info(f"\n{'█'*72}\n  KẾT LUẬN (dễ hiểu) — GATE regime hay ZERO?\n{'█'*72}")
    if sw is None or sw["n_days"] < MIN_DAYS_BUCKET:
        log.info("  Ô SIDEWAYS quá thưa để tin → chưa đủ cơ sở gate. Nghiêng ZERO.")
    else:
        sw_alive = sw["verdict"] == "ALIVE"
        trend_ok = all((t is None or t["n_days"] < MIN_DAYS_BUCKET
                        or t["verdict"] in ("DEAD", "WEAK")) for t in trending)
        log.info(f"  SIDEWAYS: IC={sw['ic']:+.4f} t={sw['t']:+.2f} "
                 f"n={sw['n_days']} → {sw['verdict']}")
        for t in trending:
            if t:
                log.info(f"  {t['bucket']:<10}: IC={t['ic']:+.4f} "
                         f"t={t['t']:+.2f} n={t['n_days']} → {t['verdict']}")
        if sw_alive and trend_ok:
            log.info("\n  ⇒ GATE HỢP LÝ: MR sống ở SIDEWAYS, chết/yếu khi trending.")
            log.info("    → giữ MR nhưng chỉ bật khi regime=SIDEWAYS "
                     "(UPTREND ×0.5 tuỳ chọn, DOWNTREND/DEEP_DOWN ×0).")
        elif not sw_alive:
            log.info("\n  ⇒ ZERO: MR KHÔNG sống kể cả ở SIDEWAYS trên rổ liquid → "
                     "gate không cứu được, đưa weight MR về 0.")
        else:
            log.info("\n  ⇒ HỖN HỢP: xem bảng per-signal — có thể chỉ gate/tỉa "
                     "vài tín hiệu thay vì cả nhóm.")
    log.info(f"{'█'*72}")


def main():
    log.info("=" * 72)
    log.info("  MR × REGIME/VALUATION trên rổ liquid (proxy V2F)")
    log.info(f"  Đăng ký trước: ô <{MIN_DAYS_BUCKET} ngày = KHÔNG TIN; "
             f"ALIVE cần IC>0 & |t|>={IC_T_MIN}")
    log.info("=" * 72)
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    report = {"generated_at": datetime.now().isoformat(timespec="seconds")}

    if not PARQUET.exists():
        log.error(f"❌ {PARQUET} thiếu — chạy bt_data.py trước.")
        return
    df = pd.read_parquet(PARQUET)
    df["time"] = pd.to_datetime(df["time"])
    parts = [compute_indicators(g) for _, g in df.groupby("symbol")]
    df = pd.concat(parts, ignore_index=True)
    df["date"] = df["time"].dt.strftime("%Y-%m-%d")

    vnidx = fetch_vnindex_ohlcv()
    if vnidx is None:
        log.error("❌ Không có VNINDEX → không gán regime → Part R vô nghĩa. Dừng.")
        return
    regime_map, vnidx_ret20 = build_regime_map(vnidx)
    df = add_mr_scores(df, vnidx_ret20)

    # tier CAO theo ADTV trong ngày
    thr = df.groupby("date")["adtv"].transform(lambda s: s.quantile(HIGH_TIER_Q))
    df_hi = df[df["adtv"] >= thr].copy()
    log.info(f"[R] tier CAO: {len(df_hi):,} obs, {df_hi['date'].nunique()} ngày")

    dist = pd.Series({d: regime_map.get(d) for d in df_hi["date"].unique()}).value_counts()
    log.info(f"[R] phân bố regime (ngày): {dist.to_dict()}")

    val_map = fetch_valuation_map(set(df_hi["date"].unique()))
    ta = run_part_r(report, df_hi, regime_map, val_map)
    plain_summary(ta)

    stamp = datetime.now().strftime("%Y%m%d")
    out = REPORT_DIR / f"mr_regime_{stamp}.json"
    with open(out, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2, default=str)
    log.info(f"\nĐã ghi → {out}")


if __name__ == "__main__":
    main()
