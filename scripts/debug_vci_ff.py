"""
scripts/debug_vci_ff.py — Verify VCI foreign_trade per-symbol
==============================================================
MỤC ĐÍCH: kiểm tra VCI Trading.foreign_trade có trả NET VALUE phân biệt
theo từng mã hay không — đối lập với CafeF (trả identical aggregate
across symbols, là lý do validate_ff_data() wipe sạch ff_score = 0).

Bối cảnh: diagnostic 2026-05-27 ghi Trading.foreign_trade ✅ (VCI, 25 cols)
và step2_deep.py (bản cũ) từng đọc fr_net_value_total per-symbol từ VCI,
NHƯNG production step_snapshot.py lại dùng CafeF với comment "VCI 100% fail".
Script này phân xử mâu thuẫn đó bằng dữ liệu thật.

TRIGGER qua debug.yml:
    workflow_dispatch → input script = scripts/debug_vci_ff.py
Chạy TRONG GIỜ GD để FF có data (ngoài giờ một số mã có thể rỗng).

QUYẾT ĐỊNH:
    VCI net_5d KHÁC nhau giữa các mã  → AN TOÀN đổi source FF sang VCI (Phương án C)
    VCI net_5d GIỐNG nhau (như CafeF) → VCI vẫn lỗi, giữ Phương án B
"""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

os.environ["VNSTOCK_INTERACTIVE"] = "0"
os.environ["VNSTOCK_LANGUAGE"]    = "en"
os.environ["MPLCONFIGDIR"]        = "/home/runner/.config/matplotlib"
os.makedirs("/home/runner/.vnstock",           exist_ok=True)
os.makedirs("/home/runner/.config/matplotlib", exist_ok=True)

import logging
import pandas as pd

from vnstock_data import Trading
from utils.helpers import start_str, today_str, safe_run, now_ict

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
log = logging.getLogger(__name__)

# Mẫu thử: bluechip thanh khoản cao + có FF rõ ràng để dễ thấy khác biệt
TEST_SYMBOLS = ["HPG", "VND", "SSI", "FPT", "VCB"]

# Fallback chain tên cột (VCI ~25 cols; CafeF dùng *_matched / *_total)
NET_COLS  = ["fr_net_value_total", "fr_net_value", "net_value", "net_val"]
BUY_COLS  = ["fr_buy_value_matched", "fr_buy_value", "buy_value", "buy_val"]
SELL_COLS = ["fr_sell_value_matched", "fr_sell_value", "sell_value", "sell_val"]
DATE_COLS = ("date", "time", "trading_date", "trade_date")


def _pick(df: pd.DataFrame, candidates: list[str]):
    for c in candidates:
        if c in df.columns:
            return c
    return None


def _net_metrics(df: pd.DataFrame):
    """
    Trả (net_5d, net_20d, rows, net_col) — tính y hệt step_snapshot:
    sort ASC theo ngày → net.tail(5).sum() / net.sum().
    """
    if df is None or df.empty:
        return None, None, 0, None

    df = df.copy()
    date_col = next((c for c in df.columns if c in DATE_COLS), None)
    if date_col:
        df[date_col] = pd.to_datetime(df[date_col], errors="coerce")
        df = df.sort_values(date_col, ascending=True)

    net_col = _pick(df, NET_COLS)
    if net_col is None:
        # Tự dựng net = buy - sell nếu thiếu cột net
        bcol, scol = _pick(df, BUY_COLS), _pick(df, SELL_COLS)
        if bcol and scol:
            df["_net_"] = (
                pd.to_numeric(df[bcol], errors="coerce").fillna(0)
                - pd.to_numeric(df[scol], errors="coerce").fillna(0)
            )
            net_col = "_net_"
        else:
            return None, None, len(df), None

    net = pd.to_numeric(df[net_col], errors="coerce").dropna()
    if net.empty:
        return None, None, len(df), net_col
    return float(net.tail(5).sum()), float(net.sum()), len(net), net_col


def _fetch(source: str, symbol: str):
    return safe_run(
        f"{source} foreign_trade {symbol}",
        lambda: Trading(symbol=symbol, source=source).foreign_trade(
            start=start_str(25), end=today_str()
        ),
    )


def run():
    log.info(f"=== DEBUG VCI FF ({now_ict():%Y-%m-%d %H:%M:%S} ICT) ===")
    log.info(f"Test symbols: {TEST_SYMBOLS}\n")

    vci_net5d:   dict[str, float | None] = {}
    cafef_net5d: dict[str, float | None] = {}

    for sym in TEST_SYMBOLS:
        log.info(f"───────── {sym} ─────────")

        # ── VCI ──
        df_vci = _fetch("VCI", sym)
        if df_vci is not None and not df_vci.empty:
            log.info(f"  [VCI]   shape={df_vci.shape} cols={list(df_vci.columns)[:10]}")
            n5, n20, rows, col = _net_metrics(df_vci)
            vci_net5d[sym] = n5
            log.info(f"  [VCI]   net_col='{col}' rows={rows} net_5d={n5} net_20d={n20}")
        else:
            log.warning("  [VCI]   EMPTY/None")
            vci_net5d[sym] = None

        # ── CafeF (đối chứng) ──
        df_cf = _fetch("CafeF", sym)
        if df_cf is not None and not df_cf.empty:
            n5, n20, rows, col = _net_metrics(df_cf)
            cafef_net5d[sym] = n5
            log.info(f"  [CafeF] net_col='{col}' rows={rows} net_5d={n5} net_20d={n20}")
        else:
            log.warning("  [CafeF] EMPTY/None")
            cafef_net5d[sym] = None
        log.info("")

    # ── Verdict ──
    def _distinct(d: dict):
        vals = [v for v in d.values() if v is not None]
        return len(vals), len(set(vals))

    v_n, v_u = _distinct(vci_net5d)
    c_n, c_u = _distinct(cafef_net5d)

    log.info("════════════ KẾT LUẬN ════════════")
    log.info(f"VCI   : {v_n} mã có data, {v_u} giá trị net_5d KHÁC NHAU")
    log.info(f"        {vci_net5d}")
    log.info(f"CafeF : {c_n} mã có data, {c_u} giá trị net_5d KHÁC NHAU")
    log.info(f"        {cafef_net5d}")
    log.info("───────────────────────────────────")

    if v_n >= 3 and v_u >= max(2, v_n - 1):
        log.info("✅ VCI trả net VALUE phân biệt theo mã.")
        log.info("   → AN TOÀN đổi source FF sang VCI (Phương án C).")
    elif v_n >= 3 and v_u == 1:
        log.info("🚨 VCI net_5d GIỐNG NHAU across mã (giống lỗi CafeF).")
        log.info("   → VCI vẫn hỏng. Giữ Phương án B (loại ff khỏi total / qualifier).")
    elif v_n < 3:
        log.info("⚠️ VCI quá ít data (ngoài giờ GD hoặc mã ít FF).")
        log.info("   → Chạy lại TRONG PHIÊN với mã thanh khoản cao để kết luận chắc.")
    else:
        log.info("⚠️ Kết quả mơ hồ — xem net_5d chi tiết phía trên để quyết định.")


if __name__ == "__main__":
    run()
