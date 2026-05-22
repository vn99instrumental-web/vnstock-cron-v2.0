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
from vnstock_data import TopStock, Quote, Trading, Finance
from vnstock_ta import Indicator

from utils.helpers import (
    now_ict, is_market_open, last_trading_date,
    load_exchange_map, get_exchange,
    safe_run, safe_val, to_float,
    start_str, today_str
)
from utils.cache import save_json, save_csv, load_json
from utils.formatter import clean_for_export, fmt_money_bil

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(levelname)s %(message)s'
)
log = logging.getLogger(__name__)

# =====================================================
# KBS Wide-form lookup helper
# =====================================================

def _kbs_lookup(df: pd.DataFrame, keys: list):
    period_cols = [c for c in df.columns
                   if c not in ["item", "item_id"]]
    if not period_cols:
        return None
    latest_col = period_cols[-1]
    idx_col    = "item_id" if "item_id" in df.columns \
                 else df.columns[0]
    df_idx     = df.set_index(idx_col)[latest_col]
    for k in keys:
        if k in df_idx.index:
            return to_float(df_idx[k])
    return None

# =====================================================
# RANKING — TopStock(VND)
# =====================================================

def get_ranking() -> dict:
    log.info("=== RANKING ===")
    ins  = TopStock()
    date = last_trading_date()
    return {
        "gainers": safe_run("gainer",
            lambda: ins.gainer(index="VNINDEX", limit=10)),
        "losers":  safe_run("loser",
            lambda: ins.loser(index="VNINDEX",  limit=10)),
    }

# =====================================================
# SNAPSHOT — Quote(VCI)
# =====================================================

def get_snapshot(symbol: str, market_open: bool) -> dict:
    row = {
        "symbol"    : symbol,
        "exchange"  : get_exchange(symbol),
        "snap_time" : now_ict().strftime("%H:%M"),
    }

    if market_open:
        df_intra = safe_run(f"intraday {symbol}",
            lambda: Quote(source="VCI", symbol=symbol)\
                    .intraday(page_size=200))
        if df_intra is not None and not df_intra.empty:
            df_intra["price"]  = pd.to_numeric(
                df_intra["price"],  errors="coerce")
            df_intra["volume"] = pd.to_numeric(
                df_intra["volume"], errors="coerce")
            row["price"]      = float(df_intra["price"].iloc[-1])
            row["price_type"] = "realtime"
            buy_mask  = df_intra["match_type"].str.contains(
                "Buy", case=False, na=False)
            sell_mask = df_intra["match_type"].str.contains(
                "Sell", case=False, na=False)
            buy_vol  = float(df_intra.loc[buy_mask,  "volume"].sum())
            sell_vol = float(df_intra.loc[sell_mask, "volume"].sum())
            total    = buy_vol + sell_vol
            row["intra_buy_vol"]   = buy_vol
            row["intra_sell_vol"]  = sell_vol
            row["intra_delta"]     = buy_vol - sell_vol
            row["intra_buy_ratio"] = round(buy_vol / total, 2) \
                                     if total > 0 else None
    else:
        df_hist = safe_run(f"history {symbol}",
            lambda: Quote(source="VCI", symbol=symbol)\
                    .history(length="5D", interval="1D"))
        if df_hist is not None and not df_hist.empty:
            df_hist["close"] = pd.to_numeric(
                df_hist["close"], errors="coerce")
            row["price"]      = float(df_hist["close"].iloc[-1])
            row["price_type"] = "last_close"
            row["price_date"] = str(df_hist["time"].iloc[-1])[:10]

    df_depth = safe_run(f"price_depth {symbol}",
        lambda: Quote(source="VCI", symbol=symbol).price_depth())
    if df_depth is not None and not df_depth.empty:
        try:
            b = float(pd.to_numeric(
                df_depth["buy_volume"], errors="coerce").sum())
            s = float(pd.to_numeric(
                df_depth["sell_volume"], errors="coerce").sum())
            row["depth_buy"]       = b
            row["depth_sell"]      = s
            row["depth_buy_ratio"] = round(b / (b + s), 2) \
                                     if (b + s) > 0 else None
        except Exception as e:
            log.error(f"depth error {symbol}: {e}")

    return row

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

    ta  = Indicator(data=df)
    res = {"symbol": symbol}

    # Trend
    ema20 = ta.trend.ema(length=20)
    ema50 = ta.trend.ema(length=50)
    res["ema20"]      = safe_val(ema20)
    res["ema50"]      = safe_val(ema50)
    res["adx"]        = safe_val(ta.trend.adx(length=14))
    res["supertrend"] = safe_val(
        ta.trend.supertrend(length=10, multiplier=3.0))

    # Derived trend
    if res["ema20"] and res["ema50"] and res["ema50"] != 0:
        res["ema_cross_pct"] = round(
            (res["ema20"] - res["ema50"]) / res["ema50"] * 100, 2)
    if res.get("ema20") and df is not None:
        last_price = float(df["close"].iloc[-1])
        res["price_vs_ema20_pct"] = round(
            (last_price - res["ema20"]) / res["ema20"] * 100, 2)

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

    # BB position
    if res["bb_upper"] and res["bb_lower"] and \
       (res["bb_upper"] - res["bb_lower"]) != 0:
        last_price = float(df["close"].iloc[-1])
        res["bb_position"] = round(
            (last_price - res["bb_lower"]) /
            (res["bb_upper"] - res["bb_lower"]), 2)

    # Volume
    res["obv"]  = safe_val(ta.volume.obv())
    res["cmf"]  = safe_val(ta.volume.cmf(length=20))
    res["mfi"]  = safe_val(ta.volume.mfi(length=14))

    return res

