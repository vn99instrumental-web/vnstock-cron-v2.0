"""
scripts/debug_depth_compare.py
==========================================================
Mục tiêu:
  1. KBS Trading.price_board() → có bid_price_1..3 / ask_price_1..3 không?
  2. VCI price_depth() vs VCI intraday() — khác nhau thế nào?
     (để xác nhận price_depth là matched-by-price, không phải order book)
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
os.environ["VNSTOCK_INTERACTIVE"] = "0"
os.environ["VNSTOCK_LANGUAGE"]    = "en"
os.makedirs("/home/runner/.vnstock", exist_ok=True)

import logging
import pandas as pd
from vnstock_data import Quote, Trading
from utils.helpers import now_ict, is_market_open

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

SYMBOLS = ["BSR", "HPG", "VCB"]

log.info(f"Time: {now_ict():%Y-%m-%d %H:%M:%S} ICT  |  market_open={is_market_open()}")

# ══════════════════════════════════════════════════════════
# MỤC 1: KBS Trading.price_board() — tìm bid/ask
# ══════════════════════════════════════════════════════════
log.info("\n" + "="*60)
log.info("MỤC 1: KBS Trading.price_board()")
log.info("="*60)
try:
    df_board = Trading(source="KBS").price_board(SYMBOLS)
    if df_board is None or df_board.empty:
        log.warning("  EMPTY")
    else:
        # Flatten MultiIndex nếu có
        if isinstance(df_board.columns, pd.MultiIndex):
            df_board.columns = ["_".join(str(c) for c in col).strip("_")
                                for col in df_board.columns]
        cols = list(df_board.columns)
        bid_cols = [c for c in cols if "bid" in c.lower()]
        ask_cols = [c for c in cols if "ask" in c.lower()]
        log.info(f"  {len(df_board)} rows, {len(cols)} cols")
        log.info(f"  bid cols: {bid_cols}")
        log.info(f"  ask cols: {ask_cols}")
        if bid_cols or ask_cols:
            log.info(f"\n  === BID/ASK DATA ===")
            show_cols = (["symbol"] if "symbol" in cols else []) + bid_cols + ask_cols
            log.info(f"\n{df_board[show_cols].to_string()}")
        else:
            log.warning("  Không thấy cột bid/ask — toàn bộ cols:")
            log.info(f"  {cols}")
            log.info(f"\n{df_board.head(3).to_string()}")
except Exception as e:
    log.error(f"  KBS price_board ERROR: {e}")

# ══════════════════════════════════════════════════════════
# MỤC 2: KBS Trading.matched_by_price() nếu có
# ══════════════════════════════════════════════════════════
log.info("\n" + "="*60)
log.info("MỤC 2: KBS Trading.matched_by_price()")
log.info("="*60)
for sym in SYMBOLS[:1]:  # chỉ test 1 symbol
    try:
        tr = Trading(source="KBS", symbol=sym)
        df = tr.matched_by_price()
        if df is None or df.empty:
            log.warning(f"  [{sym}] EMPTY")
        else:
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = ["_".join(str(c) for c in col).strip("_") for col in df.columns]
            log.info(f"  [{sym}] {len(df)} rows, cols: {list(df.columns)}")
            log.info(f"\n{df.head(5).to_string()}")
    except Exception as e:
        log.error(f"  [{sym}] matched_by_price ERROR: {e}")

# ══════════════════════════════════════════════════════════
# MỤC 3: VCI price_depth() vs intraday() — so sánh
# ══════════════════════════════════════════════════════════
log.info("\n" + "="*60)
log.info("MỤC 3: VCI price_depth() vs intraday() — so sánh BSR")
log.info("="*60)
sym = "BSR"

log.info(f"\n--- VCI price_depth({sym}) ---")
try:
    df_depth = Quote(source="VCI", symbol=sym).price_depth()
    if df_depth is None or df_depth.empty:
        log.warning("  EMPTY")
    else:
        log.info(f"  {len(df_depth)} rows")
        log.info(f"\n{df_depth.to_string()}")
        total_buy  = pd.to_numeric(df_depth["buy_volume"],  errors="coerce").sum()
        total_sell = pd.to_numeric(df_depth["sell_volume"], errors="coerce").sum()
        log.info(f"\n  → Tổng buy_volume : {total_buy:,.0f}")
        log.info(f"  → Tổng sell_volume: {total_sell:,.0f}")
except Exception as e:
    log.error(f"  price_depth ERROR: {e}")

log.info(f"\n--- VCI intraday({sym}, page_size=200) — tail 5 rows ---")
try:
    df_intra = Quote(source="VCI", symbol=sym).intraday(page_size=200)
    if df_intra is None or df_intra.empty:
        log.warning("  EMPTY")
    else:
        log.info(f"  {len(df_intra)} rows, cols: {list(df_intra.columns)}")
        log.info(f"\n{df_intra.tail(5).to_string()}")
        buy_mask  = df_intra["match_type"].str.contains("Buy",  case=False, na=False)
        sell_mask = df_intra["match_type"].str.contains("Sell", case=False, na=False)
        total_buy  = pd.to_numeric(df_intra.loc[buy_mask,  "volume"], errors="coerce").sum()
        total_sell = pd.to_numeric(df_intra.loc[sell_mask, "volume"], errors="coerce").sum()
        log.info(f"\n  → Tổng buy  volume (intraday): {total_buy:,.0f}")
        log.info(f"  → Tổng sell volume (intraday): {total_sell:,.0f}")
        log.info(f"  (So sánh với price_depth ở trên — nếu gần bằng nhau → cùng nguồn data)")
except Exception as e:
    log.error(f"  intraday ERROR: {e}")

log.info("\n" + "="*60)
log.info("DONE")
log.info("="*60)
