"""
scripts/diag_regime_op2.py — Đo bằng chứng cho regime "Op2" (m2 = đà hôm nay live)
================================================================================
Mục tiêu: THAY 3 con số neo lý thuyết bằng số đo thật, TRƯỚC khi đụng code.

Chốt thiết kế (từ hội thoại):
  - Op2: m2 = r_hôm_nay_live  (bỏ hôm qua) — nhanh nhất bắt thị trường quay đầu.
  - Map vào 5 trạng thái, m2 thay TRỤC ĐÀ NGẮN; giữ trục vị trí (giá vs EMA50/200)
    và chg_20d cho DOWN-trung-hạn + crash (đọc từ steps/step3_context.py).

Script này CHỈ ĐỌC — không ghi file, không đụng production. Fail-soft toàn bộ.

Đo 3 việc:
  [1] Phân phối đà VNINDEX (percentile) trên ~12M phiên thật
      → đối chiếu ngưỡng neo lý thuyết TH_UP=+1.3 / TH_DOWN=-1.9 rơi vào phân vị nào.
  [2] So regime Op2 (5 trạng thái, m2 thay đà ngắn) vs regime PRODUCTION
      (step3_context, 4 trạng thái, dùng chg_5d) trên cùng chuỗi EOD:
      khác nhau bao nhiêu %, mỗi bên lật (close-to-close) bao nhiêu lần.
      Kèm Op3 (w=0.4) và Op4/Op1 (w=1) để so tốc độ lật.
  [3] Whipsaw TRONG NGÀY: cần bar intraday theo giờ. Repo chưa từng fetch bar
      intraday lịch sử → script DÒ history(interval=...) rồi fallback intraday()
      của phiên hiện tại. Nếu không có → báo rõ, không bịa.

Chạy: python scripts/diag_regime_op2.py
debug.yml: nhập input script = scripts/diag_regime_op2.py
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
os.environ["VNSTOCK_INTERACTIVE"] = "0"
os.environ["VNSTOCK_LANGUAGE"]    = "en"
os.environ["MPLCONFIGDIR"]        = "/home/runner/.config/matplotlib"
os.makedirs("/home/runner/.vnstock",           exist_ok=True)
os.makedirs("/home/runner/.config/matplotlib", exist_ok=True)

import json
import logging
from collections import Counter

import pandas as pd

logging.basicConfig(level=logging.INFO, format="%(message)s")
log = logging.getLogger("diag_regime_op2")

# ── Ngưỡng neo lý thuyết đang cân nhắc (script sẽ đối chiếu với phân vị thật) ──
TH_UP   = 1.3    # enter RECOVERY            (m2 >= TH_UP)  — UPTREND KHÔNG dùng m2 nữa
TH_DOWN = -1.3   # enter DOWNTREND nhanh      (m2 <= TH_DOWN) — nới từ -1.9 (chỉ 5.7% phiên)

HOUR_BUCKETS = [("sáng ≤10:30", 0, 630),
                ("trưa 10:31–13:29", 631, 809),
                ("chiều ≥13:30", 810, 1440)]


def pct(series, qs=(0.05, 0.10, 0.25, 0.50, 0.75, 0.90, 0.95)):
    s = pd.Series(series).dropna()
    if s.empty:
        return {}
    q = s.quantile(list(qs))
    return {f"p{int(x*100)}": round(float(q.loc[x]), 3) for x in qs}


# ── Classifier PRODUCTION (nguyên si steps/step3_context.py — 4 trạng thái) ──
def classify_prod(close, ema50, ema200, c5, c20):
    above_50  = close > ema50
    above_200 = (close > ema200) if ema200 is not None else above_50
    if ((not above_50) and (not above_200)) or c20 <= -8:
        return "DEEP_DOWN"
    if (not above_50) and (c20 <= -2 or c5 <= -3):
        return "DOWNTREND"
    if above_50 and above_200 and c20 > 0:
        return "UPTREND"
    return "SIDEWAYS"


# ── Classifier ĐỀ XUẤT Op2 (5 trạng thái; m2 thay đà ngắn; giữ c20 cho crash/DOWN-TB) ──
def classify_op2(close, ema50, ema200, m2, c20):
    above_50  = close > ema50
    above_200 = (close > ema200) if ema200 is not None else above_50
    if ((not above_50) and (not above_200) and m2 <= 0) or c20 <= -8:
        return "DEEP_DOWN"
    if (not above_50) and m2 >= TH_UP:
        return "RECOVERY"
    if (not above_50) and (c20 <= -2 or m2 <= TH_DOWN):
        return "DOWNTREND"
    if above_50 and above_200 and c20 > 0:   # ĐỔI: dùng đà-20-phiên, KHÔNG dùng m2
        return "UPTREND"                       # (m2 đà-1-phiên làm UPTREND biến mất)
    return "SIDEWAYS"


def count_flips(states):
    """Số lần trạng thái đổi giữa 2 phần tử liên tiếp."""
    return sum(1 for a, b in zip(states, states[1:]) if a != b)


def fetch_vnindex_daily():
    from vnstock_data import Quote
    for attempt in range(3):
        try:
            df = Quote(source="VCI", symbol="VNINDEX").history(length="12M", interval="1D")
            if df is not None and not df.empty:
                return df
        except Exception as e:
            log.warning(f"  daily fetch attempt {attempt+1}/3 lỗi: {e}")
        time.sleep(1.0)
    return None


def try_fetch_intraday_bars():
    """DÒ bar intraday lịch sử. Trả (df, mô_tả) hoặc (None, lý_do)."""
    from vnstock_data import Quote
    trials = [
        ("history interval=1H length=1M",   lambda: Quote(source="VCI", symbol="VNINDEX").history(length="1M", interval="1H")),
        ("history interval=15m length=10D", lambda: Quote(source="VCI", symbol="VNINDEX").history(length="10D", interval="15m")),
        ("history interval=15 length=10D",  lambda: Quote(source="VCI", symbol="VNINDEX").history(length="10D", interval="15")),
    ]
    for desc, fn in trials:
        try:
            df = fn()
            if df is not None and not df.empty and "time" in df.columns:
                ts = pd.to_datetime(df["time"], errors="coerce")
                ndays = ts.dt.date.nunique()
                intraday_like = ts.dt.hour.nunique() > 1  # có nhiều giờ trong ngày
                if intraday_like and ndays >= 2:
                    log.info(f"  ✓ bar intraday qua: {desc} ({len(df)} bar / {ndays} ngày)")
                    return df.assign(_ts=ts), desc
        except Exception as e:
            log.info(f"  ✗ {desc}: {e}")
        time.sleep(0.6)
    return None, "history không trả bar intraday lịch sử"


def try_fetch_intraday_ticks_today():
    """Fallback: tick phiên hiện tại → resample theo giờ (chỉ 1 ngày)."""
    from vnstock_data import Quote
    try:
        df = Quote(source="VCI", symbol="VNINDEX").intraday(page_size=10000)
        if df is not None and not df.empty:
            return df
    except Exception as e:
        log.info(f"  ✗ intraday() ticks: {e}")
    return None


def main():
    log.info("=" * 70)
    log.info("DIAG regime Op2 — đo bằng chứng trước khi đổi code (READ-ONLY)")
    log.info(f"Ngưỡng đang cân nhắc: TH_UP=+{TH_UP}  TH_DOWN={TH_DOWN}")
    log.info("=" * 70)

    df = fetch_vnindex_daily()
    if df is None or df.empty or len(df) < 220:
        log.error("Không lấy được daily VNINDEX đủ dài (>=220 phiên). Dừng.")
        return

    df = df.copy()
    df["close"] = pd.to_numeric(df["close"], errors="coerce")
    df = df.dropna(subset=["close"]).reset_index(drop=True)
    c = df["close"]
    ema50  = c.ewm(span=50,  adjust=False).mean()
    ema200 = c.ewm(span=200, adjust=False).mean()
    r1d = c.pct_change() * 100.0                        # đà 1 phiên (close-to-close)
    c5  = (c / c.shift(5)  - 1) * 100.0
    c20 = (c / c.shift(20) - 1) * 100.0

    n = len(df)
    log.info(f"\n[0] Daily VNINDEX: {n} phiên  |  gần nhất close={c.iloc[-1]:.2f}")

    # ── [1] Phân phối đà 1 phiên (= r_hôm_nay_live CUỐI phiên cho Op2) ──
    log.info("\n" + "-" * 70)
    log.info("[1] PHÂN PHỐI ĐÀ 1 PHIÊN r1d (%) — dùng đặt ngưỡng cho Op2 (EOD)")
    log.info("-" * 70)
    log.info(f"  r1d          : {pct(r1d)}")
    log.info(f"  |r1d|        : {pct(r1d.abs())}")
    up = r1d[r1d > 0]; dn = r1d[r1d < 0]
    log.info(f"  chỉ ngày TĂNG: {pct(up)}")
    log.info(f"  chỉ ngày GIẢM: {pct(dn)}")
    p_up   = float((r1d >= TH_UP).mean())
    p_down = float((r1d <= TH_DOWN).mean())
    log.info(f"  → % phiên r1d >= +{TH_UP} : {p_up:.1%}   (tần suất chạm ngưỡng UP cuối phiên)")
    log.info(f"  → % phiên r1d <= {TH_DOWN} : {p_down:.1%}   (tần suất chạm ngưỡng DOWN cuối phiên)")
    log.info("  (ngưỡng hợp lý nếu 2 con số này KHÔNG quá hiếm cũng KHÔNG quá dày)")

    # ── [2] So regime EOD: production vs Op2/Op3/Op4 ──
    log.info("\n" + "-" * 70)
    log.info("[2] REGIME EOD (close-to-close): production(chg_5d) vs Op2/Op3/Op4(m2)")
    log.info("-" * 70)
    st_prod, st_op2, st_op3, st_op4 = [], [], [], []
    diff_op2 = 0
    start = 200  # cần đủ ema200 + chg_20d
    for t in range(start, n):
        e50 = float(ema50.iloc[t])
        e200 = float(ema200.iloc[t]) if t >= 200 else None
        cl = float(c.iloc[t])
        _c5, _c20 = float(c5.iloc[t]), float(c20.iloc[t])
        r_today = float(r1d.iloc[t])
        r_yest  = float(r1d.iloc[t-1])
        sp  = classify_prod(cl, e50, e200, _c5, _c20)
        s2  = classify_op2(cl, e50, e200, r_today, _c20)
        s3  = classify_op2(cl, e50, e200, 0.4 * r_yest + r_today, _c20)
        s4  = classify_op2(cl, e50, e200, r_yest + r_today, _c20)
        st_prod.append(sp); st_op2.append(s2); st_op3.append(s3); st_op4.append(s4)
        if sp != s2:
            diff_op2 += 1

    m = len(st_prod)
    log.info(f"  Số phiên so sánh: {m}")
    log.info(f"  Phân bố PRODUCTION: {dict(Counter(st_prod))}")
    log.info(f"  Phân bố Op2       : {dict(Counter(st_op2))}")
    log.info(f"  Phân bố Op3       : {dict(Counter(st_op3))}")
    log.info(f"  Phân bố Op4       : {dict(Counter(st_op4))}")
    log.info(f"  Op2 khác production: {diff_op2}/{m} = {diff_op2/m:.1%} số phiên")
    log.info("  Số lần LẬT trạng thái (close-to-close, càng cao càng hay đổi):")
    log.info(f"    production : {count_flips(st_prod)}")
    log.info(f"    Op2 (w=0)  : {count_flips(st_op2)}")
    log.info(f"    Op3 (w=.4) : {count_flips(st_op3)}")
    log.info(f"    Op4 (w=1)  : {count_flips(st_op4)}")

    # 30 phiên gần nhất
    k = 30
    log.info(f"  [30 phiên gần nhất] lật: prod={count_flips(st_prod[-k:])} "
             f"Op2={count_flips(st_op2[-k:])} Op3={count_flips(st_op3[-k:])} Op4={count_flips(st_op4[-k:])}")

    # ── [3] Whipsaw TRONG NGÀY (cần bar intraday) ──
    log.info("\n" + "-" * 70)
    log.info("[3] WHIPSAW TRONG NGÀY — cần bar intraday theo giờ")
    log.info("-" * 70)
    prev_close_map = {}
    for t in range(1, n):
        d = str(pd.to_datetime(df["time"].iloc[t]).date()) if "time" in df.columns else None
        if d:
            prev_close_map[d] = float(c.iloc[t-1])

    bars, desc = try_fetch_intraday_bars()
    if bars is not None:
        bars = bars.copy()
        bars["close"] = pd.to_numeric(bars["close"], errors="coerce")
        bars = bars.dropna(subset=["close"])
        bars["_date"] = bars["_ts"].dt.date.astype(str)
        bars["_minute"] = bars["_ts"].dt.hour * 60 + bars["_ts"].dt.minute
        # tra ema/c20 gần nhất theo ngày từ chuỗi daily
        daily_idx = {str(pd.to_datetime(df["time"].iloc[t]).date()): t for t in range(n)} if "time" in df.columns else {}
        rtl_by_bucket = {b[0]: [] for b in HOUR_BUCKETS}
        flips_intra_op2, days_used = [], 0
        for d, g in bars.groupby("_date"):
            pc = prev_close_map.get(d)
            ti = daily_idx.get(d)
            if pc is None or ti is None or ti < 200:
                continue
            e50 = float(ema50.iloc[ti]); e200 = float(ema200.iloc[ti]); _c20 = float(c20.iloc[ti])
            g = g.sort_values("_minute")
            states = []
            for _, row in g.iterrows():
                rtl = (float(row["close"]) - pc) / pc * 100.0
                for name, lo, hi in HOUR_BUCKETS:
                    if lo <= row["_minute"] <= hi:
                        rtl_by_bucket[name].append(rtl); break
                states.append(classify_op2(float(row["close"]), e50, e200, rtl, _c20))
            if states:
                flips_intra_op2.append(count_flips(states)); days_used += 1
        log.info(f"  Nguồn: {desc}  |  ngày dùng được: {days_used}")
        log.info("  Phân phối r_hôm_nay_live theo GIỜ (dùng đặt ngưỡng-theo-giờ nếu cần):")
        for name, _, _ in HOUR_BUCKETS:
            log.info(f"    {name:22s}: {pct(rtl_by_bucket[name])}")
        if flips_intra_op2:
            avg = sum(flips_intra_op2) / len(flips_intra_op2)
            log.info(f"  Whipsaw Op2 TRONG NGÀY (số lần đổi/ngày): "
                     f"tb={avg:.2f}  max={max(flips_intra_op2)}  "
                     f"(0 = không giật; cao = cần band/xác nhận-run)")
    else:
        log.info(f"  Không có bar intraday lịch sử ({desc}). Thử tick phiên hiện tại…")
        tk = try_fetch_intraday_ticks_today()
        if tk is not None:
            cols = list(tk.columns)
            log.info(f"  intraday() OK: {len(tk)} tick, cột={cols}")
            log.info("  → chỉ có phiên HÔM NAY: đo whipsaw trong-ngày cần tích lũy nhiều phiên,")
            log.info("    nên KHÔNG kết luận whipsaw từ 1 phiên. Đề xuất: ghi log r_hôm_nay_live")
            log.info("    mỗi intraday run trong ~30 phiên rồi mới đo (đúng kỷ luật shadow).")
        else:
            log.info("  Cả history-intraday lẫn intraday() đều không có → whipsaw trong-ngày")
            log.info("  CHƯA đo được từ data hiện có. Không bịa số.")

    log.info("\n" + "=" * 70)
    log.info("XONG. Đọc [1] để chốt ngưỡng theo phân vị; [2] để so tốc độ lật EOD;")
    log.info("[3] để xem whipsaw trong-ngày (nếu có bar intraday).")
    log.info("=" * 70)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        import traceback
        log.error(f"diag lỗi (fail-soft, không chặn CI): {e}")
        traceback.print_exc()