# =====================================================
# ORDER FLOW — Trading(VCI)
# =====================================================

def get_flow(symbol: str) -> dict:
    log.info(f"  Flow: {symbol}")
    res = {"symbol": symbol}

    df_ft = safe_run(f"foreign_trade {symbol}",
             lambda: Trading(symbol=symbol, source="VCI").foreign_trade(
                 start=start_str(20), end=today_str()))
    if df_ft is not None and not df_ft.empty:
        net_series = df_ft["fr_net_value_total"]

        res["ff_buy_val_5d"]  = float(
            df_ft["fr_buy_value_matched"].tail(5).sum())
        res["ff_sell_val_5d"] = float(
            df_ft["fr_sell_value_matched"].tail(5).sum())
        res["ff_net_val_5d"]  = float(net_series.tail(5).sum())
        res["ff_net_val_20d"] = float(net_series.sum())

        if "fr_current_room" in df_ft.columns:
            res["ff_room"] = float(
                df_ft["fr_current_room"].iloc[-1])

        # FF derived
        if len(net_series) >= 5:
            import numpy as np
            x = np.arange(len(net_series))
            y = net_series.fillna(0).values
            slope = np.polyfit(x, y, 1)[0]
            res["ff_trend"] = round(float(slope) / 1e9, 2)

            days_positive = (net_series > 0).sum()
            res["ff_consistency"] = round(
                days_positive / len(net_series), 2)

            ff_5d_avg  = net_series.tail(5).mean()
            ff_20d_avg = net_series.mean()
            res["ff_acceleration"] = round(
                float(ff_5d_avg - ff_20d_avg) / 1e9, 2) \
                if ff_20d_avg != 0 else 0

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
# FUNDAMENTAL — Finance(KBS) + Cash Flow
# =====================================================

