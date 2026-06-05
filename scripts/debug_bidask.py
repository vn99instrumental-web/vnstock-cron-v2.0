"""
scripts/debug_bidask.py — Test bid/ask từ vnstock public TCBS
=============================================================
Mục đích:
  1. Xác nhận có lấy được bid_1..3 / ask_1..3 từ TCBS không
  2. Xác nhận ngoài giờ GD trả về gì (rỗng / lỗi / giá trị cũ)
  3. Log đủ thông tin để quyết định có dùng được không

Chạy qua debug.yml:
  workflow_dispatch → script: scripts/debug_bidask.py

Output log sẽ cho biết:
  - market_open: True/False
  - Mỗi symbol: bid_1..3 price/vol, ask_1..3 price/vol
  - Trạng thái: OK / EMPTY / ERROR + exception message
"""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

os.environ["VNSTOCK_INTERACTIVE"] = "0"
os.environ["VNSTOCK_LANGUAGE"]    = "en"
os.makedirs("/home/runner/.vnstock", exist_ok=True)

import logging
import pandas as pd

# public vnstock (không phải vnstock_data sponsor)
from vnstock import Quote as VnstockQuote

from utils.helpers import now_ict, is_market_open, load_exchange_map
from utils.cache import load_json

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s"
)
log = logging.getLogger(__name__)

# ── Test với top 5 symbol đầu từ deep_raw (hoặc hardcode nếu chưa có) ──
FALLBACK_SYMBOLS = ["BSR", "LPB", "VCB", "HPG", "FPT"]


def fetch_bidask(symbol: str) -> dict:
    """
    Gọi vnstock public TCBS price_depth(), extract bid/ask.
    Trả dict với keys:
      status: "OK" | "EMPTY" | "ERROR"
      bid_1_price, bid_1_vol, bid_2_price, bid_2_vol, bid_3_price, bid_3_vol
      ask_1_price, ask_1_vol, ask_2_price, ask_2_vol, ask_3_price, ask_3_vol
      raw_cols: list columns (để debug nếu format thay đổi)
      error: str nếu có
    """
    result = {"symbol": symbol, "status": "ERROR"}
    try:
        df = VnstockQuote(symbol=symbol, source="tcbs").price_depth()

        if df is None or df.empty:
            result["status"] = "EMPTY"
            result["note"]   = "DataFrame None hoặc empty"
            return result

        # Flatten MultiIndex columns nếu có
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = ["_".join(str(c) for c in col).strip("_")
                          for col in df.columns]

        result["raw_cols"] = list(df.columns)
        row = df.iloc[0]

        # Extract bid/ask — tên cột sau flatten: "bid_ask_bid_1_price" etc.
        # Thử cả 2 pattern: có prefix "bid_ask_" và không có
        def _get(col_candidates):
            for c in col_candidates:
                if c in row.index:
                    v = row[c]
                    if pd.notna(v) and v != 0:
                        return float(v)
            return None

        for i in (1, 2, 3):
            result[f"bid_{i}_price"] = _get([
                f"bid_ask_bid_{i}_price", f"bid_{i}_price"
            ])
            result[f"bid_{i}_vol"] = _get([
                f"bid_ask_bid_{i}_volume", f"bid_{i}_volume",
                f"bid_ask_bid_{i}_vol",    f"bid_{i}_vol"
            ])
            result[f"ask_{i}_price"] = _get([
                f"bid_ask_ask_{i}_price", f"ask_{i}_price"
            ])
            result[f"ask_{i}_vol"] = _get([
                f"bid_ask_ask_{i}_volume", f"ask_{i}_volume",
                f"bid_ask_ask_{i}_vol",    f"ask_{i}_vol"
            ])

        # Kiểm tra có data thực không
        has_data = any(
            result.get(f"bid_{i}_price") is not None
            for i in (1, 2, 3)
        )
        result["status"] = "OK" if has_data else "EMPTY"

    except Exception as e:
        result["status"] = "ERROR"
        result["error"]  = str(e)

    return result


def log_result(r: dict):
    sym    = r["symbol"]
    status = r["status"]

    if status == "ERROR":
        log.error(f"  [{sym}] ERROR: {r.get('error', '?')}")
        return

    if status == "EMPTY":
        log.warning(f"  [{sym}] EMPTY — {r.get('note', 'no data')}")
        log.info(f"    raw_cols: {r.get('raw_cols', [])[:10]}")
        return

    # OK — log bid/ask table
    log.info(f"  [{sym}] OK")
    log.info(f"    {'Level':<8} {'Bid Price':>12} {'Bid Vol':>12}  |  {'Ask Price':>12} {'Ask Vol':>12}")
    log.info(f"    {'-'*8} {'-'*12} {'-'*12}  |  {'-'*12} {'-'*12}")
    for i in (1, 2, 3):
        bp = r.get(f"bid_{i}_price")
        bv = r.get(f"bid_{i}_vol")
        ap = r.get(f"ask_{i}_price")
        av = r.get(f"ask_{i}_vol")
        bp_s = f"{bp:,.0f}" if bp else "–"
        bv_s = f"{bv:,.0f}" if bv else "–"
        ap_s = f"{ap:,.0f}" if ap else "–"
        av_s = f"{av:,.0f}" if av else "–"
        log.info(f"    {'bid/ask '+str(i):<8} {bp_s:>12} {bv_s:>12}  |  {ap_s:>12} {av_s:>12}")


if __name__ == "__main__":
    now = now_ict()
    market_open = is_market_open()

    log.info("=" * 60)
    log.info(f"debug_bidask.py")
    log.info(f"Time       : {now:%Y-%m-%d %H:%M:%S} ICT")
    log.info(f"Market open: {market_open}")
    log.info("=" * 60)

    # Lấy symbols từ deep_raw nếu có, fallback hardcode
    deep_raw = load_json("deep_raw.json")
    if deep_raw:
        symbols = [r["symbol"] for r in deep_raw[:5] if r.get("symbol")]
        log.info(f"Symbols từ deep_raw.json: {symbols}")
    else:
        symbols = FALLBACK_SYMBOLS
        log.info(f"deep_raw.json chưa có — dùng fallback: {symbols}")

    log.info("")

    ok_count    = 0
    empty_count = 0
    error_count = 0

    for sym in symbols:
        r = fetch_bidask(sym)
        log_result(r)
        if r["status"] == "OK":    ok_count += 1
        elif r["status"] == "EMPTY": empty_count += 1
        else:                        error_count += 1

    log.info("")
    log.info("=" * 60)
    log.info(f"Kết quả: OK={ok_count}, EMPTY={empty_count}, ERROR={error_count}")
    log.info(f"Market open lúc chạy: {market_open}")
    if empty_count + error_count == len(symbols):
        log.warning("→ TẤT CẢ symbols không có data — có thể ngoài giờ GD hoặc API lỗi")
    elif ok_count == len(symbols):
        log.info("→ Tất cả symbols có bid/ask data ✅")
    else:
        log.info("→ Một phần symbols có data — xem chi tiết từng symbol ở trên")
    log.info("=" * 60)
