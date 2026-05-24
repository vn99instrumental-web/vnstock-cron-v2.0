"""
step_snapshot.py — Intraday snapshot (replaces step_all.py)
============================================================
Thay thế step_all.py. Thay đổi chính:

1. Finance từ cache (0 API calls) thay vì 4 KBS calls/symbol
2. Concurrent per-symbol: ThreadPoolExecutor(10) → ~10-15s vs 220s sequential
3. Bỏ get_foreign_flow_for_symbols (duplicate + VCI bug)
4. CafeF trực tiếp cho foreign_trade (VCI luôn fail)
5. Lưu ohlcv_5d vào deep_raw → step_order_flow reuse, không fetch lại
6. Lazy finance fallback: nếu symbol không có trong cache → fetch ngay
"""
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
from concurrent.futures import ThreadPoolExecutor, as_completed

from vnstock_data import TopStock, Quote, Trading
from vnstock_ta import Indicator

from utils.helpers import (
    now_ict, is_market_open, last_trading_date,
    load_exchange_map, get_exchange,
    safe_run, safe_val, to_float,
    start_str, today_str
)
from utils.cache import save_json, load_json, save_csv
from utils.formatter import clean_for_export, fmt_money_bil

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(levelname)s %(message)s'
)
log = logging.getLogger(__name__)

MAX_WORKERS = 10  # concurrent symbol fetches

# =====================================================
# RANKING — TopStock(VND)
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
# SNAPSHOT — Quote(VCI)
# price + intraday buy/sell + depth
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
# TA INDICATORS + OHLCV — vnstock_ta
# Lưu ohlcv_5d để step_order_flow reuse (không fetch lại)
# =====================================================

def get_ta(symbol: str) -> dict:
    df = safe_run(f"ohlcv {symbol}",
         lambda: Quote(source="VCI", symbol=symbol).history(length="4M", interval="1D"))

    if df is None or df.empty or len(df) < 20:
        return {"symbol": symbol, "ta_error": "Không đủ data"}

    ta         = Indicator(data=df)
    res        = {"symbol": symbol}
    last_close = float(df["close"].iloc[-1])

    # Trend
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

    # Volume
    res["obv"] = safe_val(ta.volume.obv())
    res["cmf"] = safe_val(ta.volume.cmf(length=20))
    res["mfi"] = safe_val(ta.volume.mfi(length=14))

    # Store last 5D OHLCV for step_order_flow reuse (no extra API call needed)
    df["volume"] = pd.to_numeric(df["volume"], errors="coerce")
    df_5d = df.tail(5)
    ohlcv_5d = []
    avg_vol = float(df_5d["volume"].mean()) if not df_5d.empty else 0
    for _, row in df_5d.iterrows():
        vol = float(row["volume"]) if pd.notna(row["volume"]) else 0
        ohlcv_5d.append({
            "date"  : str(row["time"])[:10],
            "open"  : round(float(row["open"]),  2),
            "high"  : round(float(row["high"]),  2),
            "low"   : round(float(row["low"]),   2),
            "close" : round(float(row["close"]), 2),
            "volume": int(vol),
            "vs_avg5d_pct": round(vol / avg_vol * 100 - 100, 1)
                            if avg_vol > 0 else None,
        })
    res["_ohlcv_5d"] = ohlcv_5d  # private field, used by step_order_flow

    return res

# =====================================================
# FLOW — Trading (CafeF direct for foreign_trade)
# =====================================================