def get_fundamental(symbol: str) -> dict:
    log.info(f"  Fundamental: {symbol}")
    res = {"symbol": symbol}

    # Ratio
    df_ratio = safe_run(f"ratio {symbol}",
                lambda: Finance(source="KBS", symbol=symbol).ratio(
                    period="quarter", limit=1))
    if df_ratio is not None and not df_ratio.empty:
        period_cols = [c for c in df_ratio.columns
                       if c not in ["item", "item_id"]]
        res["r_period"]      = period_cols[-1] if period_cols else ""
        res["r_pe"]          = _kbs_lookup(df_ratio, ["pe_ratio"])
        res["r_pb"]          = _kbs_lookup(df_ratio, ["pb_ratio"])
        res["r_eps"]         = _kbs_lookup(df_ratio,
            ["trailing_eps", "eps"])
        res["r_bvps"]        = _kbs_lookup(df_ratio,
            ["book_value_per_share_bvps", "bvps"])
        res["r_roe"]         = _kbs_lookup(df_ratio,
            ["roe", "roe_trailling"])
        res["r_roa"]         = _kbs_lookup(df_ratio,
            ["roa", "roa_trailling"])
        res["r_beta"]        = _kbs_lookup(df_ratio, ["beta"])
        res["r_div_yield"]   = _kbs_lookup(df_ratio, ["dividend_yield"])
        res["r_gross_margin"]= _kbs_lookup(df_ratio, ["gross_margin"])
        res["r_net_margin"]  = _kbs_lookup(df_ratio, ["net_margin"])
        res["r_quick_ratio"] = _kbs_lookup(df_ratio, ["quick_ratio"])
        res["r_interest_cov"]= _kbs_lookup(df_ratio, ["interest_coverage"])
        res["r_ev_ebitda"]   = _kbs_lookup(df_ratio, ["ev_ebitda"])

    # Income Statement
    df_is = safe_run(f"income {symbol}",
             lambda: Finance(source="KBS", symbol=symbol)\
                     .income_statement(period="quarter", limit=1))
    if df_is is not None and not df_is.empty:
        res["is_revenue"]          = _kbs_lookup(df_is,
            ["3_net_revenue", "net_revenue"])
        res["is_gross_profit"]     = _kbs_lookup(df_is,
            ["5_gross_profit", "gross_profit"])
        res["is_net_profit"]       = _kbs_lookup(df_is,
            ["profit_after_tax_for_shareholders_of_the_parent_company",
             "18_net_profit_after_tax"])
        res["is_operating_profit"] = _kbs_lookup(df_is,
            ["11_operating_profit"])
        res["is_eps"]              = _kbs_lookup(df_is,
            ["19_earnings_per_share_vnd"])
        res["is_rev_growth"]       = _kbs_lookup(df_is,
            ["revenue_growth", "yoy_revenue"])
        res["is_profit_growth"]    = _kbs_lookup(df_is,
            ["profit_growth", "yoy_profit"])

    # Balance Sheet
    df_bs = safe_run(f"balance_sheet {symbol}",
             lambda: Finance(source="KBS", symbol=symbol)\
                     .balance_sheet(period="quarter", limit=1))
    if df_bs is not None and not df_bs.empty:
        res["bs_total_assets"] = _kbs_lookup(df_bs, ["total_assets"])
        res["bs_equity"]       = _kbs_lookup(df_bs,
            ["owner_s_equity", "d_owner_s_equity"])
        res["bs_total_liab"]   = _kbs_lookup(df_bs, ["c_liabilities"])
        res["bs_short_debt"]   = _kbs_lookup(df_bs,
            ["11_short_term_borrowings_and_financial_leases"])
        res["bs_long_debt"]    = _kbs_lookup(df_bs,
            ["9_long_term_borrowings_and_financial_leases"])

    # Cash Flow — lấy realtime theo symbol
    df_cf = safe_run(f"cash_flow {symbol}",
             lambda: Finance(source="KBS", symbol=symbol)\
                     .cash_flow(period="quarter", limit=1))
    if df_cf is not None and not df_cf.empty:
        res["cf_operating"] = _kbs_lookup(df_cf,
            ["i_cash_flows_from_operating_activities",
             "operating_cash_flow"])
        res["cf_investing"]  = _kbs_lookup(df_cf,
            ["ii_cash_flows_from_investing_activities",
             "investing_cash_flow"])
        res["cf_financing"]  = _kbs_lookup(df_cf,
            ["iii_cash_flows_from_financing_activities",
             "financing_cash_flow"])
        res["cf_free"]       = _kbs_lookup(df_cf,
            ["free_cash_flow", "fcf"])

        # CF quality ratio
        if res.get("cf_operating") and res.get("is_net_profit") \
           and res["is_net_profit"] != 0:
            res["cf_quality_ratio"] = round(
                res["cf_operating"] / res["is_net_profit"], 2)

    return res

# =====================================================
# JOIN INDUSTRY + MARKET CAP METADATA
# =====================================================

