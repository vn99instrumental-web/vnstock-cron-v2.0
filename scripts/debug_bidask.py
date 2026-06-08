"""
scripts/debug_bidask_v2.py — Thử price_depth() với msn, dnse
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
os.environ["VNSTOCK_INTERACTIVE"] = "0"
os.environ["VNSTOCK_LANGUAGE"]    = "en"
os.makedirs("/home/runner/.vnstock", exist_ok=True)

import logging
import pandas as pd
from vnstock_data import Quote
from utils.helpers import now_ict, is_market_open

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

SYMBOLS  = ["BSR", "HPG", "VCB"]
SOURCES  = ["VND", "MAS"]   # vci = matched vol, kbs chưa thử price_depth

log.info(f"Time: {now_ict():%Y-%m-%d %H:%M:%S} ICT  |  market_open={is_market_open()}")

for source in SOURCES:
    log.info(f"\n{'='*50}")
    log.info(f"SOURCE: {source}")
    for sym in SYMBOLS:
        try:
            df = Quote(source=source, symbol=sym).price_depth()
            if df is None or (hasattr(df, 'empty') and df.empty):
                log.warning(f"  [{sym}] EMPTY")
                continue
            # Flatten MultiIndex nếu có
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = ["_".join(str(c) for c in col).strip("_") for col in df.columns]
            cols = list(df.columns)
            log.info(f"  [{sym}] OK — {len(df)} rows, cols: {cols}")
            # Check bid/ask keywords
            bid_cols = [c for c in cols if "bid" in c.lower()]
            ask_cols = [c for c in cols if "ask" in c.lower()]
            log.info(f"    bid cols: {bid_cols}")
            log.info(f"    ask cols: {ask_cols}")
            if bid_cols or ask_cols:
                log.info(f"    sample row:\n{df.iloc[0][bid_cols + ask_cols].to_string()}")
            else:
                log.info(f"    sample row:\n{df.iloc[0].to_string()}")
        except Exception as e:
            log.error(f"  [{sym}] ERROR: {e}")
