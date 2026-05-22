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
# HELPERS
# =====================================================

def _to_float(val) -> float | None:
    if val is None:
        return None
    try:
        f = float(val)
        return round(f, 2) if not pd.isna(f) else None
    except Exception:
        return None

def _kbs_lookup(df: pd.DataFrame, keys: list) -> float | None:
    """
    KBS Wide-form: rows=item_id, cols=kỳ báo cáo
    Tìm item_id trong danh sách keys, lấy giá trị kỳ mới nhất
    """
    period_cols = [c for c in df.columns
                   if c not in ["item", "item_id"]]
    if not period_cols:
        return None
    latest_col = period_cols[-1]

    idx_col = "item_id" if "item_id" in df.columns else df.columns[0]
    df_idx  = df.set_index(idx_col)[latest_col]

    for k in keys:
        if k in df_idx.index:
            return _to_float(df_idx[k])
    return None

# =====================================================
# TA INDICATORS — vnstock_ta
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
# ORDER FLOW — Trading(VCI)
# prop_trade đã bỏ do bug thư viện
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
# FUNDAMENTAL
# Dùng KBS (Wide-form) cho ratio/income/balance
# Wide-form: rows=item_id, cols=kỳ báo cáo
# =====================================================

def get_fundamental(symbol: str) -> dict:
    log.info(f"  Fundamental: {symbol}")
    res = {"symbol": symbol}

    # --- RATIO — KBS ---
    df_ratio = safe_run(f"ratio {symbol}",
                lambda: Finance(source="KBS", symbol=symbol).ratio(
                    period="quarter", limit=1))
    if df_ratio is not None and not df_ratio.empty:
        log.info(f"  ratio cols : {list(df_ratio.columns)}")
        log.info(f"  ratio items: {df_ratio.get('item_id', df_ratio.iloc[:,0]).tolist()}")

        period_cols = [c for c in df_ratio.columns
                       if c not in ["item", "item_id"]]
        res["r_period"] = period_cols[-1] if period_cols else ""

        res["r_pe"]            = _kbs_lookup(df_ratio,
            ["pe_ratio", "pe", "P/E", "price_to_earnings"])
        res["r_pb"]            = _kbs_lookup(df_ratio,
            ["pb_ratio", "pb", "P/B", "price_to_book"])
        res["r_eps"]           = _kbs_lookup(df_ratio,
            ["eps", "EPS", "earnings_per_share"])
        res["r_bvps"]          = _kbs_lookup(df_ratio,
            ["bvps", "book_value_per_share"])
        res["r_roe"]           = _kbs_lookup(df_ratio,
            ["roe", "ROE", "return_on_equity"])
        res["r_roa"]           = _kbs_lookup(df_ratio,
            ["roa", "ROA", "return_on_assets"])
        res["r_beta"]          = _kbs_lookup(df_ratio,
            ["beta", "Beta"])
        res["r_div_yield"]     = _kbs_lookup(df_ratio,
            ["dividend_yield", "div_yield", "dividend_ratio"])
        res["r_current_ratio"] = _kbs_lookup(df_ratio,
            ["current_ratio", "liquidity_ratio"])
        res["r_quick_ratio"]   = _kbs_lookup(df_ratio,
            ["quick_ratio", "acid_test_ratio"])
        res["r_debt_equity"]   = _kbs_lookup(df_ratio,
            ["debt_to_equity", "debt_equity", "d_e_ratio"])

    # --- INCOME STATEMENT — KBS ---
    df_is = safe_run(f"income {symbol}",
             lambda: Finance(source="KBS", symbol=symbol)\
                     .income_statement(period="quarter", limit=1))
    if df_is is not None and not df_is.empty:
        log.info(f"  income cols : {list(df_is.columns)}")
        log.info(f"  income items: {df_is.get('item_id', df_is.iloc[:,0]).tolist()}")

        res["is_revenue"]       = _kbs_lookup(df_is,
            ["net_revenue", "revenue", "net_sales", "total_revenue"])
        res["is_gross_profit"]  = _kbs_lookup(df_is,
            ["gross_profit", "gross_income"])
        res["is_net_profit"]    = _kbs_lookup(df_is,
            ["net_profit", "profit_after_tax", "net_income"])
        res["is_ebitda"]        = _kbs_lookup(df_is,
            ["ebitda", "EBITDA"])
        res["is_net_margin"]    = _kbs_lookup(df_is,
            ["net_profit_margin", "profit_margin", "net_margin"])
        res["is_rev_growth"]    = _kbs_lookup(df_is,
            ["revenue_growth", "yoy_revenue_growth"])
        res["is_profit_growth"] = _kbs_lookup(df_is,
            ["net_profit_growth", "yoy_profit_growth"])

    # --- BALANCE SHEET — KBS ---
    df_bs = safe_run(f"balance_sheet {symbol}",
             lambda: Finance(source="KBS", symbol=symbol)\
                     .balance_sheet(period="quarter", limit=1))
    if df_bs is not None and not df_bs.empty:
        log.info(f"  bs cols : {list(df_bs.columns)}")
        log.info(f"  bs items: {df_bs.get('item_id', df_bs.iloc[:,0]).tolist()}")

        res["bs_total_assets"] = _kbs_lookup(df_bs,
            ["total_assets", "assets"])
        res["bs_equity"]       = _kbs_lookup(df_bs,
            ["equity", "total_equity", "owner_equity",
             "stockholders_equity"])
        res["bs_total_liab"]   = _kbs_lookup(df_bs,
            ["total_liabilities", "total_liability", "liabilities"])
        res["bs_short_debt"]   = _kbs_lookup(df_bs,
            ["short_term_debt", "short_term_borrowing",
             "short_term_loan"])
        res["bs_long_debt"]    = _kbs_lookup(df_bs,
            ["long_term_debt", "long_term_borrowing",
             "long_term_loan"])

    # --- CASH FLOW — KBS ---
    df_cf = safe_run(f"cash_flow {symbol}",
             lambda: Finance(source="KBS", symbol=symbol)\
                     .cash_flow(period="quarter", limit=1))
    if df_cf is not None and not df_cf.empty:
        log.info(f"  cf cols : {list(df_cf.columns)}")

        res["cf_operating"]  = _kbs_lookup(df_cf,
            ["operating_cash_flow", "cfo",
             "net_cash_from_operating"])
        res["cf_investing"]  = _kbs_lookup(df_cf,
            ["investing_cash_flow", "cfi",
             "net_cash_from_investing"])
        res["cf_financing"]  = _kbs_lookup(df_cf,
            ["financing_cash_flow", "cff",
             "net_cash_from_financing"])
        res["cf_free"]       = _kbs_lookup(df_cf,
            ["free_cash_flow", "fcf"])

    return res

