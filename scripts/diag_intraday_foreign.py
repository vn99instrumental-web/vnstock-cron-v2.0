#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
scripts/diag_intraday_foreign.py — CÓ "khối ngoại trong phiên" không?
======================================================================
MỤC ĐÍCH: xác định NGUỒN NÀO (nếu có) trả foreign buy/sell PER-SYMBOL
cập nhật TRONG PHIÊN — làm đầu vào cho tín hiệu "khối ngoại / tổng GTGD".

Bối cảnh (đã verify bằng data thật, không suy diễn):
  - Quote.intraday : match_type = mua/bán CHỦ ĐỘNG (tick-rule), KHÔNG nội/ngoại.
  - Trading.foreign_trade (VCI): EOD phiên trước (T-1), đứng im nguyên phiên
    (HPG ff_net_5d y hệt qua 4 lần chạy 09:35→14:33 ngày 06/08).
  - Trading.price_board : diag 2026-05-27 ghi ❌ RetryError → CẦN RE-VERIFY.

Script thăm dò 4 hướng + in VERDICT rõ ràng:
  1) Quote.intraday   — liệt kê CỘT, khẳng định có/không cột foreign.
  2) foreign_trade    — in dòng cuối + trading_date: CÓ dòng HÔM NAY không?
  3) price_board      — HƯỚNG CHÍNH: có cột foreign per-symbol không? khác nhau
                        giữa các mã không? gọi 2 LẦN cách ~45s → foreign có TĂNG
                        (tích luỹ trong phiên) không?
  4) probe            — liệt kê method khả dĩ khác của Trading/Market.

⚠️ PHẢI CHẠY TRONG GIỜ GD (09:15–14:30 ICT) để foreign intraday có data và để
   test tích luỹ (2 lần gọi) có ý nghĩa. Ngoài giờ → nhiều nguồn rỗng.

TRIGGER:
    Actions → debug.yml → Run workflow → script = scripts/diag_intraday_foreign.py

QUYẾT ĐỊNH (đọc VERDICT cuối log):
    (3) price_board có foreign per-symbol KHÁC nhau + Δ≠0 giữa 2 lần gọi
        → CÓ khối ngoại trong phiên → build tín hiệu được.
    (3) hỏng / không có cột foreign, chỉ còn (2) T-1
        → KHÔNG có intraday từ nguồn hiện tại → đổi nguồn hoặc chấp nhận T-1.
