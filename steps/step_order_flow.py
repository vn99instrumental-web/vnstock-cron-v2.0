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
from vnstock_data import Quote

from utils.helpers import (
    now_ict, is_market_open,
    load_exchange_map, get_exchange,
    safe_run, start_str, today_str
)
from utils.cache import load_json, save_json

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(levelname)s %(message)s'
)
log = logging.getLogger(__name__)

# =====================================================
# VOLUME PROFILE từ intraday
# Columns VCI: time, price, volume, match_type, id
# =====================================================

def build_volume_profile(df: pd.DataFrame) -> list:
    """
    Tính volume profile từ intraday data:
    - Group theo price
    - Đếm số lệnh (trade_count) và tổng volume
    - Tính % theo count và volume
    """
    if df is None or df.empty:
        return []

    df = df.copy()
    df["price"]  = pd.to_numeric(df["price"],  errors="coerce")
    df["volume"] = pd.to_numeric(df["volume"], errors="coerce")
    df = df.dropna(subset=["price", "volume"])

    # Detect buy/sell từ match_type
    buy_mask  = df["match_type"].str.contains(
        "Buy", case=False, na=False)
    sell_mask = df["match_type"].str.contains(
        "Sell", case=False, na=False)
    df["is_buy"]  = buy_mask
    df["is_sell"] = sell_mask

    # Group theo price
    grouped = df.groupby("price").agg(
        trade_count = ("volume", "count"),
        volume      = ("volume", "sum"),
        buy_count   = ("is_buy",  "sum"),
        sell_count  = ("is_sell", "sum"),
        buy_volume  = ("volume", lambda x:
                       x[df.loc[x.index, "is_buy"]].sum()),
        sell_volume = ("volume", lambda x:
                       x[df.loc[x.index, "is_sell"]].sum()),
    ).reset_index()

    total_count  = grouped["trade_count"].sum()
    total_volume = grouped["volume"].sum()

    grouped["count_pct"]  = (grouped["trade_count"] / total_count * 100)\
                            .round(1)
    grouped["volume_pct"] = (grouped["volume"] / total_volume * 100)\
                            .round(1)
    grouped["buy_ratio"]  = (grouped["buy_count"] /
                             grouped["trade_count"]).round(2)

    # Sort giá giảm dần
    grouped = grouped.sort_values("price", ascending=False)

    return grouped.to_dict(orient="records")

# =====================================================
# SUMMARY từ volume profile + history
# =====================================================

