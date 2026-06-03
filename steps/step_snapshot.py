"""
step_snapshot.py — Intraday snapshot (replaces step_all.py)
============================================================
CHANGELOG:
  2026-05-25 — FF identical validation gate (Bug #3)
  2026-05-27 — Phase 1+2 indicator additions:
    - History fetch length 4M → 12M (cần ≥200 ngày cho EMA200)
    - get_ta(): add ema200, vol_ma_ratio (today/avg20d)
    - enrich_finance(): expose debt_to_equity field
  2026-06-02 — FIX bb_position (Bug #11):
    pandas_ta.bbands() trả cột [BBL, BBM, BBU, BBB, BBP] — Lower ở index 0,
    Upper ở index 2. Code cũ dùng safe_val(bb,0)→bb_upper khiến upper/lower
    bị TRÁO → bb_position đảo dấu, ra ngoài [0,1] (thấy: -0.25, 1.15).
    Fix: lấy cột theo TÊN (BBL/BBM/BBU) + dùng BBP (%B) pandas_ta tính sẵn,
    clamp về [0,1]. Volatility_score trước đây dùng sai → giờ mới đáng tin.
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

MAX_WORKERS = 10

# History length: need ≥200 days for EMA200 — was "4M" (~80d), now "12M" (~250d)
HISTORY_LENGTH = "12M"

# FF fields wiped together when validation detects bug
FF_FIELDS = [
    "ff_buy_val_5d", "ff_sell_val_5d",
    "ff_net_val_5d", "ff_net_val_20d",
    "ff_room",
    "ff_trend", "ff_consistency", "ff_acceleration",
]

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
# SNAPSHOT — Quote(VCI)
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
# TA INDICATORS + OHLCV
# =====================================================

def get_ta(symbol: str) -> dict:
    # Phase 2: 12M history để có ≥200 ngày cho EMA200
    df = safe_run(f"ohlcv {symbol}",
         lambda: Quote(source="VCI", symbol=symbol).history(
             length=HISTORY_LENGTH, interval="1D"))

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

    # Phase 2 NEW: EMA200 (major long-term support/resistance level)
    if len(df) >= 200:
        ema200 = ta.trend.ema(length=200)
        res["ema200"] = safe_val(ema200)
    else:
        res["ema200"] = None

    if res["ema20"] and res["ema50"] and res["ema50"] != 0:
        res["ema_cross_pct"] = round(
            (res["ema20"] - res["ema50"]) / res["ema50"] * 100, 2)
    if res.get("ema20") and res["ema20"] != 0:
        res["price_vs_ema20_pct"] = round(
            (last_close - res["ema20"]) / res["ema20"] * 100, 2)
    if res.get("ema200") and res["ema200"] != 0:
        res["price_vs_ema200_pct"] = round(
            (last_close - res["ema200"]) / res["ema200"] * 100, 2)

    # Momentum
    res["rsi"]       = safe_val(ta.momentum.rsi(length=14))
    macd = ta.momentum.macd(fast=12, slow=26, signal=9)
    res["macd"]      = safe_val(macd, 0)
    res["macd_sig"]  = safe_val(macd, 1)
    res["macd_hist"] = safe_val(macd, 2)
    stoch = ta.momentum.stoch(k=14, d=3, smooth_k=3)
    res["stoch_k"]   = safe_val(stoch, 0)
    res["stoch_d"]   = safe_val(stoch, 1)

    # ── Volatility — FIX 2026-06: lấy theo TÊN cột (Bug #11) ──────────
    # pandas_ta.bbands() trả [BBL_20_2.0, BBM_20_2.0, BBU_20_2.0,
    #                         BBB_20_2.0, BBP_20_2.0]
    # Trước đây dùng safe_val(bb,0/1/2) → upper/lower bị tráo.
    bb = ta.volatility.bbands(length=20, std=2.0)

    def _bb_col(prefix):
        """Lấy cột bbands theo prefix tên, trả giá trị cuối (đúng thứ tự)."""
        if bb is None or not hasattr(bb, "columns"):
            return None
        cols = [c for c in bb.columns if c.startswith(prefix)]
        if not cols:
            return None
        val = bb[cols[0]].iloc[-1]
        return round(float(val), 2) if pd.notna(val) else None

    res["bb_lower"] = _bb_col("BBL")   # Lower band
    res["bb_mid"]   = _bb_col("BBM")   # Mid (SMA20)
    res["bb_upper"] = _bb_col("BBU")   # Upper band
    res["atr"]      = safe_val(ta.volatility.atr(length=14))

    # bb_position: ưu tiên BBP (%B) pandas_ta tính sẵn — chuẩn hóa, clamp [0,1].
    # Fallback tự tính nếu không có cột BBP.
    bbp = _bb_col("BBP")
    if bbp is not None:
        res["bb_position"] = round(max(0.0, min(1.0, bbp)), 2)
    elif res["bb_upper"] and res["bb_lower"] and \
         (res["bb_upper"] - res["bb_lower"]) != 0:
        raw = (last_close - res["bb_lower"]) / (res["bb_upper"] - res["bb_lower"])
        res["bb_position"] = round(max(0.0, min(1.0, raw)), 2)

    if res.get("atr") and last_close:
        res["atr_pct"] = round(res["atr"] / last_close * 100, 2)

    # Volume
    res["obv"] = safe_val(ta.volume.obv())
    res["cmf"] = safe_val(ta.volume.cmf(length=20))
    res["mfi"] = safe_val(ta.volume.mfi(length=14))

    # Phase 2 NEW: Volume MA ratio (today vs 20-day avg)
    df["volume"] = pd.to_numeric(df["volume"], errors="coerce")
    if len(df) >= 21:
        vol_today  = float(df["volume"].iloc[-1])
        vol_avg_20 = float(df["volume"].iloc[-21:-1].mean())
        if vol_avg_20 > 0:
            res["vol_ma_ratio"] = round(vol_today / vol_avg_20, 2)
            res["vol_today"]    = vol_today
            res["vol_avg_20d"]  = round(vol_avg_20, 0)

    # Store last 5D OHLCV for step_order_flow reuse
    df_5d = df.tail(5)
    ohlcv_5d = []
    avg_vol_5d = float(df_5d["volume"].mean()) if not df_5d.empty else 0
    for _, row in df_5d.iterrows():
        vol = float(row["volume"]) if pd.notna(row["volume"]) else 0
        ohlcv_5d.append({
            "date"  : str(row["time"])[:10],
            "open"  : round(float(row["open"]),  2),
            "high"  : round(float(row["high"]),  2),
            "low"   : round(float(row["low"]),   2),
            "close" : round(float(row["close"]), 2),
            "volume": int(vol),
            "vs_avg5d_pct": round(vol / avg_vol_5d * 100 - 100, 1)
                            if avg_vol_5d > 0 else None,
        })
    res["_ohlcv_5d"] = ohlcv_5d

    return res

# =====================================================
# FLOW — CafeF foreign_trade (VCI broken)
# =====================================================

def get_flow(symbol: str) -> dict:
    res = {"symbol": symbol}

    # Foreign trade — CafeF (filter 25d gần nhất, sort ASC)
    df_ft = safe_run(f"foreign_trade {symbol}",
             lambda: Trading(symbol=symbol, source="CafeF").foreign_trade(
                 start=start_str(25), end=today_str()))

    if df_ft is not None and not df_ft.empty:
        # Normalize column names (CafeF variant)
        rename = {
            "fr_buy_value_matched" : "buy_val",
            "fr_sell_value_matched": "sell_val",
            "fr_net_value_total"   : "net_val",
        }
        for old, new in rename.items():
            if old in df_ft.columns:
                df_ft = df_ft.rename(columns={old: new})

        buy  = pd.to_numeric(df_ft.get("buy_val"),  errors="coerce").dropna() \
               if "buy_val"  in df_ft.columns else pd.Series(dtype=float)
        sell = pd.to_numeric(df_ft.get("sell_val"), errors="coerce").dropna() \
               if "sell_val" in df_ft.columns else pd.Series(dtype=float)
        net  = pd.to_numeric(df_ft.get("net_val"),  errors="coerce").dropna() \
               if "net_val"  in df_ft.columns else pd.Series(dtype=float)

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
                float(ff_5d_avg - ff_20d_avg) / 1e9, 2) \
                if ff_20d_avg != 0 else 0.0

        log.info(f"  FF {symbol}: net5d={res.get('ff_net_val_5d'):.0f} "
                 f"net20d={res.get('ff_net_val_20d'):.0f} rows={len(net)}")

    # Insider deal — VCI → CafeF fallback
    df_id = safe_run(f"insider_deal_vci {symbol}",
             lambda: Trading(symbol=symbol, source="VCI").insider_deal(limit=5))
    if df_id is None:
        df_id = safe_run(f"insider_deal_cafef {symbol}",
                 lambda: Trading(symbol=symbol, source="CafeF").insider_deal(limit=5))
        if df_id is not None and not df_id.empty:
            df_id = df_id.rename(columns={
                "transaction_man"         : "trader_name",
                "transaction_man_position": "trader_position",
                "transaction_note"        : "action_type",
            })

    if df_id is not None and not df_id.empty:
        res["insider_count"]  = len(df_id)
        res["insider_latest"] = str(df_id["action_type"].iloc[0]) \
                                if "action_type" in df_id.columns else None
        res["insider_name"]   = str(df_id["trader_name"].iloc[0]) \
                                if "trader_name" in df_id.columns else None

    return res

# =====================================================
# ENRICH FINANCE — từ finance cache (KBS)
# =====================================================

def enrich_finance(symbol: str, fin_cache: dict) -> dict:
    """
    Phase 1.5: expose debt_to_equity for scoring.
    Lazy fetch nếu cache miss.
    """
    entry = fin_cache.get(symbol)

    if not entry:
        log.info(f"  Finance cache miss: {symbol} — lazy fetch")
        try:
            from steps.step_finance_scan import fetch_one
            entry = fetch_one(symbol)
            if entry:
                fin_cache[symbol] = entry
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
        "is_revenue"          : i.get("revenue"),
        "is_gross_profit"     : i.get("gross_profit"),
        "is_net_profit"       : i.get("net_profit"),
        "is_operating_profit" : i.get("operating_profit"),
        "is_eps"              : i.get("eps"),
        "is_rev_growth"       : i.get("rev_growth_qoq"),
        "is_profit_growth"    : i.get("profit_growth_qoq"),
        "is_rev_growth_yoy"   : i.get("rev_growth_yoy"),
        "is_profit_growth_yoy": i.get("profit_growth_yoy"),
        "bs_total_assets": b.get("total_assets"),
        "bs_equity"      : b.get("equity"),
        "bs_total_liab"  : b.get("total_liab"),
        "bs_short_debt"  : b.get("short_debt"),
        "bs_long_debt"   : b.get("long_debt"),
        "bs_debt_to_equity": b.get("debt_to_equity"),   # ← Phase 1.5 NEW
        "cf_operating"    : c.get("cf_operating"),
        "cf_investing"    : c.get("cf_investing"),
        "cf_financing"    : c.get("cf_financing"),
        "cf_free"         : c.get("cf_free"),
        "cf_quality_ratio": c.get("cf_quality"),
        "finance_score"       : entry.get("finance_score", {}).get("total"),
        "finance_score_fund"  : entry.get("finance_score", {}).get("fundamental"),
        "finance_score_cf"    : entry.get("finance_score", {}).get("cashflow"),
        "finance_score_growth": entry.get("finance_score", {}).get("growth"),
    }
    return result

# =====================================================
# BUILD ONE SYMBOL
# =====================================================

def build_one(symbol: str, group: str, market_open: bool,
              industry_map: list, fin_cache: dict) -> dict:
    try:
        snap    = get_snapshot(symbol, market_open)
        ta      = get_ta(symbol)
        flow    = get_flow(symbol)
        finance = enrich_finance(symbol, fin_cache)

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
            f"VolRatio={row.get('vol_ma_ratio')} "
            f"D/E={row.get('bs_debt_to_equity')}"
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
# FF identical validation gate
# =====================================================

def validate_ff_data(deep_rows: list[dict]) -> list[dict]:
    if not deep_rows:
        return deep_rows

    nets_5d  = [r.get("ff_net_val_5d")  for r in deep_rows
                if r.get("ff_net_val_5d")  is not None]
    nets_20d = [r.get("ff_net_val_20d") for r in deep_rows
                if r.get("ff_net_val_20d") is not None]

    suspicious = False
    reason     = ""

    if len(nets_5d) >= 3 and len(set(nets_5d)) == 1:
        suspicious = True
        reason     = (
            f"identical ff_net_val_5d={nets_5d[0]:.0f} "
            f"across {len(nets_5d)} symbols"
        )
    elif len(nets_20d) >= 3 and len(set(nets_20d)) == 1:
        suspicious = True
        reason     = (
            f"identical ff_net_val_20d={nets_20d[0]:.0f} "
            f"across {len(nets_20d)} symbols"
        )

    if not suspicious:
        unique_5d = len(set(nets_5d))
        log.info(
            f"  ✅ FF data quality OK: "
            f"{len(nets_5d)} symbols with data, "
            f"{unique_5d} unique net_5d values"
        )
        return deep_rows

    log.error(f"🚨 FF DATA BUG DETECTED: {reason}")
    log.error(f"   Wiping FF fields for all {len(deep_rows)} symbols.")

    affected = 0
    for r in deep_rows:
        had_data = any(r.get(k) is not None for k in FF_FIELDS)
        for k in FF_FIELDS:
            r[k] = None
        r["ff_data_invalid"] = True
        if had_data:
            affected += 1

    log.error(f"   {affected}/{len(deep_rows)} symbols had FF data wiped.")
    return deep_rows


# =====================================================
# MAIN
# =====================================================

if __name__ == "__main__":
    trading = is_market_open()
    log.info(f"Time       : {now_ict():%Y-%m-%d %H:%M:%S} ICT")
    log.info(f"Market open: {trading}")
    log.info(f"History    : {HISTORY_LENGTH} (for EMA200)")

    load_exchange_map()

    industry_map = load_json("industry_map.json") or []
    fin_cache_raw = load_json("finance/cache.json") or {}
    fin_cache = fin_cache_raw.get("symbols", fin_cache_raw) \
                if isinstance(fin_cache_raw, dict) else {}
    log.info(f"Finance cache: {len(fin_cache)} symbols loaded")

    ranking = get_ranking()

    all_ranking_rows = []
    all_deep_rows    = []

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

    for sym, grp in symbol_jobs:
        if sym in results:
            all_deep_rows.append(results[sym])

    log.info("\n=== DATA QUALITY: FF validation ===")
    all_deep_rows = validate_ff_data(all_deep_rows)

    if all_ranking_rows:
        df_rank_all = pd.concat(all_ranking_rows, ignore_index=True)
        save_json("ranking.json", df_rank_all.to_dict(orient="records"))
        save_csv("ranking.csv", clean_for_export(df_rank_all))

    if all_deep_rows:
        df_deep = pd.DataFrame(all_deep_rows)
        save_json("deep_raw.json", df_deep.to_dict(orient="records"))
        df_export = df_deep.drop(columns=["_ohlcv_5d"], errors="ignore")
        df_clean  = clean_for_export(df_export)
        save_json("deep.json", df_clean.to_dict(orient="records"))
        save_csv("deep.csv",   df_clean)

        log.info(
            f"Deep: {len(df_deep)} rows, {len(df_deep.columns)} cols"
        )

    log.info("=== SNAPSHOT DONE ===")
