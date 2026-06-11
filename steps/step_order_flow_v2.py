"""
step_order_flow_v2.py — Volume profile + pattern cho V2 pipeline
=================================================================
Clone của step_order_flow.py với thay đổi duy nhất:
  - Input : deep_raw_v2.json (không dùng deep_raw.json của V3)
  - Output: order_flow_v2.json (không ghi đè order_flow.json của V3)

Logic volume profile, pattern classify, concurrent fetch giữ nguyên.

CHANGELOG:
  2026-06-11 — v2 initial: tách input/output files khỏi V3
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
from concurrent.futures import ThreadPoolExecutor, as_completed

from utils.helpers import now_ict, is_market_open, load_exchange_map, get_exchange
from utils.cache import load_json, save_json

# Import toàn bộ logic từ step_order_flow — không duplicate
from steps.step_order_flow import (
    fetch_one,
    _error_result,
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
IN_DEEP_RAW   = "deep_raw_v2.json"
OUT_ORDER_FLOW = "order_flow_v2.json"


# =====================================================
# MAIN
# =====================================================

if __name__ == "__main__":
    trading = is_market_open()
    log.info(f"=== ORDER FLOW V2 START ({now_ict():%Y-%m-%d %H:%M:%S} ICT) ===")
    log.info(f"Market open: {trading}")
    log.info(f"Input      : {IN_DEEP_RAW}")
    log.info(f"Output     : {OUT_ORDER_FLOW}")

    load_exchange_map()

    deep_raw = load_json(IN_DEEP_RAW)
    if not deep_raw:
        log.error(f"{IN_DEEP_RAW} not found — chạy step_snapshot_v2.py trước")
        import sys; sys.exit(1)

    log.info(f"Processing {len(deep_raw)} symbols concurrently "
             f"(workers={MAX_WORKERS})...")

    results_map: dict[str, dict] = {}

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        future_map = {
            executor.submit(fetch_one, row, trading): row["symbol"]
            for row in deep_raw
        }
        for future in as_completed(future_map):
            sym = future_map[future]
            deep_row = next(
                (r for r in deep_raw if r["symbol"] == sym),
                {"symbol": sym}
            )
            try:
                results_map[sym] = future.result()
            except Exception as e:
                log.error(f"  ❌ {sym} future error: {e}")
                results_map[sym] = _error_result(deep_row, f"future error: {e}")

    # Restore original order — giữ đủ entries
    results = []
    error_count = 0
    for r in deep_raw:
        sym = r["symbol"]
        if sym in results_map:
            results.append(results_map[sym])
            if results_map[sym].get("error"):
                error_count += 1

    save_json(OUT_ORDER_FLOW, results)
    log.info(f"Saved {OUT_ORDER_FLOW} — {len(results)} symbols "
             f"({error_count} with errors)")
    log.info("=== ORDER FLOW V2 DONE ===")