def _parse_cafef_ff(df: pd.DataFrame) -> pd.DataFrame | None:
    """
    Chuẩn hóa CafeF foreign_trade DataFrame.

    Vấn đề thực tế:
    - CafeF trả về toàn bộ lịch sử (23765 records), không filter theo start/end
    - Sort DESC → tail(5) = 5 rows cũ nhất ≈ 0
    - Column names thay đổi theo version thư viện

    Fix:
    - Lọc manual: chỉ giữ 25 ngày gần nhất
    - Sort ASC trước tail()
    - Normalize column names linh hoạt
    """
    if df is None or df.empty:
        return None

    # Sort + filter theo date
    date_col = next(
        (c for c in df.columns if c in ("date", "time", "trading_date", "trade_date")),
        None
    )
    if date_col:
        df[date_col] = pd.to_datetime(df[date_col], errors="coerce")
        cutoff        = pd.Timestamp.now() - pd.Timedelta(days=25)
        df            = df[df[date_col] >= cutoff].sort_values(date_col, ascending=True)

    # Normalize column names
    cols      = set(df.columns)
    rename    = {}
    for c in ("fr_buy_value", "fr_buy_volume", "buy_value", "buy_vol",
              "fr_buy_value_matched"):
        if c in cols: rename[c] = "ff_buy"; break
    for c in ("fr_sell_value", "fr_sell_volume", "sell_value", "sell_vol",
              "fr_sell_value_matched"):
        if c in cols: rename[c] = "ff_sell"; break
    for c in ("fr_net_value", "fr_net_volume", "net_value", "net_vol",
              "fr_net_value_total"):
        if c in cols: rename[c] = "ff_net"; break
    for c in ("fr_current_room", "current_room", "room"):
        if c in cols: rename[c] = "ff_room"; break

    if rename:
        df = df.rename(columns=rename)

    # Tính ff_net nếu chưa có
    if "ff_net" not in df.columns:
        if "ff_buy" in df.columns and "ff_sell" in df.columns:
            df["ff_net"] = (pd.to_numeric(df["ff_buy"],  errors="coerce").fillna(0)
                          - pd.to_numeric(df["ff_sell"], errors="coerce").fillna(0))

    if "ff_net" not in df.columns:
        log.warning(f"  CafeF FF: unknown cols {list(df.columns)[:8]}")
        return None

    for c in ("ff_buy", "ff_sell", "ff_net"):
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0)

    return df.reset_index(drop=True)


def get_flow(symbol: str) -> dict:
    res = {"symbol": symbol}

    df_raw = safe_run(f"foreign_trade {symbol}",
              lambda: Trading(symbol=symbol, source="CafeF").foreign_trade(
                  start=start_str(20), end=today_str()))

    df_ft = _parse_cafef_ff(df_raw)

    if df_ft is not None and not df_ft.empty:
        net  = df_ft["ff_net"]
        buy  = df_ft["ff_buy"]  if "ff_buy"  in df_ft.columns else pd.Series(dtype=float)
        sell = df_ft["ff_sell"] if "ff_sell" in df_ft.columns else pd.Series(dtype=float)

        res["ff_buy_val_5d"]  = float(buy.tail(5).sum())  if not buy.empty  else 0.0
        res["ff_sell_val_5d"] = float(sell.tail(5).sum()) if not sell.empty else 0.0
        res["ff_net_val_5d"]  = float(net.tail(5).sum())
        res["ff_net_val_20d"] = float(net.sum())

        if "ff_room" in df_ft.columns:
            res["ff_room"] = float(df_ft["ff_room"].iloc[-1])

        if len(net) >= 5:
            x     = np.arange(len(net))
            y     = net.fillna(0).values
            slope = np.polyfit(x, y, 1)[0]
            res["ff_trend"]       = round(float(slope) / 1e9, 2)
            res["ff_consistency"] = round((net > 0).sum() / len(net), 2)
            ff_5d_avg  = net.tail(5).mean()
            ff_20d_avg = net.mean()
            res["ff_acceleration"] = round(
                float(ff_5d_avg - ff_20d_avg) / 1e9, 2)                 if ff_20d_avg != 0 else 0.0

        log.info(f"  FF {symbol}: net5d={res.get('ff_net_val_5d'):.0f} "
                 f"net20d={res.get('ff_net_val_20d'):.0f} rows={len(net)}")

