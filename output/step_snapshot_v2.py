"""
step_snapshot_v2.py — Intraday snapshot cho V2 pipeline
=========================================================
Clone của step_snapshot.py với thay đổi duy nhất:
  - Output: deep_raw_v2.json / deep_v2.json / deep_v2.csv / ranking_v2.json/csv
  - KHÔNG ghi đè deep_raw.json / deep.json / ranking.json của V3

Logic fetch, TA, FF, finance enrichment giữ nguyên hoàn toàn.

CHANGELOG:
  2026-06-11 — v2 initial: tách output files khỏi V3
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

# Import toàn bộ logic từ step_snapshot — không duplicate
from steps.step_snapshot import (
    get_ranking,
    build_one,
    validate_ff_data,
    FF_FIELDS,
    HISTORY_LENGTH,
    MAX_WORKERS,
)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(levelname)s %(message)s'
)
log = logging.getLogger(__name__)

# =====================================================
# OUTPUT FILE NAMES — v2 specific
# =====================================================
OUT_DEEP_RAW = "deep_raw_v2.json"
OUT_DEEP     = "deep_v2.json"
OUT_DEEP_CSV = "deep_v2.csv"
OUT_RANKING  = "ranking_v2.json"
OUT_RANK_CSV = "ranking_v2.csv"


# =====================================================
# MAIN
# =====================================================

if __name__ == "__main__":
    trading = is_market_open()
    log.info(f"=== SNAPSHOT V2 START ({now_ict():%Y-%m-%d %H:%M:%S} ICT) ===")
    log.info(f"Market open: {trading}")
    log.info(f"History    : {HISTORY_LENGTH} (for EMA200)")
    log.info(f"Output     : {OUT_DEEP_RAW} (independent from V3)")

    load_exchange_map()

    industry_map   = load_json("industry_map.json") or \
                     load_json("market/industry_map.json") or []
    fin_cache_raw  = load_json("finance/cache.json") or {}
    fin_cache      = fin_cache_raw.get("symbols", fin_cache_raw) \
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

    # ── Save ranking_v2 ──
    if all_ranking_rows:
        df_rank_all = pd.concat(all_ranking_rows, ignore_index=True)
        save_json(OUT_RANKING, df_rank_all.to_dict(orient="records"))
        save_csv(OUT_RANK_CSV, clean_for_export(df_rank_all))
        log.info(f"Saved {OUT_RANKING} ({len(df_rank_all)} rows)")

    # ── Save deep_raw_v2 ──
    if all_deep_rows:
        df_deep = pd.DataFrame(all_deep_rows)
        save_json(OUT_DEEP_RAW, df_deep.to_dict(orient="records"))
        df_export = df_deep.drop(columns=["_ohlcv_5d"], errors="ignore")
        df_clean  = clean_for_export(df_export)
        save_json(OUT_DEEP, df_clean.to_dict(orient="records"))
        save_csv(OUT_DEEP_CSV, df_clean)
        log.info(f"Saved {OUT_DEEP_RAW} ({len(df_deep)} rows, "
                 f"{len(df_deep.columns)} cols)")

    log.info("=== SNAPSHOT V2 DONE ===")
