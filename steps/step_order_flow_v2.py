"""
step_order_flow_v2.py — Volume profile + pattern cho V2 pipeline (fully standalone)
====================================================================================
Copy đầy đủ của step_order_flow.py. KHÔNG import từ step_order_flow.
Thay đổi duy nhất so với step_order_flow.py: input/output filenames có suffix _v2.

Sync từ step_order_flow.py:
  2026-05-25 — FIX BUG TPC 'float' object is not subscriptable
  2026-06-11 — v2 fork: input deep_raw_v2.json / output order_flow_v2.json
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
import traceback
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

    if df.empty:
        return []

    buy_mask  = df["match_type"].str.contains("Buy",  case=False, na=False)
    sell_mask = df["match_type"].str.contains("Sell", case=False, na=False)
    df["is_buy"]  = buy_mask
    df["is_sell"] = sell_mask

    try:
        grouped = df.groupby("price").agg(
            trade_count = ("volume", "count"),
            volume      = ("volume", "sum"),
            buy_count   = ("is_buy",  "sum"),
            sell_count  = ("is_sell", "sum"),
            buy_volume  = ("volume", lambda x: x[df.loc[x.index, "is_buy"]].sum()),
            sell_volume = ("volume", lambda x: x[df.loc[x.index, "is_sell"]].sum()),
        ).reset_index()
    except Exception as e:
        log.warning(f"  build_volume_profile groupby error: {e}")
        return []

    total_count  = grouped["trade_count"].sum()
    total_volume = grouped["volume"].sum()

    if total_count == 0:
        return []

    grouped["count_pct"]  = (grouped["trade_count"] / total_count * 100).round(1)
    grouped["volume_pct"] = (grouped["volume"] / total_volume * 100).round(1) \
                            if total_volume > 0 else 0
    grouped["buy_ratio"]  = (grouped["buy_count"] / grouped["trade_count"]).round(2)

    return grouped.sort_values("price", ascending=False).to_dict(orient="records")

# =====================================================
# SUMMARY từ volume profile + ohlcv_5d
# =====================================================

def _safe_get_last_dict(seq):
    if not isinstance(seq, list) or len(seq) == 0:
        return None
    last = seq[-1]
    return last if isinstance(last, dict) else None


def _safe_iter_dicts(seq):
    if not isinstance(seq, list):
        return
    for item in seq:
        if isinstance(item, dict):
            yield item


def build_summary(symbol: str, df_intra: pd.DataFrame,
                  ohlcv_5d: list, vol_profile: list, group: str) -> dict:
    summary = {"symbol": symbol, "group": group}

    if not vol_profile:
        summary["error"] = "Không đủ data"
        return summary

    df_vp = pd.DataFrame(vol_profile)

    try:
        poc_count_idx = df_vp["trade_count"].idxmax()
        poc_vol_idx   = df_vp["volume"].idxmax()
        poc_by_count_raw  = df_vp.loc[poc_count_idx, "price"]
        poc_by_volume_raw = df_vp.loc[poc_vol_idx,   "price"]

        if isinstance(poc_by_count_raw, pd.Series):
            poc_by_count_raw = poc_by_count_raw.iloc[0]
        if isinstance(poc_by_volume_raw, pd.Series):
            poc_by_volume_raw = poc_by_volume_raw.iloc[0]

        poc_by_count  = float(poc_by_count_raw)
        poc_by_volume = float(poc_by_volume_raw)
    except Exception as e:
        log.warning(f"  [{symbol}] POC calc failed: {e}")
        summary["error"] = f"POC calc failed: {e}"
        return summary

    summary["poc_by_count"]  = poc_by_count
    summary["poc_by_volume"] = poc_by_volume
    summary["poc_diverge"]   = abs(poc_by_count - poc_by_volume) > \
                               poc_by_volume * 0.005

    try:
        total_count = df_vp["trade_count"].sum()
        df_sorted   = df_vp.sort_values("trade_count", ascending=False)
        cumsum      = 0
        va_prices   = []
        for _, row in df_sorted.iterrows():
            cumsum += row["trade_count"]
            va_prices.append(row["price"])
            if total_count > 0 and cumsum / total_count >= 0.70:
                break
        if va_prices:
            summary["value_area_high"] = round(max(va_prices), 2)
            summary["value_area_low"]  = round(min(va_prices), 2)
            summary["value_area_pct"]  = round(cumsum / total_count * 100, 1) \
                                         if total_count > 0 else None
    except Exception as e:
        log.warning(f"  [{symbol}] Value Area calc failed: {e}")

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

    if df_intra is not None and not df_intra.empty:
        try:
            df_intra["volume"] = pd.to_numeric(df_intra["volume"], errors="coerce")
            buy_mask  = df_intra["match_type"].str.contains("Buy",  case=False, na=False)
            sell_mask = df_intra["match_type"].str.contains("Sell", case=False, na=False)
            buy_vol   = float(df_intra.loc[buy_mask,  "volume"].sum())
            sell_vol  = float(df_intra.loc[sell_mask, "volume"].sum())
            total     = buy_vol + sell_vol
            summary["buy_ratio_today"]  = round(buy_vol / total, 2) if total > 0 else None
            summary["sell_ratio_today"] = round(sell_vol / total, 2) if total > 0 else None
        except Exception as e:
            log.warning(f"  [{symbol}] Buy/sell ratio calc failed: {e}")

    last_entry = _safe_get_last_dict(ohlcv_5d)
    if last_entry is not None:
        current_price = last_entry.get("close")
        if current_price is not None:
            try:
                summary["current_price"] = float(current_price)
                summary["price_vs_poc_pct"] = round(
                    (float(current_price) - poc_by_count) / poc_by_count * 100, 2) \
                    if poc_by_count != 0 else None
            except (TypeError, ValueError) as e:
                log.warning(f"  [{symbol}] current_price conversion failed: {e}")

    vols = []
    for d in _safe_iter_dicts(ohlcv_5d):
        v = d.get("volume")
        if v:
            try:
                vols.append(float(v))
            except (TypeError, ValueError):
                continue

    if len(vols) >= 2:
        avg_vol   = sum(vols[:-1]) / len(vols[:-1])
        vol_today = vols[-1]
        summary["vol_5d_avg"]    = round(avg_vol, 0)
        summary["vol_today"]     = round(vol_today, 0)
        summary["vol_spike_pct"] = round(
            vol_today / avg_vol * 100 - 100, 1) if avg_vol > 0 else None

    try:
        summary["distribution_type"] = classify_distribution(df_vp)
    except Exception as e:
        log.warning(f"  [{symbol}] classify_distribution failed: {e}")
        summary["distribution_type"] = "ERROR"

    try:
        summary["pattern"] = classify_pattern(summary)
    except Exception as e:
        log.warning(f"  [{symbol}] classify_pattern failed: {e}")
        summary["pattern"] = "ERROR"

    return summary

# =====================================================
# CLASSIFY DISTRIBUTION & PATTERN
# =====================================================

def classify_distribution(df_vp: pd.DataFrame) -> str:
    if df_vp.empty or len(df_vp) < 3:
        return "INSUFFICIENT_DATA"

    counts       = df_vp.sort_values("price")["trade_count"].values
    total        = counts.sum()
    if total == 0:
        return "INSUFFICIENT_DATA"
    n            = len(counts)
    pcts         = counts / total
    pcts         = pcts[pcts > 0]
    if len(pcts) == 0:
        return "INSUFFICIENT_DATA"
    entropy      = -np.sum(pcts * np.log(pcts))
    max_entropy  = np.log(n) if n > 0 else 0
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
# FETCH ONE SYMBOL
# =====================================================

def _error_result(deep_row: dict, error_msg: str) -> dict:
    symbol = deep_row.get("symbol", "?")
    return {
        "symbol"        : symbol,
        "group"         : deep_row.get("group", ""),
        "exchange"      : deep_row.get("exchange", get_exchange(symbol)),
        "time"          : now_ict().strftime("%Y-%m-%d %H:%M"),
        "date"          : today_str(),
        "history_5d"    : deep_row.get("_ohlcv_5d") or [],
        "volume_profile": [],
        "summary"       : {
            "symbol" : symbol,
            "error"  : error_msg,
            "pattern": "ERROR",
        },
        "error"         : error_msg,
    }


def fetch_one(deep_row: dict, market_open: bool) -> dict:
    symbol = deep_row.get("symbol", "?")

    try:
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

    except Exception as e:
        log.error(f"  ❌ {symbol} fetch_one error: {e}")
        traceback.print_exc()
        return _error_result(deep_row, str(e))

# =====================================================
# MAIN — chỉ khác step_order_flow.py ở input/output filenames (_v2)
# =====================================================

if __name__ == "__main__":
    trading = is_market_open()
    log.info(f"=== ORDER FLOW V2 START ({now_ict():%Y-%m-%d %H:%M:%S} ICT) ===")
    log.info(f"Market open: {trading}")

    load_exchange_map()

    # ── V2: đọc deep_raw_v2.json thay vì deep_raw.json ──
    deep_raw = load_json("deep_raw_v2.json")
    if not deep_raw:
        log.error("deep_raw_v2.json not found — chạy step_snapshot_v2.py trước")
        import sys; sys.exit(1)

    log.info(f"Processing {len(deep_raw)} symbols concurrently (workers={MAX_WORKERS})...")

    results_map: dict[str, dict] = {}

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        future_map = {
            executor.submit(fetch_one, row, trading): row["symbol"]
            for row in deep_raw
        }
        for future in as_completed(future_map):
            sym      = future_map[future]
            deep_row = next((r for r in deep_raw if r["symbol"] == sym), {"symbol": sym})
            try:
                results_map[sym] = future.result()
            except Exception as e:
                log.error(f"  ❌ {sym} future error: {e}")
                results_map[sym] = _error_result(deep_row, f"future error: {e}")

    results     = []
    error_count = 0
    for r in deep_raw:
        sym = r["symbol"]
        if sym in results_map:
            results.append(results_map[sym])
            if results_map[sym].get("error"):
                error_count += 1

    # ── V2: ghi order_flow_v2.json thay vì order_flow.json ──
    save_json("order_flow_v2.json", results)
    log.info(
        f"Saved order_flow_v2.json — {len(results)} symbols "
        f"({error_count} with errors)"
    )
    log.info("=== ORDER FLOW V2 DONE ===")