def enrich_finance(symbol: str, fin_cache: dict) -> dict:
    """
    Lấy finance data từ cache và flatten vào deep_raw format.
    Backward-compatible: dùng cùng field names như step_all.py cũ
    (r_pe, r_pb, r_roe, is_revenue, cf_operating, bs_total_assets...).
    """
    entry = fin_cache.get(symbol)

    # Lazy fallback nếu không có trong cache
    if not entry:
        log.info(f"  Finance cache miss: {symbol} — lazy fetch")
        try:
            from steps.step_finance_scan import fetch_one
            entry = fetch_one(symbol)
            if entry:
                fin_cache[symbol] = entry
                # Persist lazy fetch vào cache file
                try:
                    from steps.step_finance_scan import load_cache, save_cache
                    cache = load_cache()
                    cache[symbol] = entry
                    save_cache(cache)
                except Exception:
                    pass
        except Exception as e:
            log.warning(f"  Lazy finance fetch failed {symbol}: {e}")

    if not entry:
        return {}

    r = entry.get("ratio", {})
    i = entry.get("income", {})
    b = entry.get("balance", {})
    c = entry.get("cashflow", {})

    result = {
        # Ratio
        "r_period"    : entry.get("period", ""),
        "r_pe"        : r.get("pe"),
        "r_pb"        : r.get("pb"),
        "r_roe"       : r.get("roe"),
        "r_roa"       : r.get("roa"),
        "r_eps"       : r.get("eps"),
        "r_bvps"      : r.get("bvps"),
        "r_beta"      : r.get("beta"),
        "r_div_yield" : r.get("div_yield"),
        "r_gross_margin": r.get("gross_margin"),
        "r_net_margin": r.get("net_margin"),
        "r_quick_ratio": r.get("quick_ratio"),
        "r_interest_cov": r.get("interest_cov"),
        "r_ev_ebitda" : r.get("ev_ebitda"),
        # Income
        "is_revenue"          : i.get("revenue"),
        "is_gross_profit"     : i.get("gross_profit"),
        "is_net_profit"       : i.get("net_profit"),
        "is_operating_profit" : i.get("operating_profit"),
        "is_eps"              : i.get("eps"),
        "is_rev_growth"       : i.get("rev_growth_qoq"),
        "is_profit_growth"    : i.get("profit_growth_qoq"),
        "is_rev_growth_yoy"   : i.get("rev_growth_yoy"),
        "is_profit_growth_yoy": i.get("profit_growth_yoy"),
        # Balance
        "bs_total_assets": b.get("total_assets"),
        "bs_equity"      : b.get("equity"),
        "bs_total_liab"  : b.get("total_liab"),
        "bs_short_debt"  : b.get("short_debt"),
        "bs_long_debt"   : b.get("long_debt"),
        # Cash Flow
        "cf_operating"    : c.get("cf_operating"),
        "cf_investing"    : c.get("cf_investing"),
        "cf_financing"    : c.get("cf_financing"),
        "cf_free"         : c.get("cf_free"),
        "cf_quality_ratio": c.get("cf_quality"),
        # Precomputed finance score
        "finance_score"       : entry.get("finance_score", {}).get("total"),
        "finance_score_fund"  : entry.get("finance_score", {}).get("fundamental"),
        "finance_score_cf"    : entry.get("finance_score", {}).get("cashflow"),
        "finance_score_growth": entry.get("finance_score", {}).get("growth"),
    }
    return result

# =====================================================
# BUILD ONE SYMBOL — runs concurrently
# =====================================================

def build_one(symbol: str, group: str, market_open: bool,
              industry_map: list, fin_cache: dict) -> dict:
    try:
        snap    = get_snapshot(symbol, market_open)
        ta      = get_ta(symbol)
        flow    = get_flow(symbol)
        finance = enrich_finance(symbol, fin_cache)

        # Industry — robust lookup (column may be 'symbol' or 'ticker')
        ind_row  = next(
            (r for r in industry_map
             if r.get("symbol") == symbol or r.get("ticker") == symbol),
            {}
        )
        industry = ind_row.get("icb_name", "")
        icb_code = ind_row.get("icb_code", "")

        row = {
            "symbol"  : symbol,
            "group"   : group,
            "exchange": get_exchange(symbol),
            "time"    : now_ict().strftime("%Y-%m-%d %H:%M"),
            "date"    : today_str(),
            **{k: v for k, v in snap.items()    if k != "symbol"},
            **{k: v for k, v in ta.items()      if k != "symbol"},
            **{k: v for k, v in flow.items()    if k != "symbol"},
            **{k: v for k, v in finance.items() if k != "symbol"},
            "industry": industry,
            "icb_code": icb_code,
        }

        log.info(
            f"  ✅ {symbol} ({group}) "
            f"RSI={row.get('rsi')} "
            f"PE={row.get('r_pe')} "
            f"FF5d={fmt_money_bil(row.get('ff_net_val_5d'))}tỷ "
            f"CFO={fmt_money_bil(row.get('cf_operating'))}tỷ "
            f"RevG={row.get('is_rev_growth')} "
            f"ATR%={row.get('atr_pct')}"
        )
        return row

    except Exception as e:
        log.error(f"  ❌ {symbol}: {e}")
        import traceback; traceback.print_exc()
        return {
            "symbol"  : symbol,
            "group"   : group,
            "exchange": get_exchange(symbol),
            "time"    : now_ict().strftime("%Y-%m-%d %H:%M"),
            "date"    : today_str(),
            "error"   : str(e),
        }

