import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

os.environ["VNSTOCK_INTERACTIVE"] = "0"
os.environ["VNSTOCK_LANGUAGE"]    = "en"
os.environ["MPLCONFIGDIR"]        = "/home/runner/.config/matplotlib"
os.makedirs("/home/runner/.vnstock",           exist_ok=True)
os.makedirs("/home/runner/.config/matplotlib", exist_ok=True)

import logging
import numpy as np
import pandas as pd
from vnstock_data import TopStock, Quote, Trading, Finance
from vnstock_ta import Indicator

from utils.helpers import (
    now_ict, is_market_open,
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
# KBS helpers
# =====================================================

def _kbs_lookup(df: pd.DataFrame, keys: list,
                col: str | None = None) -> float | None:
    """Tìm item_id trong keys, lấy giá trị cột col (mặc định kỳ mới nhất)."""
    if df is None or df.empty:
        return None
    period_cols = [c for c in df.columns if c not in ["item", "item_id"]]
    if not period_cols:
        return None
    target_col = col if col else period_cols[-1]
    idx_col    = "item_id" if "item_id" in df.columns else df.columns[0]
    try:
        df_idx = df.set_index(idx_col)[target_col]
    except Exception:
        return None
    for k in keys:
        if k in df_idx.index:
            return to_float(df_idx[k])
    return None

def _kbs_growth(df: pd.DataFrame, keys: list) -> float | None:
    """QoQ growth: (kỳ[-1] - kỳ[-2]) / abs(kỳ[-2]). Cần limit>=2."""
    if df is None or df.empty:
        return None
    period_cols = [c for c in df.columns if c not in ["item", "item_id"]]
    if len(period_cols) < 2:
        return None
    v_new  = _kbs_lookup(df, keys, period_cols[-1])
    v_prev = _kbs_lookup(df, keys, period_cols[-2])
    if v_new is None or v_prev is None or v_prev == 0:
        return None
    return round((v_new - v_prev) / abs(v_prev), 4)

# =====================================================
# RANKING
# =====================================================

def get_ranking() -> dict:
    log.info("=== RANKING ===")
    ins = TopStock()
    return {
        "gainers": safe_run("gainer",
            lambda: ins.gainer(index="VNINDEX", limit=10)),
        "losers":  safe_run("loser",
            lambda: ins.loser(index="VNINDEX",  limit=10)),
    }

# =====================================================
# SNAPSHOT
# =====================================================

def get_snapshot(symbol: str, market_open: bool) -> dict:
    row = {
        "symbol"   : symbol,
        "exchange" : get_exchange(symbol),
        "snap_time": now_ict().strftime("%H:%M"),
    }

    if market_open:
        df_intra = safe_run(f"intraday {symbol}",
            lambda: Quote(source="VCI", symbol=symbol).intraday(page_size=200))
        if df_intra is not None and not df_intra.empty:
            df_intra["price"]  = pd.to_numeric(df_intra["price"],  errors="coerce")
            df_intra["volume"] = pd.to_numeric(df_intra["volume"], errors="coerce")
            row["price"]      = float(df_intra["price"].iloc[-1])
            row["price_type"] = "realtime"
            buy_mask  = df_intra["match_type"].str.contains("Buy",  case=False, na=False)
            sell_mask = df_intra["match_type"].str.contains("Sell", case=False, na=False)
            buy_vol   = float(df_intra.loc[buy_mask,  "volume"].sum())
            sell_vol  = float(df_intra.loc[sell_mask, "volume"].sum())
            total     = buy_vol + sell_vol
            row["intra_buy_vol"]   = buy_vol
            row["intra_sell_vol"]  = sell_vol
            row["intra_delta"]     = buy_vol - sell_vol
            row["intra_buy_ratio"] = round(buy_vol / total, 2) if total > 0 else None
    else:
        df_hist = safe_run(f"history {symbol}",
            lambda: Quote(source="VCI", symbol=symbol).history(length="5D", interval="1D"))
        if df_hist is not None and not df_hist.empty:
            df_hist["close"] = pd.to_numeric(df_hist["close"], errors="coerce")
            row["price"]      = float(df_hist["close"].iloc[-1])
            row["price_type"] = "last_close"
            row["price_date"] = str(df_hist["time"].iloc[-1])[:10]

    df_depth = safe_run(f"price_depth {symbol}",
        lambda: Quote(source="VCI", symbol=symbol).price_depth())
    if df_depth is not None and not df_depth.empty:
        try:
            b = float(pd.to_numeric(df_depth["buy_volume"],  errors="coerce").sum())
            s = float(pd.to_numeric(df_depth["sell_volume"], errors="coerce").sum())
            row["depth_buy"]       = b
            row["depth_sell"]      = s
            row["depth_buy_ratio"] = round(b / (b + s), 2) if (b + s) > 0 else None
        except Exception as e:
            log.error(f"depth error {symbol}: {e}")

    return row

# =====================================================
# TA INDICATORS + store ohlcv_5d cho order_flow reuse
# =====================================================

def get_ta(symbol: str) -> dict:
    df = safe_run(f"ohlcv {symbol}",
         lambda: Quote(source="VCI", symbol=symbol).history(length="4M", interval="1D"))

    if df is None or df.empty or len(df) < 20:
        return {"symbol": symbol, "ta_error": "Không đủ data"}

    ta         = Indicator(data=df)
    res        = {"symbol": symbol}
    last_close = float(df["close"].iloc[-1])

    ema20 = ta.trend.ema(length=20)
    ema50 = ta.trend.ema(length=50)
    res["ema20"]      = safe_val(ema20)
    res["ema50"]      = safe_val(ema50)
    res["adx"]        = safe_val(ta.trend.adx(length=14))
    res["supertrend"] = safe_val(ta.trend.supertrend(length=10, multiplier=3.0))

    if res["ema20"] and res["ema50"] and res["ema50"] != 0:
        res["ema_cross_pct"] = round(
            (res["ema20"] - res["ema50"]) / res["ema50"] * 100, 2)
    if res.get("ema20") and res["ema20"] != 0:
        res["price_vs_ema20_pct"] = round(
            (last_close - res["ema20"]) / res["ema20"] * 100, 2)

    res["rsi"]       = safe_val(ta.momentum.rsi(length=14))
    macd = ta.momentum.macd(fast=12, slow=26, signal=9)
    res["macd"]      = safe_val(macd, 0)
    res["macd_sig"]  = safe_val(macd, 1)
    res["macd_hist"] = safe_val(macd, 2)
    stoch = ta.momentum.stoch(k=14, d=3, smooth_k=3)
    res["stoch_k"]   = safe_val(stoch, 0)
    res["stoch_d"]   = safe_val(stoch, 1)

    bb = ta.volatility.bbands(length=20, std=2.0)
    res["bb_upper"] = safe_val(bb, 0)
    res["bb_mid"]   = safe_val(bb, 1)
    res["bb_lower"] = safe_val(bb, 2)
    res["atr"]      = safe_val(ta.volatility.atr(length=14))

    if res["bb_upper"] and res["bb_lower"] and \
       (res["bb_upper"] - res["bb_lower"]) != 0:
        res["bb_position"] = round(
            (last_close - res["bb_lower"]) /
            (res["bb_upper"] - res["bb_lower"]), 2)
    if res.get("atr") and last_close:
        res["atr_pct"] = round(res["atr"] / last_close * 100, 2)

    res["obv"] = safe_val(ta.volume.obv())
    res["cmf"] = safe_val(ta.volume.cmf(length=20))
    res["mfi"] = safe_val(ta.volume.mfi(length=14))

    # Lưu 5D OHLCV để step_order_flow reuse, không fetch lại
    df["volume"] = pd.to_numeric(df["volume"], errors="coerce")
    df_5d    = df.tail(5)
    avg_vol  = float(df_5d["volume"].mean()) if not df_5d.empty else 0
    ohlcv_5d = []
    for _, row in df_5d.iterrows():
        vol = float(row["volume"]) if pd.notna(row["volume"]) else 0
        ohlcv_5d.append({
            "date"        : str(row["time"])[:10],
            "open"        : round(float(row["open"]),  2),
            "high"        : round(float(row["high"]),  2),
            "low"         : round(float(row["low"]),   2),
            "close"       : round(float(row["close"]), 2),
            "volume"      : int(vol),
            "vs_avg5d_pct": round(vol / avg_vol * 100 - 100, 1)
                            if avg_vol > 0 else None,
        })
    res["_ohlcv_5d"] = ohlcv_5d

    return res

# =====================================================
# FLOW — CafeF trực tiếp (VCI 100% fail, confirmed từ log)
# =====================================================

def get_flow(symbol: str) -> dict:
    res = {"symbol": symbol}

    df_ft = safe_run(f"foreign_trade {symbol}",
             lambda: Trading(symbol=symbol, source="CafeF").foreign_trade(
                 start=start_str(20), end=today_str()))

    if df_ft is not None and not df_ft.empty:
        # CafeF columns: fr_buy_volume, fr_sell_volume, fr_net_volume
        # Đơn vị: VND (đồng) — confirmed từ log analysis
        df_ft = df_ft.rename(columns={
            "fr_buy_volume" : "fr_buy_value_matched",
            "fr_sell_volume": "fr_sell_value_matched",
            "fr_net_volume" : "fr_net_value_total",
        })
        net = df_ft["fr_net_value_total"]
        res["ff_buy_val_5d"]  = float(df_ft["fr_buy_value_matched"].tail(5).sum())
        res["ff_sell_val_5d"] = float(df_ft["fr_sell_value_matched"].tail(5).sum())
        res["ff_net_val_5d"]  = float(net.tail(5).sum())
        res["ff_net_val_20d"] = float(net.sum())
        if "fr_current_room" in df_ft.columns:
            res["ff_room"] = float(df_ft["fr_current_room"].iloc[-1])

        if len(net) >= 5:
            x     = np.arange(len(net))
            y     = net.fillna(0).values
            slope = np.polyfit(x, y, 1)[0]
            res["ff_trend"]       = round(float(slope) / 1e9, 2)
            res["ff_consistency"] = round((net > 0).sum() / len(net), 2)
            ff_5d_avg  = net.tail(5).mean()
            ff_20d_avg = net.mean()
            res["ff_acceleration"] = round(
                float(ff_5d_avg - ff_20d_avg) / 1e9, 2) \
                if ff_20d_avg != 0 else 0

    df_id = safe_run(f"insider_deal_vci {symbol}",
             lambda: Trading(symbol=symbol, source="VCI").insider_deal(limit=5))
    if df_id is None:
        df_id = safe_run(f"insider_deal_cafef {symbol}",
                 lambda: Trading(symbol=symbol, source="CafeF").insider_deal(limit=5))
        if df_id is not None and not df_id.empty:
            df_id = df_id.rename(columns={
                "transaction_man"          : "trader_name",
                "transaction_man_position" : "trader_position",
                "transaction_note"         : "action_type",
            })

    if df_id is not None and not df_id.empty:
        res["insider_count"]  = len(df_id)
        res["insider_latest"] = str(df_id["action_type"].iloc[0]) \
                                if "action_type" in df_id.columns else None
        res["insider_name"]   = str(df_id["trader_name"].iloc[0]) \
                                if "trader_name" in df_id.columns else None

    return res

# =====================================================
# FUNDAMENTAL — Finance(KBS)
#
# FIXES từ debug_kbs.py log:
# 1. Income: profit_after_tax_for_shareholders_of_parent_company
#    (không có _the_ — đây là key thực tế KBS trả về)
# 2. Income: limit=4 để tính QoQ growth
# 3. BS: total_assets = nan (header row) → tính a_short + b_long
# 4. CF: KBS trộn CF items vào balance_sheet() DataFrame
#    → đọc cf_operating/investing/financing từ df_bs, không phải df_cf
# 5. Đơn vị KBS = NGHÌN ĐỒNG (không phải triệu, không phải đồng)
#    → scoring dùng raw nên không ảnh hưởng
#    → formatter.py phải chia 1e6 để ra tỷ
# =====================================================

def get_fundamental(symbol: str) -> dict:
    log.info(f"  Fundamental: {symbol}")
    res = {"symbol": symbol}

    # ── RATIO ──
    df_ratio = safe_run(f"ratio {symbol}",
                lambda: Finance(source="KBS", symbol=symbol).ratio(
                    period="quarter", limit=1))
    if df_ratio is not None and not df_ratio.empty:
        period_cols     = [c for c in df_ratio.columns if c not in ["item", "item_id"]]
        res["r_period"] = period_cols[-1] if period_cols else ""
        res["r_pe"]     = _kbs_lookup(df_ratio, ["pe_ratio"])
        res["r_pb"]     = _kbs_lookup(df_ratio, ["pb_ratio"])
        res["r_eps"]    = _kbs_lookup(df_ratio, ["trailing_eps", "eps"])
        res["r_bvps"]   = _kbs_lookup(df_ratio, ["book_value_per_share_bvps", "bvps"])
        res["r_roe"]    = _kbs_lookup(df_ratio, ["roe", "roe_trailling"])
        res["r_roa"]    = _kbs_lookup(df_ratio, ["roa_trailling", "roa"])
        res["r_beta"]         = _kbs_lookup(df_ratio, ["beta"])
        res["r_div_yield"]    = _kbs_lookup(df_ratio, ["dividend_yield"])
        res["r_gross_margin"] = _kbs_lookup(df_ratio, ["gross_margin"])
        res["r_net_margin"]   = _kbs_lookup(df_ratio, ["net_margin"])
        res["r_quick_ratio"]  = _kbs_lookup(df_ratio, ["quick_ratio"])
        res["r_interest_cov"] = _kbs_lookup(df_ratio, ["interest_coverage"])
        res["r_ev_ebitda"]    = _kbs_lookup(df_ratio, ["ev_ebitda"])

    # ── INCOME STATEMENT — limit=4 cho QoQ growth ──
    df_is = safe_run(f"income {symbol}",
             lambda: Finance(source="KBS", symbol=symbol).income_statement(
                 period="quarter", limit=4))
    if df_is is not None and not df_is.empty:
        idx_col = "item_id" if "item_id" in df_is.columns else df_is.columns[0]
        log.info(f"  income items: {df_is[idx_col].tolist()[:8]}")

        res["is_revenue"]          = _kbs_lookup(df_is,
            ["3_net_revenue", "net_revenue", "1_revenue"])
        res["is_gross_profit"]     = _kbs_lookup(df_is,
            ["5_gross_profit", "gross_profit"])
        res["is_net_profit"]       = _kbs_lookup(df_is,
            # FIX: không có _the_ — confirmed từ debug log
            ["profit_after_tax_for_shareholders_of_parent_company",
             "18_net_profit_after_tax",
             "profit_after_tax_for_shareholders_of_the_parent_company"])
        res["is_operating_profit"] = _kbs_lookup(df_is,
            ["11_operating_profit", "operating_profit"])
        res["is_eps"]              = _kbs_lookup(df_is,
            ["19_earnings_per_share_vnd", "earnings_per_share"])

        # QoQ growth — cần ít nhất 2 kỳ (limit=4)
        res["is_rev_growth"]    = _kbs_growth(df_is,
            ["3_net_revenue", "net_revenue", "1_revenue"])
        res["is_profit_growth"] = _kbs_growth(df_is,
            ["profit_after_tax_for_shareholders_of_parent_company",
             "18_net_profit_after_tax",
             "profit_after_tax_for_shareholders_of_the_parent_company"])

    # ── BALANCE SHEET ──
    # FIX: KBS trộn CF items vào BS DataFrame.
    # Đọc tất cả từ df_bs: BS fields + CF fields cùng 1 call.
    df_bs = safe_run(f"balance_sheet {symbol}",
             lambda: Finance(source="KBS", symbol=symbol).balance_sheet(
                 period="quarter", limit=1))
    if df_bs is not None and not df_bs.empty:
        idx_col  = "item_id" if "item_id" in df_bs.columns else df_bs.columns[0]
        bs_items = df_bs[idx_col].tolist()
        log.info(f"  bs items (first 15): {bs_items[:15]}")
        log.info(f"  bs items (all CF-related): "
                 f"{[x for x in bs_items if 'cash' in str(x).lower() or 'flow' in str(x).lower()]}")

        # BS — total_assets = nan (header), tính tổng 2 dòng con
        short_assets = _kbs_lookup(df_bs, ["a_short_term_assets"])
        long_assets  = _kbs_lookup(df_bs, ["b_long_term_assets"])
        if short_assets is not None and long_assets is not None:
            res["bs_total_assets"] = round(short_assets + long_assets, 2)
        else:
            # Fallback: thử total_assets (có thể không nan trên một số symbols)
            res["bs_total_assets"] = _kbs_lookup(df_bs, ["total_assets"])

        res["bs_equity"] = _kbs_lookup(df_bs,
            ["owner_s_equity", "d_owner_s_equity",
             "total_equity", "equity"])
        res["bs_total_liab"] = _kbs_lookup(df_bs,
            ["c_liabilities", "total_liabilities",
             "i_short_term_liabilities"])
        res["bs_short_debt"] = _kbs_lookup(df_bs,
            ["11_short_term_borrowings_and_financial_leases",
             "short_term_borrowings"])
        res["bs_long_debt"]  = _kbs_lookup(df_bs,
            ["9_long_term_borrowings_and_financial_leases",
             "long_term_borrowings"])

        # CF — đọc từ df_bs vì KBS trộn CF vào đây
        # FIX: dùng key thực tế từ log
        res["cf_operating"] = _kbs_lookup(df_bs,
            ["i_cash_flows_from_operating_activities",
             "operating_cash_flow",
             "net_cash_flows_from_operating_activities"])
        res["cf_investing"]  = _kbs_lookup(df_bs,
            ["investing_cash_flow",
             "ii_cash_flows_from_investing_activities",
             "net_cash_flows_from_investing_activities"])
        res["cf_financing"]  = _kbs_lookup(df_bs,
            ["financing_cash_flow",
             "iii_cash_flows_from_financing_activities",
             "net_cash_flows_from_financing_activities"])

        log.info(f"  BS: assets={res.get('bs_total_assets')}, "
                 f"equity={res.get('bs_equity')}, "
                 f"cf_op={res.get('cf_operating')}, "
                 f"cf_inv={res.get('cf_investing')}, "
                 f"cf_fin={res.get('cf_financing')}")

    # ── CF quality ratio ──
    # Cả 2 cùng đơn vị nghìn đồng → ratio đúng
    if res.get("cf_operating") and res.get("is_net_profit") \
       and res["is_net_profit"] != 0:
        res["cf_quality_ratio"] = round(
            res["cf_operating"] / res["is_net_profit"], 2)

    # cf_free = cf_operating + cf_investing (capex âm)
    if res.get("cf_operating") and res.get("cf_investing"):
        res["cf_free"] = round(
            res["cf_operating"] + res["cf_investing"], 2)

    return res

# =====================================================
# ENRICH METADATA
# =====================================================

def enrich_metadata(row: dict, industry_map: list) -> dict:
    sym     = row["symbol"]
    ind_row = next((r for r in industry_map if r.get("symbol") == sym), {})
    row["industry"] = ind_row.get("icb_name", "")
    row["icb_code"] = ind_row.get("icb_code", "")
    return row

# =====================================================
# BUILD DEEP ROW
# =====================================================

def build_deep_row(symbol: str, group: str,
                   market_open: bool, industry_map: list) -> dict:
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
    row = enrich_metadata(row, industry_map)

    log.info(
        f"  [{symbol}] "
        f"RSI={row.get('rsi')} "
        f"PE={row.get('r_pe')} "
        f"ROE={row.get('r_roe')}% "
        f"FF5d={fmt_money_bil(row.get('ff_net_val_5d'))}tỷ "
        f"CF_op={row.get('cf_operating')} "
        f"CF_q={row.get('cf_quality_ratio')} "
        f"RevG={row.get('is_rev_growth')} "
        f"ATR%={row.get('atr_pct')}"
    )
    return row

# =====================================================
# MAIN
# REMOVED: get_foreign_flow_for_symbols() — duplicate + VCI bug
# =====================================================

if __name__ == "__main__":
    trading = is_market_open()
    log.info(f"Time       : {now_ict():%Y-%m-%d %H:%M:%S} ICT")
    log.info(f"Market open: {trading}")

    load_exchange_map()

    industry_map = load_json("industry_map.json") or []
    ranking      = get_ranking()

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
            row = build_deep_row(symbol, group, trading, industry_map)
            all_deep_rows.append(row)

    # Export ranking
    if all_ranking_rows:
        df_rank_all = pd.concat(all_ranking_rows, ignore_index=True)
        save_json("ranking.json", df_rank_all.to_dict(orient="records"))
        save_csv("ranking.csv", clean_for_export(df_rank_all))

    # Export deep
    if all_deep_rows:
        df_deep = pd.DataFrame(all_deep_rows)
        save_json("deep_raw.json", df_deep.to_dict(orient="records"))

        df_export = df_deep.drop(columns=["_ohlcv_5d"], errors="ignore")
        df_clean  = clean_for_export(df_export)
        save_json("deep.json", df_clean.to_dict(orient="records"))
        save_csv("deep.csv",   df_clean)
        log.info(f"Deep: {len(df_deep)} rows, {len(df_deep.columns)} cols")

    log.info("=== STEP ALL DONE ===")
