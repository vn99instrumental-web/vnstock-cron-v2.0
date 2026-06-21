"""
scripts/diag_vci_finance.py — VCI có thay được KBS làm nguồn fundamental không?
================================================================================
Mục đích: quyết định "2 nguồn (KBS+VCI fallback) như hiện tại" vs "1 nguồn VCI".

Test trên vài mã VN100, gọi CẢ HAI nguồn với ĐÚNG signature step_finance_scan
đang dùng, rồi so sánh phủ sóng từng loại báo cáo:

  Finance(src).ratio(quarter,1)           → PE/PB/ROE/ROA/div_yield   (nhóm Fundamental)
  Finance(src).income_statement(quarter,4)→ Revenue/NP/EPS growth     (nhóm Growth)
  Finance(src).balance_sheet(quarter,1)   → Assets/Equity/Debt → D/E  (Fundamental)
  Finance(src).cash_flow(year,1)          → CFO/CFI/CFF               (nhóm Cash Flow)
  Company(VCI).ratio_summary()            → fallback ratio hiện tại

Câu hỏi chốt: Finance(VCI).{income,balance,cashflow} CÓ trả data chưa?
  - CÓ  → VCI-only khả thi (thay được Growth/CF/D-E).
  - RỖNG→ KBS bắt buộc giữ cho statements → 2 nguồn là đúng.

Chạy: python scripts/diag_vci_finance.py   |  debug.yml: tên `diag_vci_finance`
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
log = logging.getLogger("diag_vci_fin")

import pandas as pd
from vnstock_data import Finance, Company

SAMPLE = os.environ.get("DIAG_SYMBOLS", "HPG,VCB,FPT,VHM,STB,MWG").split(",")

# (label, callable(symbol, source))
CALLS = {
    "ratio"      : lambda s, src: Finance(source=src, symbol=s).ratio(period="quarter", limit=1),
    "income_q"   : lambda s, src: Finance(source=src, symbol=s).income_statement(period="quarter", limit=4),
    "balance_q"  : lambda s, src: Finance(source=src, symbol=s).balance_sheet(period="quarter", limit=1),
    "cashflow_y" : lambda s, src: Finance(source=src, symbol=s).cash_flow(period="year", limit=1),
}


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


def _scalar(df, col_substr):
    """Lấy 1 giá trị từ cột chứa col_substr (case-insensitive), dòng cuối."""
    if df is None or getattr(df, "empty", True):
        return None
    cols = [c for c in df.columns if col_substr.lower() in str(c).lower()]
    if not cols:
        return None
    try:
        return df.iloc[-1][cols[0]]
    except Exception:
        return None


def main():
    log.info("=" * 78)
    log.info(f"DIAG VCI FINANCE — sample: {SAMPLE}")
    log.info("So sánh KBS vs VCI cho từng loại báo cáo (shape = rows x cols)")
    log.info("=" * 78)

    agg = {src: {k: 0 for k in CALLS} for src in ("KBS", "VCI")}
    agg_rs = 0
    first_dump_done = False

    for sym in SAMPLE:
        sym = sym.strip().upper()
        log.info(f"\n── {sym} ──")
        store = {}
        for src in ("KBS", "VCI"):
            shapes = []
            for label, fn in CALLS.items():
                df, err = _try(lambda: fn(sym, src))
                store[(src, label)] = df
                sh = _shape(df)
                if sh not in ("EMPTY", "ERR", "?"):
                    agg[src][label] += 1
                shapes.append(f"{label}={sh}" + (f"({err})" if err else ""))
                time.sleep(0.35)
            log.info(f"  {src:3s}: " + "  ".join(shapes))

        # ratio_summary (VCI-only fallback hiện tại)
        rs, err = _try(lambda: Company(source="VCI", symbol=sym).ratio_summary())
        if _shape(rs) not in ("EMPTY", "ERR", "?"):
            agg_rs += 1
        log.info(f"  VCI Company.ratio_summary = {_shape(rs)}" + (f" ({err})" if err else ""))

        # So đơn vị div_yield: KBS ratio vs VCI ratio_summary (xác nhận live bug đơn vị)
        kbs_dy = _scalar(store.get(("KBS", "ratio")), "dividend")
        vci_dy = _scalar(rs, "dividend")
        log.info(f"  div_yield → KBS={kbs_dy}  |  VCI_ratio_summary={vci_dy}")

        # Dump cột VCI statements cho mã ĐẦU TIÊN có data — xem VCI thực trả gì
        if not first_dump_done:
            for label in ("income_q", "balance_q", "cashflow_y"):
                df = store.get(("VCI", label))
                if df is not None and not getattr(df, "empty", True):
                    log.info(f"  [VCI {label} columns] {list(df.columns)[:25]}")
                    first_dump_done = True

    # ── Tổng hợp ──
    n = len(SAMPLE)
    log.info("\n" + "=" * 78)
    log.info(f"COVERAGE (số mã trả data / {n}):")
    for label in CALLS:
        log.info(f"  {label:11s}: KBS={agg['KBS'][label]}/{n}   VCI={agg['VCI'][label]}/{n}")
    log.info(f"  ratio_summary(VCI): {agg_rs}/{n}")
    log.info("=" * 78)
    log.info("ĐỌC KẾT QUẢ:")
    log.info("  - VCI income_q/balance_q/cashflow_y > 0  → VCI-only KHẢ THI (có Growth/CF/D-E).")
    log.info("  - VCI 3 báo cáo trên = 0 (EMPTY)         → KBS BẮT BUỘC giữ → 2 nguồn là đúng.")
    log.info("  - div_yield: KBS thường ~0.0x (decimal), VCI_ratio_summary ~%  → khớp bug đơn vị.")
    log.info("=" * 78)


if __name__ == "__main__":
    main()
