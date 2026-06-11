"""
step_price_levels_v2.py — Trade levels cho scoring v2
======================================================
Chạy SAU step_scoring_v2.py. Đọc signals_v2.json thay vì signals.json.
Output: trade_levels_v2.json / trade_levels_v2.csv

Logic hoàn toàn giống step_price_levels.py — chỉ đổi input/output file.
"""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

os.environ["VNSTOCK_INTERACTIVE"] = "0"
os.environ["VNSTOCK_LANGUAGE"]    = "en"
os.environ["MPLCONFIGDIR"]        = "/home/runner/.config/matplotlib"

import logging
import pandas as pd

from utils.helpers import now_ict
from utils.cache   import load_json, save_json, save_csv

# Import toàn bộ logic từ v1 — chỉ đổi file paths
from steps.step_price_levels import (
    compute_levels,
    compute_exit,
)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(levelname)s %(message)s'
)
log = logging.getLogger(__name__)

OUT_JSON = "trade_levels_v2.json"
OUT_CSV  = "trade_levels_v2.csv"


def run():
    log.info(f"=== PRICE LEVELS V2 START ({now_ict():%Y-%m-%d %H:%M:%S} ICT) ===")

    signals    = load_json("signals_v2.json")
    order_flow = load_json("order_flow.json")  # dùng chung với v3

    if not signals:
        log.error("signals_v2.json not found — abort")
        return

    if not order_flow:
        log.warning("order_flow.json not found — levels sẽ thiếu POC/VAL data")
        order_flow = []

    # Build order_flow map
    of_map = {}
    if isinstance(order_flow, list):
        for r in order_flow:
            if isinstance(r, dict) and r.get("symbol"):
                of_map[r["symbol"]] = r

    buy_results  = []
    exit_results = []

    for sig in signals:
        sym      = sig.get("symbol")
        decision = sig.get("decision", "NEUTRAL")
        of_full  = of_map.get(sym, {})
        of_sum   = of_full.get("summary", {}) if isinstance(of_full, dict) else {}

        if decision in ("BUY", "STRONG BUY"):
            res = compute_levels(sig, of_sum, of_full)
            buy_results.append(res)
            if res.get("skip"):
                log.info(f"  {sym} [{decision}] {res.get('entry_style','')} "
                         f"→ SKIP ({res['skip']})")
            else:
                log.info(f"  {sym} [{decision}/{res.get('confidence','')}] "
                         f"{res.get('entry_style','')} entry={res.get('entry')} "
                         f"SL={res.get('stop_loss')} ({res.get('risk_pct')}%) "
                         f"TP1={res.get('tp1')} RR={res.get('rr_tp1')}")
        elif decision in ("SELL", "STRONG SELL"):
            exit_results.append(compute_exit(sig, of_sum))

    out = {
        "generated_at"   : now_ict().isoformat(),
        "scoring_version": "v2",
        "buy_count"      : len(buy_results),
        "exit_count"     : len(exit_results),
        "buy_levels"     : buy_results,
        "exit_levels"    : exit_results,
    }
    save_json(OUT_JSON, out)

    if buy_results:
        df = pd.DataFrame(buy_results)
        col_order = [
            "symbol", "exchange", "decision", "confidence",
            "entry_style", "price", "entry_low", "entry", "entry_high",
            "stop_loss", "risk_pct", "tp1", "tp2", "rr_tp1",
            "rr_headroom", "size_hint", "nearest_support",
            "nearest_resist", "levels_used", "flags", "skip",
        ]
        cols = [c for c in col_order if c in df.columns]
        save_csv(OUT_CSV, df[cols])

    log.info(f"Done: {len(buy_results)} BUY levels, "
             f"{len(exit_results)} exit triggers")
    log.info("=== PRICE LEVELS V2 DONE ===")


if __name__ == "__main__":
    run()