def build_summary(
    symbol     : str,
    df_intra   : pd.DataFrame,
    df_hist    : pd.DataFrame,
    vol_profile: list,
    group      : str,
) -> dict:
    summary = {"symbol": symbol, "group": group}

    if not vol_profile:
        summary["error"] = "Không đủ data"
        return summary

    df_vp = pd.DataFrame(vol_profile)

    # ── POC by count (nhiều lệnh nhất) ──
    poc_count_idx  = df_vp["trade_count"].idxmax()
    poc_vol_idx    = df_vp["volume"].idxmax()
    poc_by_count   = float(df_vp.loc[poc_count_idx, "price"])
    poc_by_volume  = float(df_vp.loc[poc_vol_idx,   "price"])

    summary["poc_by_count"]  = poc_by_count
    summary["poc_by_volume"] = poc_by_volume
    summary["poc_diverge"]   = abs(poc_by_count - poc_by_volume) > \
                               poc_by_volume * 0.005  # >0.5% khác nhau

    # ── Value Area 70% by count ──
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

    # ── Totals ──
    summary["total_trades"]    = int(df_vp["trade_count"].sum())
    summary["total_volume"]    = int(df_vp["volume"].sum())
    summary["avg_trade_size"]  = round(
        summary["total_volume"] / summary["total_trades"], 0) \
        if summary["total_trades"] > 0 else None

    # ── Trader type từ avg_trade_size ──
    ats = summary["avg_trade_size"]
    if ats:
        if ats < 1000:
            summary["trader_type"] = "Retail"
        elif ats < 10000:
            summary["trader_type"] = "Mixed"
        else:
            summary["trader_type"] = "Institutional"

    # ── Buy/sell ratio hôm nay ──
    if df_intra is not None and not df_intra.empty:
        df_intra["volume"] = pd.to_numeric(
            df_intra["volume"], errors="coerce")
        buy_mask  = df_intra["match_type"].str.contains(
            "Buy", case=False, na=False)
        sell_mask = df_intra["match_type"].str.contains(
            "Sell", case=False, na=False)
        buy_vol   = float(df_intra.loc[buy_mask,  "volume"].sum())
        sell_vol  = float(df_intra.loc[sell_mask, "volume"].sum())
        total     = buy_vol + sell_vol
        summary["buy_ratio_today"]  = round(buy_vol / total, 2) \
                                      if total > 0 else None
        summary["sell_ratio_today"] = round(sell_vol / total, 2) \
                                      if total > 0 else None

    # ── Current price vs POC ──
    if df_hist is not None and not df_hist.empty:
        current_price = float(df_hist["close"].iloc[-1])
        summary["current_price"]    = current_price
        summary["price_vs_poc_pct"] = round(
            (current_price - poc_by_count) / poc_by_count * 100, 2) \
            if poc_by_count != 0 else None

    # ── Volume spike 5d vs history ──
    if df_hist is not None and len(df_hist) >= 5:
        df_hist["volume"] = pd.to_numeric(
            df_hist["volume"], errors="coerce")
        vol_5d_avg = float(df_hist["volume"].tail(5).mean())
        vol_today  = float(df_hist["volume"].iloc[-1])
        summary["vol_5d_avg"]   = round(vol_5d_avg, 0)
        summary["vol_today"]    = round(vol_today, 0)
        summary["vol_spike_pct"]= round(
            vol_today / vol_5d_avg * 100 - 100, 1) \
            if vol_5d_avg > 0 else None

    # ── Distribution type từ volume profile ──
    summary["distribution_type"] = classify_distribution(df_vp)

    # ── Pattern tổng hợp ──
    summary["pattern"] = classify_pattern(summary)

    return summary

# =====================================================
# CLASSIFY DISTRIBUTION
# =====================================================

def classify_distribution(df_vp: pd.DataFrame) -> str:
    """
    Phân loại hình dạng phân phối volume theo giá
    """
    if df_vp.empty or len(df_vp) < 3:
        return "INSUFFICIENT_DATA"

    counts    = df_vp.sort_values("price")["trade_count"].values
    total     = counts.sum()
    n         = len(counts)

    # Tính entropy — đo độ phân tán
    pcts  = counts / total
    pcts  = pcts[pcts > 0]
    entropy = -np.sum(pcts * np.log(pcts))
    max_entropy = np.log(n)
    norm_entropy = entropy / max_entropy if max_entropy > 0 else 0

    # Top 3 mức giá chiếm bao nhiêu %
    top3_pct = sorted(pcts, reverse=True)[:3]
    top3_sum = sum(top3_pct)

    # Tìm số đỉnh (local maxima)
    peaks = 0
    for i in range(1, n - 1):
        if counts[i] > counts[i-1] and counts[i] > counts[i+1]:
            peaks += 1

    if norm_entropy < 0.7 and peaks == 1:
        return "NORMAL"       # 1 đỉnh rõ ràng
    elif peaks >= 2:
        return "BIMODAL"      # 2 đỉnh — tranh chấp
    elif norm_entropy > 0.9:
        return "FLAT"         # phân phối đều
    else:
        # Xem phân phối lệch về đâu
        mid = n // 2
        upper_sum = counts[mid:].sum()
        lower_sum = counts[:mid].sum()
        if upper_sum > lower_sum * 1.3:
            return "SKEWED_UP"    # lệch lên — áp lực mua
        elif lower_sum > upper_sum * 1.3:
            return "SKEWED_DOWN"  # lệch xuống — áp lực bán
        else:
            return "NORMAL"

# =====================================================
# CLASSIFY PATTERN
# =====================================================

