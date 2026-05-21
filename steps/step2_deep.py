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
from vnstock_data import Quote, Trading, Finance
from vnstock_ta import Indicator

from utils.helpers import (
    now_ict, get_exchange, load_exchange_map,
    safe_run, safe_val, start_str, today_str
)
from utils.cache import load_json, save_json, save_csv
from utils.formatter import clean_for_export

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(levelname)s %(message)s'
)
log = logging.getLogger(__name__)

# =====================================================
# TA INDICATORS
# =====================================================

def get_ta(symbol: str) -> dict:
    log.info(f"  TA: {symbol}")
    df = safe_run(f"ohlcv {symbol}",
         lambda: Quote(source="VCI", symbol=symbol)\
                 .history(length="4M", interval="1D"))

    if df is None or df.empty or len(df) < 20:
        return {"symbol": symbol, "ta_error": "Không đủ data"}

    log.info(f"  ohlcv {symbol}: {len(df)} rows")
    ta  = Indicator(data=df)
    res = {"symbol": symbol}

    res["ema20"]      = safe_val(ta.trend.ema(length=20))
    res["ema50"]      = safe_val(ta.trend.ema(length=50))
    res["adx"]        = safe_val(ta.trend.adx(length=14))
    res["supertrend"] = safe_val(
        ta.trend.supertrend(length=10, multiplier=3.0))
    res["rsi"]        = safe_val(ta.momentum.rsi(length=14))
    macd = ta.momentum.macd(fast=12, slow=26, signal=9)
    res["macd"]       = safe_val(macd, 0)
    res["macd_sig"]   = safe_val(macd, 1)
    res["macd_hist"]  = safe_val(macd, 2)
    stoch = ta.momentum.stoch(k=14, d=3, smooth_k=3)
    res["stoch_k"]    = safe_val(stoch, 0)
    res["stoch_d"]    = safe_val(stoch, 1)
    bb = ta.volatility.bbands(length=20, std=2.0)
    res["bb_upper"]   = safe_val(bb, 0)
    res["bb_mid"]     = safe_val(bb, 1)
    res["bb_lower"]   = safe_val(bb, 2)
    res["atr"]        = safe_val(ta.volatility.atr(length=14))
    res["obv"]        = safe_val(ta.volume.obv())
    res["cmf"]        = safe_val(ta.volume.cmf(length=20))
    res["mfi"]        = safe_val(ta.volume.mfi(length=14))

    return res

# =====================================================
# ORDER FLOW
# =====================================================

def get_flow(symbol: str) -> dict:
    log.info(f"  Flow: {symbol}")
    res = {"symbol": symbol}

    df_ft = safe_run(f"foreign_trade {symbol}",
             lambda: Trading(symbol=symbol, source="VCI").foreign_trade(
                 start=start_str(20), end=today_str()))
    if df_ft is not None and not df_ft.empty:
        res["ff_buy_val_5d"]  = float(
            df_ft["fr_buy_value_matched"].tail(5).sum())
        res["ff_sell_val_5d"] = float(
            df_ft["fr_sell_value_matched"].tail(5).sum())
        res["ff_net_val_5d"]  = float(
            df_ft["fr_net_value_total"].tail(5).sum())
        res["ff_net_val_20d"] = float(
            df_ft["fr_net_value_total"].sum())
        if "fr_current_room" in df_ft.columns:
            res["ff_room"] = float(
                df_ft["fr_current_room"].iloc[-1])

    df_pt = safe_run(f"prop_trade {symbol}",
             lambda: Trading(symbol=symbol, source="VCI").prop_trade(
                 start=start_str(10), end=today_str()))
    if df_pt is not None and not df_pt.empty:
        res["prop_buy_vol_5d"]  = float(
            df_pt["total_buy_trade_volume"].tail(5).sum())
        res["prop_sell_vol_5d"] = float(
            df_pt["total_sell_trade_volume"].tail(5).sum())
        res["prop_net_val_5d"]  = float(
            df_pt["total_trade_net_value"].tail(5).sum())

    df_id = safe_run(f"insider_deal {symbol}",
             lambda: Trading(symbol=symbol, source="VCI")\
                     .insider_deal(limit=5))
    if df_id is not None and not df_id.empty:
        res["insider_count"]  = len(df_id)
        res["insider_latest"] = str(df_id["action_type"].iloc[0]) \
                                if "action_type" in df_id.columns else None
        res["insider_name"]   = str(df_id["trader_name"].iloc[0]) \
                                if "trader_name" in df_id.columns else None

    return res

