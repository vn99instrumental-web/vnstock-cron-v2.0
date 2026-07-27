"""
steps/step_news_collect.py — Thu thập & tổng hợp tin (thay vnstock_news)
========================================================================
Chạy trong .github/workflows/cron_news.yml (n8n trigger, TRƯỚC intraday).

LUỒNG:
  1. Đọc 5 nguồn RSS (utils/news_sources)                 ← A3: chỉ RSS
  2. Bài RSS thiếu mô tả & là bài MỚI → fetch body        ← C2 + cache history
  3. Enrich từng bài (ngành/type/effective_date/cảm xúc/độ tươi)
  4. Dedup theo URL + tiêu đề chuẩn hóa (gộp tin trùng giữa các nguồn)
  5. Gộp với history 30 ngày
  6. Tổng hợp → today_index.json (schema cũ, D1) + insights.json (mới)
  7. Ghi raw.json, history.json

FAIL-SOFT: lỗi 1 feed / 1 bài → bỏ qua, không chặn. Script luôn exit 0.

Không cần package sponsor (vnstock_*). Chỉ cần: requests, feedparser,
beautifulsoup4, lxml, pandas (cài trong workflow).
"""
import os
import sys
import logging
from datetime import timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.cache import save_json, load_json
from utils.helpers import now_ict
from utils.news_sources import SOURCES, LIMIT_PER_FEED, HISTORY_DAYS
from utils import news_rss
from utils.news_enrich import enrich_article, parse_time, normalize
from utils.news_aggregate import build_outputs

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

# Trần fetch body mỗi lần chạy (an toàn — chặn tải chạy loạn nếu feed lỗi hàng loạt)
MAX_BODY_FETCH = 80


def _load_history() -> list:
    return load_json("news/history.json") or load_json("news_history.json") or []


def _collect(known_desc: dict) -> list:
    """
    Đọc tất cả feed → enrich. known_desc: url→desc (từ history) để né fetch lại.
    Chỉ fetch body cho bài MỚI có mô tả rỗng, tối đa MAX_BODY_FETCH bài.
    """
    now = now_ict()
    all_articles: list = []
    n_body = 0

    for src in SOURCES:
        name = src["name"]
        weight = src.get("weight", 1.0)
        for feed_url in src["feeds"]:
            for raw in news_rss.fetch_feed(feed_url, name, LIMIT_PER_FEED):
                url = raw.get("url", "")
                desc = raw.get("short_description", "")

                # C2: mô tả rỗng → ưu tiên dùng lại history; nếu bài mới thì fetch body
                if news_rss.needs_body(desc):
                    if url in known_desc and known_desc[url]:
                        raw["short_description"] = known_desc[url]
                    elif url and n_body < MAX_BODY_FETCH:
                        body = news_rss.fetch_body(url)
                        if body:
                            raw["short_description"] = body
                            n_body += 1

                try:
                    all_articles.append(enrich_article(raw, name, weight, now))
                except Exception as e:
                    log.debug(f"  enrich fail {url}: {e}")

    log.info(f"  Fetch body (bài mới thiếu mô tả): {n_body}")
    return all_articles


def _dedup(articles: list) -> list:
    """Khử trùng theo URL và theo tiêu đề chuẩn hóa (tin trùng giữa các nguồn)."""
    seen_url, seen_title, out = set(), set(), []
    for a in articles:
        url = a.get("url", "")
        tkey = normalize(a.get("title", ""))[:120]
        if url and url in seen_url:
            continue
        if tkey and tkey in seen_title:
            continue
        if url:
            seen_url.add(url)
        if tkey:
            seen_title.add(tkey)
        out.append(a)
    return out


def _update_history(new_articles: list, history: list) -> list:
    """Thêm bài mới, cắt bài quá HISTORY_DAYS (giữ tin delayed tới hết hiệu lực +3d)."""
    now = now_ict()
    cutoff = now - timedelta(days=HISTORY_DAYS)
    existing = {a["url"] for a in history if a.get("url")}
    added = 0
    for art in new_articles:
        if art.get("url") and art["url"] not in existing:
            history.append(art)
            existing.add(art["url"])
            added += 1

    def _keep(art):
        pub = parse_time(art.get("publish_time"))
        if pub and pub.replace(tzinfo=timezone.utc) < cutoff.replace(tzinfo=timezone.utc):
            if art.get("news_type") == "delayed" and art.get("effective_date"):
                eff = parse_time(art["effective_date"])
                if eff:
                    return (now - eff).total_seconds() / 86400 <= 3
            return False
        return True

    before = len(history)
    history = [a for a in history if _keep(a)]
    log.info(f"  History: +{added} mới, -{before - len(history)} cắt, "
             f"{len(history)} tổng")
    save_json("news/history.json", history)
    save_json("news_history.json", history)
    return history


def run():
    log.info("=== step_news_collect: START ===")
    now = now_ict()

    history = _load_history()
    known_desc = {a.get("url"): a.get("short_description", "")
                  for a in history if a.get("url")}

    articles = _collect(known_desc)
    deduped = _dedup(articles)
    log.info(f"  Thu {len(articles)} bài -> {len(deduped)} sau dedup")

    save_json("news/raw.json", deduped)
    save_json("news_raw.json", deduped)

    history = _update_history(deduped, history)

    # Gộp bài hôm nay + history (khử trùng URL) để tính index
    seen, merged = set(), []
    for art in deduped + history:
        u = art.get("url", "")
        if u and u not in seen:
            seen.add(u)
            merged.append(art)

    industry_map = (load_json("market/industry_map.json")
                    or load_json("industry_map.json") or [])
    log.info(f"  Industry map: {len(industry_map)} mã")

    today_index, insights = build_outputs(merged, industry_map, now)

    save_json("news/today_index.json", today_index)   # schema cũ
    save_json("news_today_index.json", today_index)    # path phẳng cho scoring cũ
    save_json("news/insights.json", insights)          # bản mới, giàu

    log.info(f"  Index: {len(today_index['by_industry'])} ngành, "
             f"{len(today_index['symbol_mentions'])} mã")
    log.info(f"  Insights: {insights['totals']}")
    log.info("=== step_news_collect: DONE ===")


if __name__ == "__main__":
    try:
        run()
    except Exception as e:
        log.error(f"FATAL: {e}", exc_info=True)
        # fail-soft: không để workflow đỏ vì lỗi news
        sys.exit(0)
