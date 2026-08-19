#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
diag_ta_candle_test.py — READ-ONLY. Không ghi output production, không commit.
================================================================================
CÂU HỎI DUY NHẤT script này trả lời:
    Trong PHIÊN (mid-session), lệnh history(interval="1D") của VCI có trả về
    CÂY NẾN CỦA HÔM NAY (đang hình thành, giá còn chạy) hay chỉ tới nến đã đóng
    của phiên trước?

VÌ SAO QUAN TRỌNG (P0.2 — TA daily cache):
    - Nếu nến hôm nay ĐANG hình thành trong history  → EMA/RSI/ADX lúc 14:30
      KHÁC lúc 09:40 → KHÔNG được freeze TA về giá trị đầu phiên (sẽ lệch điểm).
    - Nếu history chỉ có nến ĐÃ ĐÓNG (last = phiên trước) → TA đứng yên suốt
      phiên → AN TOÀN để cache 1 lần/ngày, các run sau dùng lại.

CÁCH ĐỌC KẾT QUẢ:
    Với mỗi mã, script so 3 tín hiệu:
      (1) last_candle_date == hôm nay?         → nến hôm nay có mặt?
      (2) last_candle_close ≈ giá live intraday? → nến đó có phải nến đang chạy?
      (3) EMA20/RSI/close có ĐỔI giữa 2 lần fetch cách nhau GAP giây?
    Verdict:
      FORMING (nến đang chạy) → P0.2 KHÔNG an toàn cho các indicator dùng close.
      STABLE  (nến đã đóng)   → P0.2 an toàn để freeze daily.

CHẠY KHI NÀO:
    BẮT BUỘC chạy GIỮA PHIÊN (≈09:45–11:25 hoặc 13:05–14:25 ICT) để kết luận có
    giá trị. Chạy ngoài giờ: nến hôm nay (nếu có) đã đóng → không phân biệt được
    "đang chạy" vs "đã đóng" bằng tín hiệu (3); script sẽ CẢNH BÁO.

DISPATCH:
    debug.yml → input script = scripts/diag_ta_candle_test.py
    Tuỳ chọn qua env:
      TA_TEST_SYMBOLS  = "FPT,HPG,VCB"   (mặc định: lấy 6 mã đầu universe)
      TA_TEST_GAP_SEC  = "90"            (khoảng cách 2 lần fetch, giây)
