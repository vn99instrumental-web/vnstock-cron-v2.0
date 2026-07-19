# scripts/run_news_daily_dry.py
# ============================================================================
# DRY RUN cho step_news_daily v2 qua debug.yml — KHÔNG cần bật cron_daily.
#
# debug.yml không có bước commit output/ → mọi file step ghi ra
# (news/raw.json, news/history.json, news/today_index.json) chỉ tồn tại
# trên runner và bị bỏ khi job kết thúc. Repo không thay đổi.
#
# Chạy: trigger debug.yml với script = scripts/run_news_daily_dry.py
#
# Sau khi run() xong, script dump thêm phần DECODE: news_score từng mã
# universe theo đúng công thức consumer (build_news_scores) để đánh giá
# phân phối điểm trên dữ liệu THẬT trước khi bật vào cron_daily.
# ============================================================================
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import logging
log = logging.getLogger("news_dry")

from steps import step_news_daily as snd
from utils.cache import load_json


def _decode_dump():
    """Mô phỏng build_news_scores: in news_score cho mã có mention/industry."""
    idx = load_json("news/today_index.json") or {}
    if not idx:
        log.warning("today_index.json trống — không decode được")
        return

    by_industry     = idx.get("by_industry", {})
    symbol_mentions = idx.get("symbol_mentions", {})
    macro           = idx.get("macro", {})
    macro_c         = float(macro.get("score", 1.0)) - 1.0

    industry_map = load_json("market/industry_map.json") or \
                   load_json("industry_map.json") or []
    icb_of = {}
    for r in industry_map:
        s = r.get("symbol") or r.get("ticker") or r.get("code")
        if s:
            icb_of[str(s).strip().upper()] = r.get("icb_name") or ""

    universe = snd._load_universe()
    if not universe:
        universe = set(symbol_mentions.keys())

    rows = []
    for sym in sorted(universe):
        ind   = icb_of.get(sym, "")
        ind_c = float(by_industry.get(ind, {}).get("score", 2.0)) - 2.0
        sym_c = float(symbol_mentions.get(sym, {}).get("score", 2.0)) - 2.0
        total = max(-5.0, min(5.0, round(ind_c + sym_c + macro_c, 2)))
        if total != 0 or sym in symbol_mentions:
            rows.append((total, sym, sym_c, ind_c, ind))

    rows.sort(key=lambda r: r[0], reverse=True)
    log.info("=== DECODE: news_score theo công thức consumer "
             f"(macro component {macro_c:+.2f}) ===")
    log.info(f"  {len(rows)}/{len(universe)} mã có news_score ≠ 0")
    for total, sym, sym_c, ind_c, ind in rows:
        log.info(f"  {sym:5s} total {total:+5.2f}  "
                 f"(sym {sym_c:+5.2f} | ind {ind_c:+5.2f})  {ind[:30]}")

    n_pos = sum(1 for r in rows if r[0] >= 1)
    n_neg = sum(1 for r in rows if r[0] <= -1)
    log.info(f"  Phân phối: {n_pos} mã ≥ +1 | {n_neg} mã ≤ -1 | "
             f"{len(rows) - n_pos - n_neg} mã trong (-1, +1)")
    log.info("=== DECODE: DONE ===")


if __name__ == "__main__":
    log.info(">>> DRY RUN step_news_daily v2 (debug.yml — không commit output)")
    snd.run()
    _decode_dump()
    log.info(">>> DRY RUN DONE — kiểm tra block METRICS + DECODE ở trên")
