"""
scripts/debug_market_orderbook.py
Test Market.equity().order_book() và các hàm liên quan từ vnstock_data
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
os.environ["VNSTOCK_INTERACTIVE"] = "0"
os.environ["VNSTOCK_LANGUAGE"]    = "en"
os.makedirs("/home/runner/.vnstock", exist_ok=True)

import logging
import pandas as pd
from vnstock_data import Market
from utils.helpers import now_ict, is_market_open

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

SYMBOLS = ["BSR", "HPG", "VCB"]

log.info(f"Time: {now_ict():%Y-%m-%d %H:%M:%S} ICT  |  market_open={is_market_open()}")

def test(label, fn):
    try:
        df = fn()
        if df is None or (hasattr(df, 'empty') and df.empty):
            log.warning(f"  [{label}] EMPTY")
            return
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = ["_".join(str(c) for c in col).strip("_") for col in df.columns]
        cols = list(df.columns)
        bid_cols = [c for c in cols if "bid" in c.lower()]
        ask_cols = [c for c in cols if "ask" in c.lower()]
        log.info(f"  [{label}] OK — {len(df)} rows, cols: {cols}")
        if bid_cols or ask_cols:
            log.info(f"    bid cols: {bid_cols}")
            log.info(f"    ask cols: {ask_cols}")
        log.info(f"\n{df.head(3).to_string()}\n")
    except Exception as e:
        log.error(f"  [{label}] ERROR: {e}")

mkt = Market()

for sym in SYMBOLS:
    log.info(f"\n{'='*55}\nSYMBOL: {sym}\n{'='*55}")
    eq = mkt.equity(sym)

    test(f"{sym}.order_book",     lambda e=eq: e.order_book())
    test(f"{sym}.quote",          lambda e=eq: e.quote())
    test(f"{sym}.trades",         lambda e=eq: e.trades())
    test(f"{sym}.volume_profile", lambda e=eq: e.volume_profile())

log.info("\nDONE")
