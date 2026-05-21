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
from vnstock_data import TopStock, Quote

from config import TOP_N
from utils.helpers import (
    now_ict, is_market_open, last_trading_date,
    load_exchange_map, get_exchange, is_hsx, safe_run
)
from utils.cache import save_json, save_csv
from utils.formatter import clean_for_export

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(levelname)s %(message)s'
)
log = logging.getLogger(__name__)

# =====================================================
# RANKING
# =====================================================

def get_ranking() -> dict:
    log.info("=== RANKING ===")
    ins  = TopStock()
    date = last_trading_date()
    return {
        "gainers"     : safe_run("gainer",
            lambda: ins.gainer(index="VNINDEX", limit=TOP_N)),
        "losers"      : safe_run("loser",
            lambda: ins.loser(index="VNINDEX",  limit=TOP_N)),
        "foreign_buy" : safe_run("foreign_buy",
            lambda: ins.foreign_buy(limit=TOP_N, date=date)),
        "foreign_sell": safe_run("foreign_sell",
            lambda: ins.foreign_sell(limit=TOP_N, date=date)),
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
                df_depth["buy_volume"],  errors="coerce").sum())
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
# MAIN
# =====================================================

if __name__ == "__main__":
    trading = is_market_open()
    log.info(f"Time       : {now_ict():%Y-%m-%d %H:%M:%S} ICT")
    log.info(f"Market open: {trading}")

    load_exchange_map()
    ranking = get_ranking()

    all_ranking_rows = []
    all_snapshot_rows = []
    top3_cache = {"gainers": [], "losers": []}

    for group, df_rank in [
        ("GAINER", ranking["gainers"]),
        ("LOSER",  ranking["losers"]),
    ]:
        if df_rank is None or df_rank.empty:
            continue

        symbols = df_rank["symbol"].tolist()
        df_rank["exchange"] = df_rank["symbol"].map(get_exchange)
        df_rank["group"]    = group

        # Lưu top 3 HSX vào cache cho step2
        hsx = [s for s in symbols if is_hsx(s)]
        top3_cache[group.lower() + "s"] = hsx[:3]

        all_ranking_rows.append(df_rank)

        # Snapshot
        snap_rows = [get_snapshot(s, trading) for s in symbols]
        for r in snap_rows:
            r["group"] = group
        all_snapshot_rows.extend(snap_rows)

    # =====================================================
    # EXPORT
    # =====================================================

    # Ranking CSV + JSON
    if all_ranking_rows:
        df_all_rank = pd.concat(all_ranking_rows, ignore_index=True)
        df_clean    = clean_for_export(df_all_rank)
        save_csv("ranking.csv", df_clean)
        save_json("ranking.json", df_clean.to_dict(orient="records"))

    # Snapshot CSV + JSON
    if all_snapshot_rows:
        df_snap  = pd.DataFrame(all_snapshot_rows)
        df_clean = clean_for_export(df_snap)
        save_csv("snapshot.csv", df_clean)
        save_json("snapshot.json", df_clean.to_dict(orient="records"))

    # Foreign flow CSV + JSON
    for label, df_ff in [
        ("foreign_buy",  ranking.get("foreign_buy")),
        ("foreign_sell", ranking.get("foreign_sell")),
    ]:
        if df_ff is not None and not df_ff.empty:
            df_ff["type"] = label.split("_")[1].upper()
            df_clean = clean_for_export(df_ff)
            save_csv(f"{label}.csv", df_clean)
            save_json(f"{label}.json", df_clean.to_dict(orient="records"))

    # Cache top 3 cho step2
    save_json("top3_cache.json", top3_cache)
    log.info(f"Top 3 cache: {top3_cache}")

    log.info("=== STEP 1 DONE ===")
