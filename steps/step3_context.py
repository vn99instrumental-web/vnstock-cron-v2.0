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
from vnstock_data import Analytics, TopStock

from utils.helpers import now_ict, last_trading_date, safe_run
from utils.cache import save_json, save_csv

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(levelname)s %(message)s'
)
log = logging.getLogger(__name__)

# =====================================================
# MARKET CONTEXT — Analytics(VND) 5Y
# =====================================================

def get_market_context() -> list:
    log.info("=== MARKET CONTEXT ===")

    df_eval = safe_run("vnindex_evaluation",
               lambda: Analytics().valuation("VNINDEX")\
                       .evaluation(duration="5Y"))

    if df_eval is None or df_eval.empty:
        log.warning("Không có data vnindex_evaluation")
        return []

    pe_cur  = float(df_eval["pe"].iloc[-1])
    pb_cur  = float(df_eval["pb"].iloc[-1])
