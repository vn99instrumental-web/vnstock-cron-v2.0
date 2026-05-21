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

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(levelname)s %(message)s'
)
log = logging.getLogger(__name__)

# =====================================================
# HELPER
# =====================================================

def _to_float(val) -> float | None:
    if val is None:
        return None
    try:
        f = float(val)
        return round(f, 2) if not pd.isna(f) else None
    except Exception:
        return None

def _get_col(row: pd.Series, candidates: list):
    """Thử nhiều tên column, trả về giá trị đầu tiên tìm thấy"""
    for c in candidates:
        if c in row.index and pd.notna(row[c]):
            return _to_float(row[c])
    return None

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

    # Trend
    res["ema20"]      = safe_val(ta.trend.ema(length=20))
    res["ema50"]      = safe_val(ta.trend.ema(length=50))
    res["adx"]        = safe_val(ta.trend.adx(length=14))
    res["supertrend"] = safe_val(
        ta.trend.supertrend(length=10, multiplier=3.0))

    # Momentum
    res["rsi"]       = safe_val(ta.momentum.rsi(length=14))
    macd = ta.momentum.macd(fast=12, slow=26, signal=9)
    res["macd"]      = safe_val(macd, 0)
    res["macd_sig"]  = safe_val(macd, 1)
    res["macd_hist"] = safe_val(macd, 2)
    stoch = ta.momentum.stoch(k=14, d=3, smooth_k=3)
    res["stoch_k"]   = safe_val(stoch, 0)
    res["stoch_d"]   = safe_val(stoch, 1)

    # Volatility
    bb = ta.volatility.bbands(length=20, std=2.0)
    res["bb_upper"]  = safe_val(bb, 0)
    res["bb_mid"]    = safe_val(bb, 1)
    res["bb_lower"]  = safe_val(bb, 2)
    res["atr"]       = safe_val(ta.volatility.atr(length=14))

    # Volume
    res["obv"]  = safe_val(ta.volume.obv())
    res["cmf"]  = safe_val(ta.volume.cmf(length=20))
    res["mfi"]  = safe_val(ta.volume.mfi(length=14))

    return res

# =====================================================
# ORDER FLOW — prop_trade đã bỏ
# =====================================================

def get_flow(symbol: str) -> dict:
    log.info(f"  Flow: {symbol}")
    res = {"symbol": symbol}

    # Foreign trade
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

    # Insider deal
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
# FUNDAMENTAL — Finance(VCI) Long-form
# Columns từ tài liệu 05-finance.md:
#   ratio(): pe, pb, roe, eps, bvps, beta, dividend_yield,
#            roa, current_ratio, quick_ratio,
#            debt_to_equity, interest_coverage
#   income_statement(): net_revenue, gross_profit, net_profit,
#                       net_profit_margin, revenue_growth,
#                       net_profit_growth, ebitda
# =====================================================

