"""
step_order_flow.py — Volume profile + pattern analysis
=======================================================
Thay đổi từ bản cũ:

1. Reuse _ohlcv_5d từ deep_raw.json (step_snapshot đã fetch)
   → Bỏ Quote.history(5D) call (20 calls saved)
2. Concurrent: ThreadPoolExecutor(10) cho intraday(10000)
   → 20 calls parallel ~10s vs 52s sequential
3. Enrich order_flow summary ngược vào deep_raw
   → step_scoring có thể dùng order_flow pattern nếu cần
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

from vnstock_data import Quote

from utils.helpers import (
    now_ict, is_market_open,
    load_exchange_map, get_exchange,
    safe_run, today_str
)
from utils.cache import load_json, save_json

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(levelname)s %(message)s'
)
log = logging.getLogger(__name__)

MAX_WORKERS = 10

# =====================================================
# VOLUME PROFILE từ intraday
# =====================================================

def build_volume_profile(df: pd.DataFrame) -> list:
    if df is None or df.empty:
        return []

    df = df.copy()
    df["price"]  = pd.to_numeric(df["price"],  errors="coerce")
    df["volume"] = pd.to_numeric(df["volume"], errors="coerce")
    df = df.dropna(subset=["price", "volume"])

    buy_mask  = df["match_type"].str.contains("Buy",  case=False, na=False)
    sell_mask = df["match_type"].str.contains("Sell", case=False, na=False)
    df["is_buy"]  = buy_mask
    df["is_sell"] = sell_mask

    grouped = df.groupby("price").agg(
        trade_count = ("volume", "count"),
        volume      = ("volume", "sum"),
        buy_count   = ("is_buy",  "sum"),
        sell_count  = ("is_sell", "sum"),
        buy_volume  = ("volume", lambda x: x[df.loc[x.index, "is_buy"]].sum()),
        sell_volume = ("volume", lambda x: x[df.loc[x.index, "is_sell"]].sum()),
    ).reset_index()

    total_count  = grouped["trade_count"].sum()
    total_volume = grouped["volume"].sum()
    grouped["count_pct"]  = (grouped["trade_count"] / total_count * 100).round(1)
    grouped["volume_pct"] = (grouped["volume"] / total_volume * 100).round(1)
    grouped["buy_ratio"]  = (grouped["buy_count"] / grouped["trade_count"]).round(2)

    return grouped.sort_values("price", ascending=False).to_dict(orient="records")

# =====================================================
# SUMMARY từ volume profile + ohlcv_5d
# =====================================================

def build_summary(symbol: str, df_intra: pd.DataFrame,
                  ohlcv_5d: list, vol_profile: list, group: str) -> dict:
    summary = {"symbol": symbol, "group": group}

    if not vol_profile:
        summary["error"] = "Không đủ data"
        return summary

    df_vp = pd.DataFrame(vol_profile)

    # POC
    poc_count_idx = df_vp["trade_count"].idxmax()
    poc_vol_idx   = df_vp["volume"].idxmax()
    poc_by_count  = float(df_vp.loc[poc_count_idx, "price"])
    poc_by_volume = float(df_vp.loc[poc_vol_idx,   "price"])

    summary["poc_by_count"]  = poc_by_count
    summary["poc_by_volume"] = poc_by_volume
    summary["poc_diverge"]   = abs(poc_by_count - poc_by_volume) > \
                               poc_by_volume * 0.005

    # Value Area 70%
    total_count = df_vp["trade_count"].sum()
    df_sorted   = df_vp.sort_values("trade_count", ascending=False)
    cumsum      = 0
    va_prices   = []
    for _, row in df_sorted.iterrows():
        cumsum += row["trade_count"]
        va_prices.append(row["price"])
        if cumsum / total_count >= 0.70:
            break
    summary["value_area_high"] = round(max(va_prices), 2)
    summary["value_area_low"]  = round(min(va_prices), 2)
    summary["value_area_pct"]  = round(cumsum / total_count * 100, 1)

    # Totals
    summary["total_trades"]   = int(df_vp["trade_count"].sum())
    summary["total_volume"]   = int(df_vp["volume"].sum())
    summary["avg_trade_size"] = round(
        summary["total_volume"] / summary["total_trades"], 0) \
        if summary["total_trades"] > 0 else None

    ats = summary["avg_trade_size"]
    if ats:
        if ats < 1000:     summary["trader_type"] = "Retail"
        elif ats < 10000:  summary["trader_type"] = "Mixed"
        else:              summary["trader_type"] = "Institutional"

    # Buy/sell ratio hôm nay
    if df_intra is not None and not df_intra.empty:
        df_intra["volume"] = pd.to_numeric(df_intra["volume"], errors="coerce")
        buy_mask  = df_intra["match_type"].str.contains("Buy",  case=False, na=False)
        sell_mask = df_intra["match_type"].str.contains("Sell", case=False, na=False)
        buy_vol   = float(df_intra.loc[buy_mask,  "volume"].sum())
        sell_vol  = float(df_intra.loc[sell_mask, "volume"].sum())
        total     = buy_vol + sell_vol
        summary["buy_ratio_today"]  = round(buy_vol / total, 2) if total > 0 else None
        summary["sell_ratio_today"] = round(sell_vol / total, 2) if total > 0 else None

    # Current price vs POC — từ ohlcv_5d đã có
    if ohlcv_5d:
        current_price = ohlcv_5d[-1]["close"]
        summary["current_price"] = current_price
        summary["price_vs_poc_pct"] = round(
            (current_price - poc_by_count) / poc_by_count * 100, 2) \
            if poc_by_count != 0 else None

    # Volume spike vs 5D avg — từ ohlcv_5d đã có
    if ohlcv_5d and len(ohlcv_5d) >= 2:
        vols    = [d["volume"] for d in ohlcv_5d if d.get("volume")]
        avg_vol = sum(vols[:-1]) / len(vols[:-1]) if len(vols) > 1 else 0
        vol_today = vols[-1] if vols else 0
        summary["vol_5d_avg"]    = round(avg_vol, 0)
        summary["vol_today"]     = round(vol_today, 0)
        summary["vol_spike_pct"] = round(
            vol_today / avg_vol * 100 - 100, 1) if avg_vol > 0 else None

    summary["distribution_type"] = classify_distribution(df_vp)
    summary["pattern"]           = classify_pattern(summary)
    return summary

# =====================================================
# CLASSIFY DISTRIBUTION & PATTERN (unchanged)
# =====================================================

def classify_distribution(df_vp: pd.DataFrame) -> str:
    if df_vp.empty or len(df_vp) < 3:
        return "INSUFFICIENT_DATA"

    counts      = df_vp.sort_values("price")["trade_count"].values
    total       = counts.sum()
    n           = len(counts)
    pcts        = counts / total
    pcts        = pcts[pcts > 0]
    entropy     = -np.sum(pcts * np.log(pcts))
    max_entropy = np.log(n)
    norm_entropy = entropy / max_entropy if max_entropy > 0 else 0

    peaks = 0
    for i in range(1, n - 1):
        if counts[i] > counts[i-1] and counts[i] > counts[i+1]:
            peaks += 1

    if norm_entropy < 0.7 and peaks == 1:
        return "NORMAL"
    elif peaks >= 2:
        return "BIMODAL"
    elif norm_entropy > 0.9:
        return "FLAT"
    else:
        mid       = n // 2
        upper_sum = counts[mid:].sum()
        lower_sum = counts[:mid].sum()
        if upper_sum > lower_sum * 1.3:   return "SKEWED_UP"
        elif lower_sum > upper_sum * 1.3: return "SKEWED_DOWN"
        else:                             return "NORMAL"

def classify_pattern(summary: dict) -> str:
    dist      = summary.get("distribution_type", "")
    buy_ratio = summary.get("buy_ratio_today")
    vol_spike = summary.get("vol_spike_pct")
    poc_div   = summary.get("poc_diverge", False)

    if poc_div and summary.get("trader_type") == "Institutional":
        return "INSTITUTIONAL_ACTIVITY"
    if vol_spike is not None and vol_spike < -20:
        return "WEAK"
    if vol_spike is not None and vol_spike > 100:
        if buy_ratio and buy_ratio > 0.65:   return "SPIKE_BUY"
        elif buy_ratio and buy_ratio < 0.35: return "SPIKE_SELL"
        else:                                return "SPIKE_NEUTRAL"
    if dist in ["NORMAL", "SKEWED_UP"]:
        if buy_ratio and buy_ratio > 0.60:   return "ACCUMULATION"
        elif buy_ratio and buy_ratio < 0.40: return "DISTRIBUTION"
    if dist == "BIMODAL": return "CONTENTION"
    if dist == "FLAT":    return "NORMAL"
    return "NORMAL"

# =====================================================
# FETCH ONE SYMBOL — runs concurrently
# =====================================================

def fetch_one(deep_row: dict, market_open: bool) -> dict:
    """
    deep_row: record từ deep_raw.json (đã có _ohlcv_5d).
    Chỉ fetch Quote.intraday(10000) — không cần history lại.
    """
    symbol   = deep_row["symbol"]
    group    = deep_row.get("group", "")
    ohlcv_5d = deep_row.get("_ohlcv_5d") or []

    df_intra = None
    if market_open:
        df_intra = safe_run(f"intraday {symbol}",
                   lambda: Quote(source="VCI", symbol=symbol).intraday(page_size=10000))
    else:
        df_intra = safe_run(f"intraday_eod {symbol}",
                   lambda: Quote(source="VCI", symbol=symbol).intraday(page_size=10000))

    vol_profile = build_volume_profile(df_intra)
    summary     = build_summary(symbol, df_intra, ohlcv_5d, vol_profile, group)

    log.info(
        f"  [{symbol}] "
        f"pattern={summary.get('pattern')}, "
        f"dist={summary.get('distribution_type')}, "
        f"poc={summary.get('poc_by_count')}, "
        f"buy_ratio={summary.get('buy_ratio_today')}, "
        f"vol_spike={summary.get('vol_spike_pct')}%"
    )

    return {
        "symbol"        : symbol,
        "group"         : group,
        "exchange"      : deep_row.get("exchange", get_exchange(symbol)),
        "time"          : now_ict().strftime("%Y-%m-%d %H:%M"),
        "date"          : today_str(),
        "history_5d"    : ohlcv_5d,
        "volume_profile": vol_profile,
        "summary"       : summary,
    }

# =====================================================
# MAIN
# =====================================================

if __name__ == "__main__":
    trading = is_market_open()
    log.info(f"Time       : {now_ict():%Y-%m-%d %H:%M:%S} ICT")
    log.info(f"Market open: {trading}")

    load_exchange_map()

    deep_raw = load_json("deep_raw.json")
    if not deep_raw:
        log.error("deep_raw.json not found — chạy step_snapshot.py trước")
        import sys; sys.exit(1)

    log.info(f"Processing {len(deep_raw)} symbols concurrently (workers={MAX_WORKERS})...")

    results_map: dict[str, dict] = {}

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        future_map = {
            executor.submit(fetch_one, row, trading): row["symbol"]
            for row in deep_raw
        }
        for future in as_completed(future_map):
            sym = future_map[future]
            try:
                results_map[sym] = future.result()
            except Exception as e:
                log.error(f"  ❌ {sym}: {e}")

    # Restore original order
    results = [results_map[r["symbol"]] for r in deep_raw if r["symbol"] in results_map]

    save_json("order_flow.json", results)
    log.info(f"Saved order_flow.json — {len(results)} symbols")
    log.info("=== ORDER FLOW DONE ===")
