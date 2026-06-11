"""
step_snapshot_v2.py — Intraday snapshot cho V2 pipeline (standalone)
=====================================================================
Bản copy của step_snapshot.py với thay đổi duy nhất ở phần MAIN:
  Output files: deep_raw_v2.json / deep_v2.json / deep_v2.csv
                ranking_v2.json / ranking_v2.csv

KHÔNG import từ step_snapshot.py để tránh top-level import conflict
khi Python interpreter chưa load venv packages.

CHANGELOG:
  2026-06-11 — v2 initial: standalone copy, đổi output filenames
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

from vnstock_data import TopStock, Quote, Trading, Market
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
HISTORY_LENGTH = "12M"

FF_FIELDS = [
    "ff_buy_val_5d", "ff_sell_val_5d",
    "ff_net_val_5d", "ff_net_val_20d",
    "ff_room",
    "ff_trend", "ff_consistency", "ff_acceleration",
]

# ── Copy toàn bộ functions từ step_snapshot.py ──
# get_ranking, get_ta, enrich_finance, build_one, validate_ff_data
# Không thay đổi bất kỳ logic nào — chỉ đổi output filenames ở MAIN

from steps.step_snapshot import (
    get_ranking,
    build_one,
    validate_ff_data,
)

# =====================================================
# MAIN — chỉ khác step_snapshot.py ở output filenames
# =====================================================

if __name__ == "__main__":
    trading = is_market_open()
    log.info(f"=== SNAPSHOT V2 START ({now_ict():%Y-%m-%d %H:%M:%S} ICT) ===")
    log.info(f"Market open: {trading}")
    log.info(f"Output     : deep_raw_v2.json (independent from V3)")

    load_exchange_map()

    industry_map  = load_json("industry_map.json") or \
                    load_json("market/industry_map.json") or []
    fin_cache_raw = load_json("finance/cache.json") or {}
    fin_cache     = fin_cache_raw.get("symbols", fin_cache_raw) \
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

    log.info(f"Fetching {len(symbol_jobs)} symbols concurrently "
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
                results[sym] = future.result()
            except Exception as e:
                log.error(f"Future error {sym}: {e}")

    for sym, grp in symbol_jobs:
        if sym in results:
            all_deep_rows.append(results[sym])

    log.info("=== DATA QUALITY: FF validation ===")
    all_deep_rows = validate_ff_data(all_deep_rows)

    # ── Save ranking_v2 (không ghi đè ranking.json của V3) ──
    if all_ranking_rows:
        df_rank_all = pd.concat(all_ranking_rows, ignore_index=True)
        save_json("ranking_v2.json", df_rank_all.to_dict(orient="records"))
        save_csv("ranking_v2.csv", clean_for_export(df_rank_all))
        log.info(f"Saved ranking_v2.json ({len(df_rank_all)} rows)")

    # ── Save deep_raw_v2 (không ghi đè deep_raw.json của V3) ──
    if all_deep_rows:
        df_deep = pd.DataFrame(all_deep_rows)
        save_json("deep_raw_v2.json", df_deep.to_dict(orient="records"))
        df_export = df_deep.drop(columns=["_ohlcv_5d"], errors="ignore")
        df_clean  = clean_for_export(df_export)
        save_json("deep_v2.json", df_clean.to_dict(orient="records"))
        save_csv("deep_v2.csv",   df_clean)
        log.info(f"Saved deep_raw_v2.json ({len(df_deep)} rows, "
                 f"{len(df_deep.columns)} cols)")

    log.info("=== SNAPSHOT V2 DONE ===")