"""
import os
import sys
import time
import random
import traceback

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

os.environ["VNSTOCK_INTERACTIVE"] = "0"
os.environ["VNSTOCK_LANGUAGE"]    = "en"
os.environ["MPLCONFIGDIR"]        = "/home/runner/.config/matplotlib"
os.makedirs("/home/runner/.vnstock",           exist_ok=True)
os.makedirs("/home/runner/.config/matplotlib", exist_ok=True)

import logging
import pandas as pd

from vnstock_data import Trading, Quote
from utils.helpers import now_ict, is_market_open, start_str, today_str

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

pd.set_option("display.max_columns", None)
pd.set_option("display.width", 220)

# Bluechip thanh khoản cao + khối ngoại giao dịch mạnh → dễ lộ cột foreign
TEST_SYMBOLS = ["HPG", "VCB", "SSI", "FPT", "VND", "MSN"]

# Token nhận diện cột foreign (VCI/CafeF/bảng giá đặt tên khác nhau)
FOREIGN_TOKENS = ("foreign", "fr_", "_fr", "nn_", "_nn", "ngoai", "khoi_ngoai",
                  "buy_foreign", "foreign_buy", "foreignbuy")


def _try(label, fn):
    """Gọi an toàn, trả df hoặc None + log lỗi gọn."""
    try:
        return fn()
    except Exception as e:
        log.warning(f"  [FAIL] {label}: {type(e).__name__}: {str(e)[:160]}")
        return None


def _flatten_cols(df):
    df = df.copy()
    df.columns = [".".join(str(x) for x in c) if isinstance(c, tuple) else str(c)
                  for c in df.columns]
    return df


def _find_foreign_cols(cols):
    return [c for c in cols if any(t in str(c).lower() for t in FOREIGN_TOKENS)]


def _find_symbol_col(cols):
    low = {c: str(c).lower() for c in cols}
    for c, cl in low.items():
        if cl == "symbol" or cl.endswith(".symbol") or "listing.symbol" in cl:
            return c
    for c, cl in low.items():
        if "symbol" in cl or "ticker" in cl:
            return c
    return None


# ─────────────────────────────────────────────────────────────────────────
# 1) Quote.intraday — xác nhận KHÔNG có foreign
# ─────────────────────────────────────────────────────────────────────────
def sect_intraday():
    log.info("=" * 72)
    log.info("1) Quote.intraday — có cột foreign không?")
    df = _try("intraday HPG",
              lambda: Quote(source="VCI", symbol="HPG").intraday(page_size=50))
    if df is None or getattr(df, "empty", True):
        log.info("   intraday rỗng (ngoài giờ?) — bỏ qua.")
        return
    cols = list(df.columns)
    log.info(f"   Cột ({len(cols)}): {cols}")
    fcols = _find_foreign_cols(cols)
    log.info(f"   → Cột foreign: {fcols if fcols else 'KHÔNG CÓ'} "
             f"(match_type = mua/bán chủ động theo tick-rule, KHÔNG phải nội/ngoại)")


# ─────────────────────────────────────────────────────────────────────────
# 2) foreign_trade — có dòng HÔM NAY (intraday) hay chỉ T-1?
# ─────────────────────────────────────────────────────────────────────────
def sect_foreign_trade():
    log.info("=" * 72)
    log.info("2) Trading.foreign_trade — có dòng HÔM NAY (intraday) không?")
    today = today_str()
    for sym in TEST_SYMBOLS[:3]:
        df = _try(f"foreign_trade {sym}",
                  lambda s=sym: Trading(symbol=s, source="VCI").foreign_trade(
                      start=start_str(10), end=today_str()))
        if df is None or df.empty:
            log.info(f"   {sym}: rỗng")
            continue
        dcol = next((c for c in df.columns if "date" in str(c).lower()), None)
        ncol = next((c for c in df.columns if "net" in str(c).lower()), None)
        if dcol:
            df = df.copy()
            df[dcol] = pd.to_datetime(df[dcol], errors="coerce")
            df = df.sort_values(dcol)
            last_date = str(df[dcol].iloc[-1])[:10]
            flag = "CÓ (intraday!)" if last_date == today else "KHÔNG → T-1/EOD"
            net = df[ncol].iloc[-1] if ncol else "?"
            log.info(f"   {sym}: dòng cuối={last_date} | HÔM NAY({today})? {flag} "
                     f"| net_cuối={net}")
        time.sleep(0.4 + random.uniform(0, 0.3))


# ─────────────────────────────────────────────────────────────────────────
# 3) price_board — HƯỚNG CHÍNH cho intraday foreign
# ─────────────────────────────────────────────────────────────────────────
def _fetch_price_board():
    """Thử vài chữ ký gọi (chưa chắc signature) → trả (df_flatten, form_name)."""
    forms = [
        ("price_board(list)",
         lambda: Trading(source="VCI").price_board(TEST_SYMBOLS)),
        ("price_board(symbols_list=)",
         lambda: Trading(source="VCI").price_board(symbols_list=TEST_SYMBOLS)),
        ("Trading(symbol).price_board([sym])",
         lambda: Trading(symbol="HPG", source="VCI").price_board(["HPG"])),
    ]
    for name, fn in forms:
        df = _try(f"price_board via {name}", fn)
        if df is not None and not df.empty:
            log.info(f"   [OK] gọi được bằng: {name}")
            return _flatten_cols(df), name
    return None, None


def sect_price_board():
    log.info("=" * 72)
    log.info("3) Trading.price_board — HƯỚNG CHÍNH (re-verify sau lỗi 27/05)")
    df, form = _fetch_price_board()
    if df is None:
        log.info("   ❌ price_board KHÔNG gọi được (hỏng / sai signature).")
        return
    cols = list(df.columns)
    log.info(f"   Tổng {len(cols)} cột:")
    for c in cols:
        log.info(f"       {c}")

    fcols = _find_foreign_cols(cols)
    log.info(f"   → Cột FOREIGN: {fcols if fcols else 'KHÔNG CÓ'}")
    if not fcols:
        log.info("   price_board gọi được nhưng KHÔNG có cột foreign → không dùng.")
        return

    symcol = _find_symbol_col(cols)
    log.info(f"   Cột symbol: {symcol}")

    log.info("   --- Foreign per-symbol (LẦN 1) ---")
    snap1 = {}
    for _, row in df.iterrows():
        sym = str(row.get(symcol)) if symcol else "?"
        snap1[sym] = {c: row.get(c) for c in fcols}
        log.info(f"     {sym}: " +
                 ", ".join(f"{c.split('.')[-1]}={row.get(c)}" for c in fcols))

    # per-symbol variance: khác nhau giữa các mã = per-symbol thật (không aggregate)
    for c in fcols:
        uniq = {str(snap1[s].get(c)) for s in snap1}
        verdict = "PER-SYMBOL ✓" if len(uniq) > 1 else "GIỐNG NHAU (nghi aggregate) ✗"
        log.info(f"   Cột {c}: {len(uniq)} giá trị khác / {len(snap1)} mã → {verdict}")

    # test tích luỹ trong phiên: gọi lại sau ~45s
    log.info("   --- Chờ ~45s rồi gọi LẦN 2 để xem foreign có TĂNG (intraday) ---")
    time.sleep(45)
    df2, _ = _fetch_price_board()
    if df2 is None or df2.empty:
        log.info("   Lần 2 rỗng — không so được delta.")
        return
    symcol2 = _find_symbol_col(list(df2.columns))
    for _, row in df2.iterrows():
        sym = str(row.get(symcol2)) if symcol2 else "?"
        if sym not in snap1:
            continue
        deltas = []
        for c in fcols:
            try:
                v1 = float(snap1[sym].get(c))
                v2 = float(row.get(c))
                deltas.append(f"{c.split('.')[-1]}:{v1:.0f}→{v2:.0f}(Δ{v2 - v1:+.0f})")
            except (TypeError, ValueError):
                pass
        if deltas:
            log.info(f"     {sym}: " + " | ".join(deltas))
    log.info("   → Δ≠0 (trong giờ GD) = foreign TÍCH LUỸ trong phiên = INTRADAY THẬT.")
    log.info("     Δ=0 toàn bộ = có thể là số T-1 tĩnh (KHÔNG intraday).")


# ─────────────────────────────────────────────────────────────────────────
# 4) probe method khả dĩ khác
# ─────────────────────────────────────────────────────────────────────────
def sect_probe():
    log.info("=" * 72)
    log.info("4) Probe method khả dĩ khác (Trading / Market)")
    try:
        t = Trading(symbol="HPG", source="VCI")
        log.info(f"   Trading methods: {[m for m in dir(t) if not m.startswith('_')]}")
    except Exception as e:
        log.warning(f"   Trading probe fail: {type(e).__name__}: {e}")
    try:
        import vnstock_data as vd
        if hasattr(vd, "Market"):
            log.info(f"   Market class methods: "
                     f"{[m for m in dir(vd.Market) if not m.startswith('_')]}")
        else:
            log.info("   vnstock_data không có class Market.")
    except Exception as e:
        log.info(f"   Market probe skip: {type(e).__name__}: {e}")


if __name__ == "__main__":
    log.info(f"=== DIAG INTRADAY FOREIGN ({now_ict():%Y-%m-%d %H:%M:%S} ICT) ===")
    mo = is_market_open()
    log.info("Market open: " + (str(mo) if mo else
             "False  ⚠️ NGOÀI GIỜ — foreign intraday có thể rỗng; "
             "chạy lại TRONG GIỜ GD để kết luận chắc."))

    for name, fn in (("intraday", sect_intraday),
                     ("foreign_trade", sect_foreign_trade),
                     ("price_board", sect_price_board),
                     ("probe", sect_probe)):
        try:
            fn()
        except Exception:
            log.error(f"[{name}] crash:\n{traceback.format_exc()}")

    log.info("=" * 72)
    log.info("VERDICT — đọc mục (3):")
    log.info("  • price_board có cột foreign per-symbol (khác nhau giữa mã) + Δ≠0")
    log.info("    giữa 2 lần gọi  → CÓ khối ngoại trong phiên → build tín hiệu được.")
    log.info("  • price_board hỏng / không cột foreign, chỉ còn foreign_trade (T-1)")
    log.info("    → KHÔNG có intraday từ nguồn hiện tại → đổi nguồn hoặc chấp nhận T-1.")
    log.info("=== DONE ===")
