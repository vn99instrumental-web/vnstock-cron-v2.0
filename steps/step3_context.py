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
from vnstock_data import Analytics, TopStock, Reference

from utils.helpers import now_ict, last_trading_date, safe_run
from utils.cache import save_json, save_csv

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(levelname)s %(message)s'
)
log = logging.getLogger(__name__)

# =====================================================
# INDUSTRY MAP — Reference(VCI)
# icb_code, icb_name, icb_level, symbol
# =====================================================

def get_industry_map() -> pd.DataFrame:
    log.info("=== INDUSTRY MAP ===")
    df = safe_run("industry_list",
         lambda: Reference().industry.list())
    if df is None or df.empty:
        log.warning("  industry_list trả về empty")
        return pd.DataFrame()
    log.info(f"  cols: {list(df.columns)}")
    log.info(f"  {len(df)} symbols")
    save_json("industry_map.json",
              df.to_dict(orient="records"))
    return df

# =====================================================
# MARKET CONTEXT — Analytics(VND) 5Y
# =====================================================

def get_market_context() -> list:
    log.info("=== MARKET CONTEXT ===")
    df_eval = safe_run("vnindex_evaluation",
               lambda: Analytics().valuation("VNINDEX")\
                       .evaluation(duration="5Y"))
    if df_eval is None or df_eval.empty:
        return []

    pe_cur  = float(df_eval["pe"].iloc[-1])
    pb_cur  = float(df_eval["pb"].iloc[-1])
    pe_mean = float(df_eval["pe"].mean())
    pb_mean = float(df_eval["pb"].mean())
    pe_pct  = float((df_eval["pe"] <= pe_cur).mean())
    pb_pct  = float((df_eval["pb"] <= pb_cur).mean())

    return [{
        "date"             : last_trading_date(),
        "vnindex_pe"       : round(pe_cur,  2),
        "vnindex_pb"       : round(pb_cur,  2),
        "pe_mean_5y"       : round(pe_mean, 2),
        "pb_mean_5y"       : round(pb_mean, 2),
        "pe_min_5y"        : round(float(df_eval["pe"].min()), 2),
        "pe_max_5y"        : round(float(df_eval["pe"].max()), 2),
        "pe_percentile_5y" : round(pe_pct * 100, 1),
        "pb_percentile_5y" : round(pb_pct * 100, 1),
        "market_valuation" : "CHEAP"     if pe_pct < 0.3 else
                             "EXPENSIVE" if pe_pct > 0.7 else "FAIR",
        "updated_at"       : now_ict().strftime("%Y-%m-%d %H:%M"),
    }]

# =====================================================
# FOREIGN FLOW — TopStock(VND)
# =====================================================

def get_foreign_flow() -> list:
    log.info("=== FOREIGN FLOW ===")
    ins  = TopStock()
    date = last_trading_date()
    rows = []
    for label, fn in [
        ("BUY",  lambda: ins.foreign_buy(limit=10,  date=date)),
        ("SELL", lambda: ins.foreign_sell(limit=10, date=date)),
    ]:
        df = safe_run(f"foreign_{label.lower()}", fn)
        if df is not None and not df.empty:
            df["type"] = label
            df["date"] = date
            rows.extend(df.to_dict(orient="records"))
            log.info(f"  {label}: {len(df)} rows")

    return rows

# =====================================================
# MAIN
# =====================================================

if __name__ == "__main__":
    log.info(f"Time: {now_ict():%Y-%m-%d %H:%M:%S} ICT")

    # Industry map — metadata cho symbol
    get_industry_map()

    # Market context
    ctx = get_market_context()
    if ctx:
        save_json("context.json", ctx)
        save_csv("context.csv", pd.DataFrame(ctx))
        c = ctx[0]
        log.info(f"PE={c['vnindex_pe']} "
                 f"pct={c['pe_percentile_5y']}% "
                 f"→ {c['market_valuation']}")

    # Foreign flow
    ff = get_foreign_flow()
    if ff:
        save_json("foreign_flow.json", ff)
        save_csv("foreign_flow.csv", pd.DataFrame(ff))
        log.info(f"Foreign flow: {len(ff)} rows")

    log.info("=== STEP 3 DONE ===")