def get_fundamental(symbol: str) -> dict:
    log.info(f"  Fundamental: {symbol}")
    res = {"symbol": symbol}

    # --- Ratio ---
    df_ratio = safe_run(f"ratio {symbol}",
                lambda: Finance(source="VCI", symbol=symbol).ratio(
                    period="quarter", lang="en"))
    if df_ratio is not None and not df_ratio.empty:
        last = df_ratio.iloc[0]   # dòng mới nhất (kỳ gần nhất)
        log.info(f"  ratio cols: {list(df_ratio.columns)}")

        # Định giá
        res["r_pe"]        = _get_col(last, ["pe", "P/E"])
        res["r_pb"]        = _get_col(last, ["pb", "P/B"])
        res["r_eps"]       = _get_col(last, ["eps", "EPS"])
        res["r_bvps"]      = _get_col(last, ["bvps", "BVPS"])

        # Hiệu quả
        res["r_roe"]       = _get_col(last, ["roe", "ROE"])
        res["r_roa"]       = _get_col(last, ["roa", "ROA"])

        # Rủi ro & cổ tức
        res["r_beta"]      = _get_col(last, ["beta", "Beta"])
        res["r_div_yield"] = _get_col(last,
            ["dividend_yield", "div_yield", "Dividend Yield"])

        # Thanh khoản & nợ
        res["r_current_ratio"] = _get_col(last,
            ["current_ratio", "Current Ratio"])
        res["r_quick_ratio"]   = _get_col(last,
            ["quick_ratio", "Quick Ratio"])
        res["r_debt_equity"]   = _get_col(last,
            ["debt_to_equity", "Debt/Equity"])

        res["r_period"] = str(last.get("report_period", ""))

    # --- Income statement ---
    df_is = safe_run(f"income {symbol}",
             lambda: Finance(source="VCI", symbol=symbol)\
                     .income_statement(period="quarter", lang="en"))
    if df_is is not None and not df_is.empty:
        last = df_is.iloc[0]
        log.info(f"  income cols: {list(df_is.columns)}")

        res["is_revenue"]       = _get_col(last,
            ["net_revenue", "Net Revenue", "revenue"])
        res["is_gross_profit"]  = _get_col(last,
            ["gross_profit", "Gross Profit"])
        res["is_net_profit"]    = _get_col(last,
            ["net_profit", "Net Profit"])
        res["is_ebitda"]        = _get_col(last,
            ["ebitda", "EBITDA"])
        res["is_net_margin"]    = _get_col(last,
            ["net_profit_margin", "Net Profit Margin"])
        res["is_rev_growth"]    = _get_col(last,
            ["revenue_growth", "Revenue Growth"])
        res["is_profit_growth"] = _get_col(last,
            ["net_profit_growth", "Net Profit Growth"])

    # --- Balance sheet — thêm từ tài liệu ---
    df_bs = safe_run(f"balance_sheet {symbol}",
             lambda: Finance(source="VCI", symbol=symbol)\
                     .balance_sheet(period="quarter", lang="en"))
    if df_bs is not None and not df_bs.empty:
        last = df_bs.iloc[0]
        log.info(f"  balance cols: {list(df_bs.columns)}")

        res["bs_total_assets"]   = _get_col(last,
            ["total_assets", "Total Assets"])
        res["bs_total_equity"]   = _get_col(last,
            ["total_equity", "Total Equity",
             "owner_equity", "Stockholders Equity"])
        res["bs_short_debt"]     = _get_col(last,
            ["short_term_debt", "Short Term Debt"])
        res["bs_long_debt"]      = _get_col(last,
            ["long_term_debt", "Long Term Debt"])

    return res

# =====================================================
# MAIN
# =====================================================

if __name__ == "__main__":
    log.info(f"Time: {now_ict():%Y-%m-%d %H:%M:%S} ICT")

    load_exchange_map()

    top3_cache = load_json("top3_cache.json")
    if not top3_cache:
        log.error("Không tìm thấy top3_cache.json")
        sys.exit(1)

    log.info(f"Top 3: {top3_cache}")

    all_deep_rows = []

    for group_key, group_label in [
        ("gainers", "GAINER"),
        ("losers",  "LOSER"),
    ]:
        symbols = top3_cache.get(group_key, [])
        if not symbols:
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

            log.info(f"  [{symbol}]")
            log.info(f"    TA   : RSI={row.get('rsi')}, "
                     f"MACD={row.get('macd')}, "
                     f"ADX={row.get('adx')}")
            log.info(f"    Ratio: PE={row.get('r_pe')}, "
                     f"PB={row.get('r_pb')}, "
                     f"ROE={row.get('r_roe')}, "
                     f"EPS={row.get('r_eps')}")
            log.info(f"    IS   : Rev={row.get('is_revenue')}, "
                     f"Margin={row.get('is_net_margin')}, "
                     f"Growth={row.get('is_profit_growth')}")
            log.info(f"    BS   : Assets={row.get('bs_total_assets')}, "
                     f"Equity={row.get('bs_total_equity')}")
            log.info(f"    FF   : net5d={row.get('ff_net_val_5d')}, "
                     f"net20d={row.get('ff_net_val_20d')}")
            log.info(f"    Insider: {row.get('insider_count')} deals, "
                     f"{row.get('insider_latest')} "
                     f"by {row.get('insider_name')}")

    if all_deep_rows:
        df_deep  = pd.DataFrame(all_deep_rows)

        # Export raw JSON — giữ nguyên số để dùng cho AI/analysis
        save_json("deep_raw.json", df_deep.to_dict(orient="records"))

        # Export clean CSV/JSON — format đẹp cho Google Sheets
        from utils.formatter import clean_for_export
        df_clean = clean_for_export(df_deep)
        save_csv("deep.csv",   df_clean)
        save_json("deep.json", df_clean.to_dict(orient="records"))

        log.info(f"Exported {len(df_deep)} rows, "
                 f"{len(df_deep.columns)} cols")
        log.info(f"Columns: {list(df_clean.columns)}")
