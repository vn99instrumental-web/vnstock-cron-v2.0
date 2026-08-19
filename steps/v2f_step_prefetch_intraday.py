#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v2f_step_prefetch_intraday.py — Prefetch tape intraday DÙNG CHUNG (P0.1 + Option B)
===================================================================================
Chạy TRƯỚC snapshot. Fetch intraday(page_size=10000) MỘT LẦN mỗi mã (song song),
ghi ra cache; snapshot + order_flow đọc lại thay vì mỗi bên tự gọi.

Vì sao 10000 (không phải 200): order_flow cần TOÀN tape trong ngày để dựng volume
profile / POC / value area. Snapshot chỉ cần 200 lệnh gần nhất → tự cắt tail(200)
từ tape chung (giữ nguyên intra_buy_ratio). 10000 là superset của 200.

Song song hoá an toàn: benchmark (2026-08-19) cho thấy workers=3 / interval=0.35s
đạt 0 lần 429, 100% completeness, nhanh hơn đơn luồng ~119s. Vẫn bọc circuit
breaker của utils.vci_throttle như production.

ROLLBACK: PREFETCH_ENABLED=0 → step này tự bỏ qua (exit 0), snapshot/order_flow
fetch live như trước. Không cần sửa code.

ENV:
  PREFETCH_ENABLED    "1"      bật/tắt (0 = bỏ qua hoàn toàn)
  PREFETCH_WORKERS    "3"      số luồng fetch song song
  PREFETCH_INTERVAL   "0.35"   min-interval giữa 2 call VCI (giây)
  PREFETCH_PAGESIZE   "10000"  giống order_flow production
  PREFETCH_POST_COOLDOWN "5"   nghỉ cuối step cho VCI hồi trước khi snapshot chạy
  INTRADAY_CACHE_DIR  (mặc định output/cache/intraday)
"""
import os
import sys
import time
import uuid
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from vnstock_data import Quote

from utils.helpers import now_ict, is_market_open, today_str
from utils.vci_throttle import vci_safe_run, set_min_interval, is_blocked
from utils.v2f_universe import build_v2f_universe
from utils import intraday_cache

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("prefetch_intraday")

WORKERS       = int(os.environ.get("PREFETCH_WORKERS", "3"))
MIN_INTERVAL  = float(os.environ.get("PREFETCH_INTERVAL", "0.35"))
PAGESIZE      = int(os.environ.get("PREFETCH_PAGESIZE", "10000"))
POST_COOLDOWN = int(os.environ.get("PREFETCH_POST_COOLDOWN", "5"))


def _fetch_and_store(symbol: str) -> str:
    """Fetch tape 1 mã, ghi cache. Trả 'ok' | 'empty' | 'fail'."""
    if is_blocked():
        return "fail"
    df = vci_safe_run(
        f"prefetch {symbol}",
        lambda: Quote(source="VCI", symbol=symbol).intraday(page_size=PAGESIZE),
    )
    if df is None or getattr(df, "empty", True):
        return "empty"
    return "ok" if intraday_cache.write_tape(symbol, df) else "fail"


def main():
    # ── Rollback switch: tắt là bỏ qua, snapshot/order_flow tự fetch live ──
    if not intraday_cache.is_enabled():
        log.info("PREFETCH_ENABLED=0 → BỎ QUA prefetch. "
                 "snapshot/order_flow sẽ fetch live như cũ.")
        return

    trading = is_market_open()
    td = today_str()
    run_id = os.environ.get("GITHUB_RUN_ID") or uuid.uuid4().hex[:12]

    log.info(f"=== PREFETCH INTRADAY START ({now_ict():%Y-%m-%d %H:%M:%S} ICT) ===")
    log.info(f"market_open={trading}  workers={WORKERS}  interval={MIN_INTERVAL}s  "
             f"page_size={PAGESIZE}")

    jobs, _ = build_v2f_universe()
    symbols = [s for s, _g in jobs]
    if not symbols:
        log.error("Universe rỗng — không prefetch được. snapshot/order_flow sẽ fetch live.")
        # Không ghi manifest → read_tape trả None → fallback live. exit 0.
        return

    intraday_cache.reset_dir()          # xoá tape cũ, tránh dùng nhầm
    set_min_interval(MIN_INTERVAL)

    counts = {"ok": 0, "empty": 0, "fail": 0}
    t0 = time.monotonic()
    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        futs = {ex.submit(_fetch_and_store, s): s for s in symbols}
        for fut in as_completed(futs):
            try:
                label = fut.result()
            except Exception as e:
                log.warning(f"  prefetch {futs[fut]} exception: {e}")
                label = "fail"
            counts[label] = counts.get(label, 0) + 1
    wall = time.monotonic() - t0

    # Manifest: snap_time để consumer biết tape chụp lúc nào; market_date để chống
    # dùng nhầm tape của ngày khác (phòng thủ lớp 2 ngoài runner ephemeral).
    intraday_cache.write_manifest({
        "run_id"      : run_id,
        "market_date" : td,
        "snap_time"   : now_ict().strftime("%H:%M:%S"),
        "market_open" : trading,
        "n_symbols"   : len(symbols),
        "n_ok"        : counts["ok"],
        "n_empty"     : counts["empty"],
        "n_fail"      : counts["fail"],
        "workers"     : WORKERS,
        "interval"    : MIN_INTERVAL,
        "page_size"   : PAGESIZE,
        "wall_sec"    : round(wall, 1),
    })

    n = len(symbols)
    log.info(f"=== PREFETCH DONE: ok={counts['ok']} empty={counts['empty']} "
             f"fail={counts['fail']} / {n} mã trong {wall:.1f}s ===")
    if counts["ok"] == 0:
        log.warning("⚠️ Không mã nào prefetch thành công → snapshot/order_flow sẽ "
                    "fallback fetch live (an toàn, chỉ chậm như cũ).")

    if POST_COOLDOWN > 0:
        log.info(f"Cooldown {POST_COOLDOWN}s cho VCI hồi trước khi snapshot chạy...")
        time.sleep(POST_COOLDOWN)


if __name__ == "__main__":
    main()