# =====================================================
# MAIN
# =====================================================

if __name__ == "__main__":
    log.info(f"Time: {now_ict():%Y-%m-%d %H:%M:%S} ICT")

    load_exchange_map()

    top3_cache = load_json("top3_cache.json")
    if not top3_cache:
        log.error("Không tìm thấy top3_cache.json — chạy step1 trước")
        sys.exit(1)

    log.info(f"Top 3: {top3_cache}")

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

            log.info(f"  [{symbol}]")
            log.info(f"    TA      : RSI={row.get('rsi')}, "
                     f"MACD={row.get('macd')}/{row.get('macd_hist')}, "
                     f"ADX={row.get('adx')}")
            log.info(f"    BB      : {row.get('bb_lower')}|"
                     f"{row.get('bb_mid')}|{row.get('bb_upper')}, "
                     f"ATR={row.get('atr')}")
            log.info(f"    Ratio   : PE={row.get('r_pe')}, "
                     f"PB={row.get('r_pb')}, "
                     f"ROE={row.get('r_roe')}, "
                     f"EPS={row.get('r_eps')}, "
                     f"Period={row.get('r_period')}")
            log.info(f"    IS      : Rev={row.get('is_revenue')}, "
                     f"Margin={row.get('is_net_margin')}, "
                     f"Growth={row.get('is_profit_growth')}")
            log.info(f"    BS      : Assets={row.get('bs_total_assets')}, "
                     f"Equity={row.get('bs_equity')}")
            log.info(f"    CF      : Oper={row.get('cf_operating')}, "
                     f"Free={row.get('cf_free')}")
            log.info(f"    FF      : net5d={row.get('ff_net_val_5d')}, "
                     f"net20d={row.get('ff_net_val_20d')}, "
                     f"room={row.get('ff_room')}")
            log.info(f"    Insider : {row.get('insider_count')} deals, "
                     f"{row.get('insider_latest')} "
                     f"by {row.get('insider_name')}")

    # Export
    if all_deep_rows:
        df_deep = pd.DataFrame(all_deep_rows)

        # Raw JSON — giữ nguyên số để dùng cho AI/analysis
        save_json("deep_raw.json",
                  df_deep.to_dict(orient="records"))

        # Clean CSV/JSON — format đẹp cho Google Sheets
        df_clean = clean_for_export(df_deep)
        save_csv("deep.csv",   df_clean)
        save_json("deep.json", df_clean.to_dict(orient="records"))

        log.info(f"Exported {len(df_deep)} rows, "
                 f"{len(df_deep.columns)} cols")
        log.info(f"Columns: {list(df_clean.columns)}")

    log.info("=== STEP 2 DONE ===")
