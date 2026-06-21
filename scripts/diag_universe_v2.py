"""
scripts/diag_universe_v2.py — Chẩn đoán PASS 1 của VN100 universe (V2)
======================================================================
Chỉ chạy pass 1 (NHẸ): Listing.symbols_by_group + TopStock gainer/loser.
KHÔNG đụng TA 12M / FF / depth → cực rẻ, an toàn quota.

Trả lời 2 câu hỏi trước khi wire vào cron_intraday.yml:
  1) Với VN100_RANK_LIMIT mặc định, có bắt đủ TOP_X gainer + TOP_X loser
     trong rổ VN100 không?
  2) TopStock có CAP số dòng trả về không? (limit sweep: nếu số mã VN100 bắt
     được ngừng tăng khi limit tăng → đã chạm cap.)

Chạy:  python scripts/diag_universe_v2.py
Qua debug.yml: truyền tên script `diag_universe_v2`.
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

os.environ["VNSTOCK_INTERACTIVE"] = "0"
os.environ["VNSTOCK_LANGUAGE"]    = "en"
os.environ["MPLCONFIGDIR"]        = "/home/runner/.config/matplotlib"
os.makedirs("/home/runner/.vnstock",           exist_ok=True)
os.makedirs("/home/runner/.config/matplotlib", exist_ok=True)

import logging
logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("diag_universe")

from utils.universe_v2 import (
    build_vn100_universe, fetch_index_members,
    INDEX_GROUP, RANK_LIMIT, TOP_X,
)


def main():
    log.info("=" * 64)
    log.info(f"DIAG UNIVERSE V2 — group={INDEX_GROUP} "
             f"RANK_LIMIT={RANK_LIMIT} TOP_X={TOP_X}")
    log.info("=" * 64)

    # ── 0. VN100 list ──
    t0 = time.time()
    vn100 = fetch_index_members(INDEX_GROUP)
    log.info(f"[0] {INDEX_GROUP}: {len(vn100)} mã "
             f"(fetch {time.time()-t0:.1f}s) — sample: {vn100[:10]}")
    if not vn100:
        log.error("VN100 rỗng — symbols_by_group fail. Dừng.")
        return

    # ── 1. Build universe mặc định (đúng cấu hình production) ──
    t1 = time.time()
    symbol_jobs, ranking_rows = build_vn100_universe()
    dt1 = time.time() - t1
    g = [r for r in ranking_rows if r.get("group") == "GAINER"]
    l = [r for r in ranking_rows if r.get("group") == "LOSER"]
    log.info(f"[1] build_vn100_universe() {dt1:.1f}s → "
             f"{len(symbol_jobs)} mã ({len(g)} gainer / {len(l)} loser)")
    log.info(f"    đủ TOP_X? gainer={len(g)}/{TOP_X}  loser={len(l)}/{TOP_X}")
    for tag, rows in (("GAINER", g), ("LOSER", l)):
        for r in rows:
            log.info(f"    {tag:6s} {r['symbol']:6s} "
                     f"%={r.get('price_change_percent_1d')} "
                     f"Δ={r.get('price_change_1d')} "
                     f"val={r.get('accumulated_value')}")

    # ── 2. Limit sweep — dò TopStock có cap không ──
    # top_x=999 để KHÔNG cắt → đếm tổng số mã VN100 xuất hiện ở mỗi limit.
    log.info("-" * 64)
    log.info("[2] LIMIT SWEEP (top_x=999 → đếm full số mã VN100 bắt được):")
    prev = None
    for lim in (100, 300, 500, 1000):
        ts = time.time()
        jobs, rows = build_vn100_universe(top_x=999, rank_limit=lim)
        ng = sum(1 for r in rows if r.get("group") == "GAINER")
        nl = sum(1 for r in rows if r.get("group") == "LOSER")
        plateau = "  ← bằng limit trước (nghi CAP)" if prev == (ng, nl) else ""
        log.info(f"    limit={lim:5d} → {ng:3d} gainer + {nl:3d} loser "
                 f"trong VN100 ({time.time()-ts:.1f}s){plateau}")
        prev = (ng, nl)

    log.info("=" * 64)
    log.info("KẾT LUẬN nhanh:")
    log.info("  - [1] đủ TOP_X mỗi phía → giữ RANK_LIMIT mặc định, wire được.")
    log.info("  - [1] thiếu nhưng [2] còn tăng theo limit → tăng VN100_RANK_LIMIT.")
    log.info("  - [2] plateau sớm (vd dừng ở ~50) → TopStock CAP, cần đổi pass-1.")
    log.info("=" * 64)


if __name__ == "__main__":
    main()