# =====================================================
# MAIN
# =====================================================

if __name__ == "__main__":
    trading = is_market_open()
    log.info(f"Time       : {now_ict():%Y-%m-%d %H:%M:%S} ICT")
    log.info(f"Market open: {trading}")

    load_exchange_map()

    # Pre-load daily caches (0 API calls)
    industry_map = load_json("industry_map.json") or []
    fin_cache_raw = load_json("finance/cache.json") or {}
    # Unwrap nếu có "symbols" key
    fin_cache = fin_cache_raw.get("symbols", fin_cache_raw) \
                if isinstance(fin_cache_raw, dict) else {}
    log.info(f"Finance cache: {len(fin_cache)} symbols loaded")

    ranking = get_ranking()

    all_ranking_rows = []
    all_deep_rows    = []

    # Collect all (symbol, group) pairs
    symbol_jobs: list[tuple[str, str]] = []
    for group, df_rank in [
        ("GAINER", ranking["gainers"]),
        ("LOSER",  ranking["losers"]),
    ]:
        if df_rank is None or df_rank.empty:
            log.warning(f"No data: {group}")
            continue
        symbols = df_rank["symbol"].tolist()
        df_rank["exchange"] = df_rank["symbol"].map(get_exchange)
        df_rank["group"]    = group
        df_rank["date"]     = today_str()
        all_ranking_rows.append(df_rank)
        for sym in symbols:
            symbol_jobs.append((sym, group))

    log.info(f"\nFetching {len(symbol_jobs)} symbols concurrently "
             f"(workers={MAX_WORKERS})...")

    # Concurrent fetch — results come back out-of-order, sort after
    results: dict[str, dict] = {}
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        future_map = {
            executor.submit(
                build_one, sym, grp, trading, industry_map, fin_cache
            ): (sym, grp)
            for sym, grp in symbol_jobs
        }
        for future in as_completed(future_map):
            sym, grp = future_map[future]
            try:
                row = future.result()
                results[sym] = row
            except Exception as e:
                log.error(f"Future error {sym}: {e}")

    # Restore original order (gainers first, then losers, in ranking order)
    for sym, grp in symbol_jobs:
        if sym in results:
            all_deep_rows.append(results[sym])

    # Export Ranking
    if all_ranking_rows:
        df_rank_all = pd.concat(all_ranking_rows, ignore_index=True)
        save_json("ranking.json", df_rank_all.to_dict(orient="records"))
        save_csv("ranking.csv", clean_for_export(df_rank_all))

    # Export Deep
    if all_deep_rows:
        df_deep = pd.DataFrame(all_deep_rows)

        # deep_raw.json — raw numbers, includes _ohlcv_5d for order_flow
        save_json("deep_raw.json", df_deep.to_dict(orient="records"))

        # deep.json / deep.csv — formatted, strip internal fields
        df_export = df_deep.drop(columns=["_ohlcv_5d"], errors="ignore")
        df_clean  = clean_for_export(df_export)
        save_json("deep.json", df_clean.to_dict(orient="records"))
        save_csv("deep.csv",   df_clean)

        log.info(
            f"Deep: {len(df_deep)} rows, {len(df_deep.columns)} cols "
            f"(+_ohlcv_5d for order_flow)"
        )

    log.info("=== SNAPSHOT DONE ===")