def classify_pattern(summary: dict) -> str:
    """
    Kết hợp distribution + buy_ratio + vol_spike
    → Phân loại pattern tổng thể
    """
    dist      = summary.get("distribution_type", "")
    buy_ratio = summary.get("buy_ratio_today")
    vol_spike = summary.get("vol_spike_pct")
    poc_pct   = summary.get("price_vs_poc_pct")
    poc_div   = summary.get("poc_diverge", False)

    # Spike bất thường + 1 tổ chức
    if poc_div and summary.get("trader_type") == "Institutional":
        return "INSTITUTIONAL_ACTIVITY"

    # Volume thấp + giá tăng → yếu
    if vol_spike is not None and vol_spike < -20:
        return "WEAK"

    # Volume đột biến
    if vol_spike is not None and vol_spike > 100:
        if buy_ratio and buy_ratio > 0.65:
            return "SPIKE_BUY"
        elif buy_ratio and buy_ratio < 0.35:
            return "SPIKE_SELL"
        else:
            return "SPIKE_NEUTRAL"

    # Normal distribution — tích lũy hay phân phối
    if dist in ["NORMAL", "SKEWED_UP"]:
        if buy_ratio and buy_ratio > 0.60:
            return "ACCUMULATION"
        elif buy_ratio and buy_ratio < 0.40:
            return "DISTRIBUTION"

    if dist == "BIMODAL":
        return "CONTENTION"    # giằng co

    if dist == "FLAT":
        return "NORMAL"

    return "NORMAL"

# =====================================================
# LẤY DATA CHO 1 SYMBOL
# =====================================================

def get_order_flow_data(
    symbol     : str,
    group      : str,
    market_open: bool,
) -> dict:
    log.info(f"  OrderFlow: {symbol}")

    # History 5D — OHLCV
    df_hist = safe_run(f"hist5d {symbol}",
               lambda: Quote(source="VCI", symbol=symbol)\
                       .history(length="5D", interval="1D"))

    # Intraday hôm nay — tất cả lệnh có thể
    df_intra = None
    if market_open:
        df_intra = safe_run(f"intraday {symbol}",
                   lambda: Quote(source="VCI", symbol=symbol)\
                           .intraday(page_size=10000))
    else:
        # Ngoài giờ: lấy page_size lớn để có đủ lệnh của phiên
        df_intra = safe_run(f"intraday_eod {symbol}",
                   lambda: Quote(source="VCI", symbol=symbol)\
                           .intraday(page_size=10000))

    # Build volume profile từ intraday
    vol_profile = build_volume_profile(df_intra)

    # Build history 5D summary
    hist_5d = []
    if df_hist is not None and not df_hist.empty:
        df_hist["volume"] = pd.to_numeric(
            df_hist["volume"], errors="coerce")
        avg_vol = float(df_hist["volume"].mean())
        for _, row in df_hist.iterrows():
            vol = float(row["volume"])
            hist_5d.append({
                "date"          : str(row["time"])[:10],
                "open"          : round(float(row["open"]),  2),
                "high"          : round(float(row["high"]),  2),
                "low"           : round(float(row["low"]),   2),
                "close"         : round(float(row["close"]), 2),
                "volume"        : int(vol),
                "vs_avg5d_pct"  : round(vol / avg_vol * 100 - 100, 1)
                                  if avg_vol > 0 else None,
            })

    # Build summary
    summary = build_summary(
        symbol, df_intra, df_hist, vol_profile, group)

    return {
        "symbol"        : symbol,
        "group"         : group,
        "exchange"      : get_exchange(symbol),
        "time"          : now_ict().strftime("%Y-%m-%d %H:%M"),
        "date"          : today_str(),
        "history_5d"    : hist_5d,
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

    # Đọc top symbols từ deep_raw.json
    deep_raw = load_json("deep_raw.json")
    if not deep_raw:
        log.error("Không tìm thấy deep_raw.json — chạy step_all trước")
        import sys; sys.exit(1)

    log.info(f"Processing {len(deep_raw)} symbols...")

    results = []
    for row in deep_raw:
        symbol = row["symbol"]
        group  = row.get("group", "")
        result = get_order_flow_data(symbol, group, trading)
        results.append(result)

        s = result["summary"]
        log.info(f"  [{symbol}] "
                 f"pattern={s.get('pattern')}, "
                 f"dist={s.get('distribution_type')}, "
                 f"poc_count={s.get('poc_by_count')}, "
                 f"buy_ratio={s.get('buy_ratio_today')}, "
                 f"vol_spike={s.get('vol_spike_pct')}%")

    save_json("order_flow.json", results)
    log.info(f"Saved order_flow.json — {len(results)} symbols")
    log.info("=== ORDER FLOW DONE ===")
