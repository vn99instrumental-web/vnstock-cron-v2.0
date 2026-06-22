"""
scripts/diag_balance_sheet.py — Tìm signature balance_sheet trả data (cứu D/E)
==============================================================================
Pattern tham khảo: cash_flow đã fix bằng cách đổi quarter→year (v5).
balance_sheet(quarter, limit=1) hiện EMPTY 150/150 mã trong daily re-fetch gần
nhất → áp cùng giả thuyết: thử period/limit khác.

Test grid trên 6 mã VN100:
  - KBS  × {(quarter,1), (quarter,4), (year,1), (year,4)}
  - VCI  × cùng 4 combo  (đối chiếu để chắc chắn VCI vẫn empty)

Sau đó với mã đầu tiên trả data: dump tên cột để biết Equity / Debt /
Liabilities nằm ở field nào — cần cho code D/E sau khi chốt signature.

Chạy: python scripts/diag_balance_sheet.py
debug.yml: tên script `diag_balance_sheet`
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

import logging
logging.basicConfig(level=logging.INFO, format="%(message)s")
log = logging.getLogger("diag_bs")

from vnstock_data import Finance

SAMPLE = os.environ.get("DIAG_SYMBOLS", "HPG,VCB,FPT,VHM,STB,MWG").split(",")

COMBOS = [
    ("quarter", 1),
    ("quarter", 4),
    ("year",    1),
    ("year",    4),
]


def _shape(df) -> str:
    if df is None:
        return "ERR"
    try:
        if getattr(df, "empty", True):
            return "EMPTY"
        return f"{df.shape[0]}x{df.shape[1]}"
    except Exception:
        return "?"


def _try(fn):
    try:
        return fn(), None
    except Exception as e:
        return None, f"{type(e).__name__}: {str(e)[:80]}"


def _cols_of_interest(df):
    """Trả tên cột chứa equity/debt/liabilities/asset (case-insensitive)."""
    if df is None or getattr(df, "empty", True):
        return []
    keys = ("equity", "debt", "liab", "asset")
    return [c for c in df.columns if any(k in str(c).lower() for k in keys)]


def main():
    log.info("=" * 78)
    log.info(f"DIAG balance_sheet — sample: {SAMPLE}")
    log.info("Tìm combo (source, period, limit) trả data — cứu D/E")
    log.info("=" * 78)

    coverage = {(src, p, l): 0 for src in ("KBS", "VCI") for p, l in COMBOS}
    dumped_cols = False
    first_dump = None

    for sym in SAMPLE:
        sym = sym.strip().upper()
        log.info(f"\n── {sym} ──")
        for src in ("KBS", "VCI"):
            parts = []
            for period, limit in COMBOS:
                df, err = _try(lambda: Finance(source=src, symbol=sym)
                               .balance_sheet(period=period, limit=limit))
                sh = _shape(df)
                if sh not in ("EMPTY", "ERR", "?"):
                    coverage[(src, period, limit)] += 1
                    # Lưu df đầu tiên có data để dump cột sau
                    if not dumped_cols:
                        first_dump = (sym, src, period, limit, df)
                        dumped_cols = True
                parts.append(f"{period[:1]}{limit}={sh}" + (f"!{err}" if err else ""))
                time.sleep(0.30)
            log.info(f"  {src:3s}: " + "  ".join(parts))

    # ── Dump cột mã đầu tiên có data ──
    if first_dump:
        sym, src, period, limit, df = first_dump
        log.info("\n" + "-" * 78)
        log.info(f"COLUMN DUMP: {sym} via {src}.balance_sheet({period}, limit={limit})")
        log.info(f"  shape: {df.shape}")
        log.info(f"  all columns ({len(df.columns)}): {list(df.columns)}")
        loi = _cols_of_interest(df)
        log.info(f"  D/E-related columns ({len(loi)}): {loi}")
        try:
            log.info(f"  last row sample (D/E-related):")
            for c in loi[:8]:
                log.info(f"    {c} = {df.iloc[-1][c]}")
        except Exception as e:
            log.info(f"  (sample dump failed: {e})")

    # ── Tổng hợp coverage ──
    n = len(SAMPLE)
    log.info("\n" + "=" * 78)
    log.info(f"COVERAGE (số mã trả data / {n}):")
    for src in ("KBS", "VCI"):
        for period, limit in COMBOS:
            log.info(f"  {src:3s} {period:7s} limit={limit}: "
                     f"{coverage[(src, period, limit)]}/{n}")
    log.info("=" * 78)
    log.info("ĐỌC KẾT QUẢ:")
    log.info("  - Combo nào coverage = n/n → dùng combo đó cho D/E.")
    log.info("  - Tất cả KBS empty → balance_sheet broken cả 2 period → cần ticket lib.")
    log.info("  - VCI khả dĩ → fallback strategy như cash_flow→year (changelog v5).")
    log.info("=" * 78)


if __name__ == "__main__":
    main()