"""
import os
import sys
import time
import logging
from datetime import datetime

# Cho phép import package của repo khi chạy từ root
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pandas as pd

from vnstock_data import Quote
from vnstock_ta import Indicator

from utils.helpers import now_ict, is_market_open, today_str, safe_val
from utils.vci_throttle import vci_safe_run, set_min_interval
from utils.v2f_universe import build_v2f_universe

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("ta_candle_test")

HISTORY_LENGTH = "12M"   # giống production (steps/v2f_step_snapshot.py)
GAP_SEC = int(os.environ.get("TA_TEST_GAP_SEC", "90"))


def _pick_symbols() -> list[str]:
    env = os.environ.get("TA_TEST_SYMBOLS", "").strip()
    if env:
        return [s.strip().upper() for s in env.split(",") if s.strip()]
    try:
        jobs, _ = build_v2f_universe()
        syms = [s for s, _g in jobs][:6]
        if syms:
            return syms
    except Exception as e:
        log.warning(f"build_v2f_universe fail ({e}) → dùng danh sách mặc định")
    return ["FPT", "HPG", "VCB", "SSI", "MWG", "VND"]


def _fetch_history(symbol: str):
    return vci_safe_run(
        f"history {symbol}",
        lambda: Quote(source="VCI", symbol=symbol).history(
            length=HISTORY_LENGTH, interval="1D"),
    )


def _fetch_live_price(symbol: str):
    df = vci_safe_run(
        f"intraday {symbol}",
        lambda: Quote(source="VCI", symbol=symbol).intraday(page_size=200),
    )
    if df is None or df.empty or "price" not in df.columns:
        return None
    try:
        return float(pd.to_numeric(df["price"], errors="coerce").dropna().iloc[-1])
    except Exception:
        return None


def _last_candle(df) -> tuple[str | None, float | None]:
    """Trả (date_str, close) của cây nến cuối cùng trong history."""
    if df is None or df.empty:
        return None, None
    try:
        d = str(df["time"].iloc[-1])[:10]
    except Exception:
        d = None
    try:
        c = float(pd.to_numeric(df["close"], errors="coerce").dropna().iloc[-1])
    except Exception:
        c = None
    return d, c


def _indicators(df) -> dict:
    """EMA20 + RSI14 giống production để xem chúng có nhích không."""
    out = {"ema20": None, "rsi14": None}
    if df is None or df.empty or len(df) < 20:
        return out
    try:
        ind = Indicator(data=df)
        out["ema20"] = safe_val(ind.trend.ema(length=20))
        out["rsi14"] = safe_val(ind.momentum.rsi(length=14))
    except Exception as e:
        log.warning(f"  indicator fail: {e}")
    return out


def _approx(a, b, tol_pct=0.15) -> bool:
    """|a-b|/b nhỏ hơn tol_pct% → coi như xấp xỉ (giá khớp)."""
    if a is None or b is None or b == 0:
        return False
    return abs(a - b) / abs(b) * 100.0 <= tol_pct


def main():
    set_min_interval(0.35)   # nhẹ nhàng, đây chỉ là test vài mã
    symbols = _pick_symbols()
    td = today_str()
    mkt_open = is_market_open()

    print("=" * 78)
    print("TA CANDLE TEST — history 1D trong phiên có gồm nến hôm nay?")
    print(f"Thời điểm : {now_ict():%Y-%m-%d %H:%M:%S} ICT")
    print(f"Hôm nay   : {td}")
    print(f"Market open (helper): {mkt_open}")
    print(f"Symbols   : {symbols}")
    print(f"Gap 2 lần fetch: {GAP_SEC}s")
    print("=" * 78)
    if not mkt_open:
        print("⚠️  CẢNH BÁO: helper báo NGOÀI PHIÊN. Tín hiệu (3) 'giá nhích giữa")
        print("    2 lần fetch' sẽ vô nghĩa (nến đã đóng). Chỉ tín hiệu (1)+(2)")
        print("    còn tham khảo được. Nên chạy lại GIỮA PHIÊN để kết luận chắc.")
        print("-" * 78)

    # ── Fetch lần 1 + giá live ─────────────────────────────────────────────
    rows = {}
    for s in symbols:
        df1 = _fetch_history(s)
        d1, c1 = _last_candle(df1)
        ind1 = _indicators(df1)
        live = _fetch_live_price(s) if mkt_open else None
        rows[s] = {"d1": d1, "c1": c1, "live": live,
                   "ema1": ind1["ema20"], "rsi1": ind1["rsi14"],
                   "n1": (0 if df1 is None else len(df1))}

    print(f"\n⏳ Chờ {GAP_SEC}s rồi fetch lần 2 (để xem nến cuối có nhích)...\n")
    time.sleep(GAP_SEC)

    # ── Fetch lần 2 ────────────────────────────────────────────────────────
    for s in symbols:
        df2 = _fetch_history(s)
        d2, c2 = _last_candle(df2)
        ind2 = _indicators(df2)
        rows[s].update({"d2": d2, "c2": c2,
                        "ema2": ind2["ema20"], "rsi2": ind2["rsi14"]})

    # ── Đánh giá từng mã ───────────────────────────────────────────────────
    print("=" * 78)
    print("KẾT QUẢ TỪNG MÃ")
    print("=" * 78)
    n_forming = 0
    n_stable = 0
    n_unknown = 0
    for s in symbols:
        r = rows[s]
        d1, c1, live = r.get("d1"), r.get("c1"), r.get("live")
        c2 = r.get("c2")
        ema1, ema2 = r.get("ema1"), r.get("ema2")
        rsi1, rsi2 = r.get("rsi1"), r.get("rsi2")

        is_today = (d1 == td)
        close_eq_live = _approx(c1, live) if live is not None else None
        close_moved = (c1 is not None and c2 is not None and c1 != c2)
        ema_moved = (ema1 is not None and ema2 is not None and ema1 != ema2)
        rsi_moved = (rsi1 is not None and rsi2 is not None and rsi1 != rsi2)

        # Logic verdict:
        #   - Nến cuối == hôm nay VÀ (khớp giá live HOẶC có nhích) → FORMING
        #   - Nến cuối < hôm nay                                   → STABLE
        #   - Nến cuối == hôm nay nhưng ngoài phiên/không nhích    → UNKNOWN
        if is_today and (close_eq_live is True or close_moved or ema_moved or rsi_moved):
            verdict = "FORMING (nến hôm nay đang chạy → KHÔNG freeze được)"
            n_forming += 1
        elif (d1 is not None) and (not is_today):
            verdict = "STABLE (nến cuối = phiên trước → freeze OK)"
            n_stable += 1
        elif is_today:
            verdict = "UNKNOWN (nến=hôm nay nhưng không thấy nhích — chạy lại giữa phiên)"
            n_unknown += 1
        else:
            verdict = "UNKNOWN (thiếu data)"
            n_unknown += 1

        print(f"\n[{s}]  (history {r.get('n1')} nến)")
        print(f"  nến cuối date : {d1}   (hôm nay={td} → today? {is_today})")
        print(f"  nến cuối close: {c1}")
        print(f"  giá live      : {live}   (close≈live? {close_eq_live})")
        print(f"  close nhích 2 lần fetch : {c1} → {c2}  (moved={close_moved})")
        print(f"  EMA20 nhích            : {ema1} → {ema2}  (moved={ema_moved})")
        print(f"  RSI14 nhích            : {rsi1} → {rsi2}  (moved={rsi_moved})")
        print(f"  → {verdict}")

    # ── Kết luận tổng ──────────────────────────────────────────────────────
    print("\n" + "=" * 78)
    print("KẾT LUẬN TỔNG")
    print("=" * 78)
    print(f"FORMING={n_forming}  STABLE={n_stable}  UNKNOWN={n_unknown}")
    if n_forming > 0:
        print("\n❌ history 1D CÓ nến hôm nay đang chạy (ít nhất 1 mã FORMING).")
        print("   → P0.2 KHÔNG an toàn nếu freeze nguyên EMA/RSI/ADX/close về đầu")
        print("     phiên. Chỉ được cache phần THUẦN LỊCH SỬ (nến đã đóng); phần")
        print("     phụ thuộc nến hôm nay phải tính lại mỗi run (daily base +")
        print("     realtime overlay — đúng như 'category C' trong proposal).")
    elif n_stable > 0 and n_forming == 0 and n_unknown == 0:
        print("\n✅ history 1D chỉ có nến ĐÃ ĐÓNG (mọi mã STABLE).")
        print("   → P0.2 AN TOÀN: TA đứng yên trong phiên, cache 1 lần/ngày dùng lại.")
    else:
        print("\n⚠️  CHƯA KẾT LUẬN ĐƯỢC (có UNKNOWN). Nhiều khả năng chạy ngoài phiên")
        print("    hoặc thị trường phẳng đúng lúc test. CHẠY LẠI GIỮA PHIÊN.")
    print("=" * 78)


if __name__ == "__main__":
    main()