def enrich_metadata(row: dict,
                    industry_map: list) -> dict:
    """
    Thêm industry + market_cap_group vào row
    Bỏ pe_vs_industry — dùng PE trực tiếp trong scoring
    """
    symbol = row["symbol"]

    # Industry từ icb_name
    ind_row = next(
        (r for r in industry_map
         if r.get("symbol") == symbol), {})
    row["industry"] = ind_row.get("icb_name", "")
    row["icb_code"]  = ind_row.get("icb_code", "")

    # Market cap group
    market_cap_bil = row.get("market_cap")
    if market_cap_bil:
        if market_cap_bil >= 10000:
            row["market_cap_group"] = "Large"
        elif market_cap_bil >= 1000:
            row["market_cap_group"] = "Mid"
        else:
            row["market_cap_group"] = "Small"

    return row

# =====================================================
# BUILD DEEP ROW — gộp tất cả
# =====================================================

def build_deep_row(symbol: str, group: str,
                   market_open: bool,
                   industry_map: list) -> dict:  # bỏ industry_pe
    log.info(f"\n--- {symbol} ({group}) ---")

    snap = get_snapshot(symbol, market_open)
    ta   = get_ta(symbol)
    flow = get_flow(symbol)
    fund = get_fundamental(symbol)

    row = {
        "symbol"  : symbol,
        "group"   : group,
        "exchange": get_exchange(symbol),
        "time"    : now_ict().strftime("%Y-%m-%d %H:%M"),
        "date"    : today_str(),
        **{k: v for k, v in snap.items()  if k != "symbol"},
        **{k: v for k, v in ta.items()    if k != "symbol"},
        **{k: v for k, v in flow.items()  if k != "symbol"},
        **{k: v for k, v in fund.items()  if k != "symbol"},
    }

    row = enrich_metadata(row, industry_map)  # bỏ industry_pe
    return row

# =====================================================
# MAIN
# =====================================================

if __name__ == "__main__":
    trading = is_market_open()
    log.info(f"Time       : {now_ict():%Y-%m-%d %H:%M:%S} ICT")
    log.info(f"Market open: {trading}")

    load_exchange_map()

    # Load daily context
    industry_map = load_json("industry_map.json") or []
    # industry_pe  = load_json("industry_pe.json")  or {}

    ranking = get_ranking()

    all_ranking_rows = []
    all_deep_rows    = []

    for group, df_rank in [
        ("GAINER", ranking["gainers"]),
        ("LOSER",  ranking["losers"]),
    ]:
        if df_rank is None or df_rank.empty:
            log.warning(f"Không có data: {group}")
            continue

        symbols = df_rank["symbol"].tolist()
        df_rank["exchange"] = df_rank["symbol"].map(get_exchange)
        df_rank["group"]    = group
        df_rank["date"]     = today_str()
        all_ranking_rows.append(df_rank)

        log.info(f"\n=== {group}: {symbols} ===")

        for symbol in symbols:
            row = build_deep_row(
                symbol, group, trading,
                industry_map
            )
            all_deep_rows.append(row)
            log.info(f"  [{symbol}] "
                     f"RSI={row.get('rsi')}, "
                     f"PE={row.get('r_pe')}, "
                     f"FF_net5d={fmt_money_bil(row.get('ff_net_val_5d'))}")

    # ── Export Ranking ──
    if all_ranking_rows:
        df_rank_all = pd.concat(all_ranking_rows, ignore_index=True)
        save_json("ranking.json",
                  df_rank_all.to_dict(orient="records"))
        df_rank_clean = clean_for_export(df_rank_all)
        save_csv("ranking.csv", df_rank_clean)

    # ── Export Deep ──
    if all_deep_rows:
        df_deep = pd.DataFrame(all_deep_rows)

        # Raw JSON — số nguyên, dùng cho scoring/AI
        save_json("deep_raw.json",
                  df_deep.to_dict(orient="records"))

        # Clean JSON/CSV — format tỷ đồng, 2 số lẻ
        df_clean = clean_for_export(df_deep)
        save_json("deep.json", df_clean.to_dict(orient="records"))
        save_csv("deep.csv",   df_clean)

        log.info(f"Deep: {len(df_deep)} rows, "
                 f"{len(df_deep.columns)} cols")

    log.info("=== STEP ALL DONE ===")