# =====================================================
# FUNDAMENTAL
# =====================================================

def get_fundamental(symbol: str) -> dict:
    log.info(f"  Fundamental: {symbol}")
    res = {"symbol": symbol}

    df_ratio = safe_run(f"ratio {symbol}",
                lambda: Finance(source="VCI", symbol=symbol).ratio(
                    period="quarter", lang="en"))
    if df_ratio is not None and not df_ratio.empty:
        last = df_ratio.iloc[0]
        col_candidates = {
            "r_pe"       : ["pe", "p_e"],
            "r_pb"       : ["pb", "p_b"],
            "r_eps"      : ["eps"],
            "r_roe"      : ["roe"],
            "r_beta"     : ["beta"],
            "r_div_yield": ["dividend_yield"],
            "r_bvps"     : ["bvps"],
        }
        for dst, candidates in col_candidates.items():
            for c in candidates:
                if c in df_ratio.columns and pd.notna(last.get(c)):
                    try:
                        res[dst] = round(float(last[c]), 2)
                    except:
                        res[dst] = None
                    break
        res["r_period"] = str(last.get("report_period", ""))

    df_is = safe_run(f"income {symbol}",
             lambda: Finance(source="VCI", symbol=symbol)\
                     .income_statement(period="quarter", lang="en"))
    if df_is is not None and not df_is.empty:
        last = df_is.iloc[0]
        for src, dst in {
            "net_revenue"      : "is_revenue",
            "gross_profit"     : "is_gross_profit",
            "net_profit"       : "is_net_profit",
            "net_profit_margin": "is_net_margin",
            "revenue_growth"   : "is_rev_growth",
            "net_profit_growth": "is_profit_growth",
        }.items():
            val = last.get(src)
            res[dst] = round(float(val), 2) \
                       if val is not None and pd.notna(val) else None

    return res

# =====================================================
# MAIN
# =====================================================

if __name__ == "__main__":
    log.info(f"Time: {now_ict():%Y-%m-%d %H:%M:%S} ICT")

    load_exchange_map()

    # Đọc top 3 từ step 1
    top3_cache = load_json("top3_cache.json")
    if not top3_cache:
        log.error("Không tìm thấy top3_cache.json — chạy step1 trước")
        sys.exit(1)

    log.info(f"Top 3 cache: {top3_cache}")

    all_deep_rows = []

    for group_key, group_label in [
        ("gainers", "GAINER"),
        ("losers",  "LOSER"),
    ]:
        symbols = top3_cache.get(group_key, [])
        if not symbols:
            log.warning(f"Không có symbols cho {group_label}")
            continue

        log.info(f"\n=== DEEP {group_label}: {symbols} ===")

        for symbol in symbols:
            ta   = get_ta(symbol)
            flow = get_flow(symbol)
            fund = get_fundamental(symbol)

            row = {
                "symbol"  : symbol,
                "group"   : group_label,
                "exchange": get_exchange(symbol),
                "time"    : now_ict().strftime("%Y-%m-%d %H:%M"),
                **{k: v for k, v in ta.items()   if k != "symbol"},
                **{k: v for k, v in flow.items() if k != "symbol"},
                **{k: v for k, v in fund.items() if k != "symbol"},
            }
            all_deep_rows.append(row)

            log.info(f"  [{symbol}] RSI={row.get('rsi')}, "
                     f"MACD={row.get('macd')}, "
                     f"PE={row.get('r_pe')}, "
                     f"FF_net5d={row.get('ff_net_val_5d')}")

    # Export
    if all_deep_rows:
        df_deep  = pd.DataFrame(all_deep_rows)
        df_clean = clean_for_export(df_deep)
        save_csv("deep.csv", df_clean)
        save_json("deep.json", df_clean.to_dict(orient="records"))
        log.info(f"Exported {len(df_clean)} rows, "
                 f"{len(df_clean.columns)} cols")

    log.info("=== STEP 2 DONE ===")
