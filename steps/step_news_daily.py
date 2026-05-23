# steps/step_news_daily.py
# Chạy trong cron_daily.yml — sau step3_context.py
# Crawl RSS từ các báo tài chính → tag industry + macro → lưu news_raw.json

import logging
from datetime import datetime, timezone, timedelta

from utils.cache import save_json
from utils.helpers import now_ict
from utils.industry_keywords import INDUSTRY_KEYWORDS, MACRO_KEYWORDS

log = logging.getLogger(__name__)

# ─── Cấu hình nguồn báo ──────────────────────────────────────────────────────
# Ưu tiên báo tài chính chuyên ngành (source_weight cao hơn)
FINANCE_SITES = [
    ("cafef",                   1.3),
    ("vietstock",               1.3),
    ("baodautu",                1.2),
    ("vneconomy",               1.1),
    ("thoibaotaichinhvietnam",  1.1),
    ("tuoitre",                 1.0),
    ("vnexpress",               1.0),
]

LIMIT_PER_FEED = 30   # bài / site — đủ cover tin trong ngày, không quá tải


# ─── Helpers ─────────────────────────────────────────────────────────────────

def _parse_time(raw) -> datetime | None:
    """Chuyển publish_time (string hoặc datetime) về datetime aware UTC."""
    if raw is None:
        return None
    if isinstance(raw, datetime):
        return raw if raw.tzinfo else raw.replace(tzinfo=timezone.utc)
    for fmt in (
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%d %H:%M:%S%z",
    ):
        try:
            dt = datetime.strptime(str(raw).strip(), fmt)
            return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


def _time_decay(publish_time_raw) -> float:
    """
    Trọng số theo tuổi tin:
      < 1h  → 1.00
      < 6h  → 0.85
      < 12h → 0.65
      < 24h → 0.40
      ≥ 24h → 0.20
    """
    dt = _parse_time(publish_time_raw)
    if dt is None:
        return 0.5
    now = now_ict()
    # đảm bảo cùng timezone để so sánh
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    age_hours = (now - dt).total_seconds() / 3600
    if age_hours < 0:      return 1.0   # tin tương lai (clock skew)
    if age_hours < 1:      return 1.00
    if age_hours < 6:      return 0.85
    if age_hours < 12:     return 0.65
    if age_hours < 24:     return 0.40
    return 0.20


def _tag_industries(text: str) -> list[str]:
    """Trả về list icb_name match với nội dung tin."""
    text_lower = text.lower()
    matched = []
    for industry, keywords in INDUSTRY_KEYWORDS.items():
        if any(kw.lower() in text_lower for kw in keywords):
            matched.append(industry)
    return matched


def _score_sentiment(text: str) -> float:
    """
    Tính raw sentiment dựa trên POSITIVE/NEGATIVE word list.
    Trả về float âm/dương, chưa nhân weight/decay.
    """
    POSITIVE = [
        "tăng", "tích cực", "khởi sắc", "hưởng lợi", "cơ hội",
        "tăng trưởng", "vượt kỳ vọng", "lợi nhuận cao", "kỷ lục",
        "bứt phá", "phục hồi", "tốt", "thuận lợi", "tăng mạnh",
    ]
    NEGATIVE = [
        "giảm", "tiêu cực", "rủi ro", "áp lực", "sụt giảm", "thua lỗ",
        "bị phạt", "điều tra", "nợ xấu", "mất thanh khoản", "cảnh báo",
        "khó khăn", "giảm mạnh", "thất bại", "vi phạm", "bắt giữ",
    ]
    t = text.lower()
    pos = sum(1 for w in POSITIVE if w in t)
    neg = sum(1 for w in NEGATIVE if w in t)
    return float(pos - neg)


def _score_macro(text: str) -> float:
    """Tổng bias từ MACRO_KEYWORDS có trong tin."""
    t = text.lower()
    return float(sum(bias for kw, bias in MACRO_KEYWORDS.items() if kw.lower() in t))


# ─── Crawl một site ──────────────────────────────────────────────────────────

def _crawl_site(site_name: str, source_weight: float) -> list[dict]:
    """
    Crawl RSS của một site, trả về list article đã enriched.
    Trả về [] nếu lỗi — không crash toàn bộ step.
    """
    try:
        from vnstock_news import Crawler
        crawler = Crawler(site_name=site_name)
        raw = crawler.get_articles_from_feed(limit_per_feed=LIMIT_PER_FEED)

        # get_articles_from_feed trả về List[Dict] theo docs
        if not isinstance(raw, list):
            # một số version có thể trả DataFrame
            try:
                raw = raw.to_dict("records")
            except Exception:
                raw = []

        enriched = []
        for art in raw:
            title = art.get("title") or ""
            desc  = art.get("short_description") or ""
            text  = f"{title} {desc}"

            industries  = _tag_industries(text)
            sentiment   = _score_sentiment(text)
            macro_score = _score_macro(text)
            decay       = _time_decay(art.get("publish_time"))

            enriched.append({
                "url":              art.get("url", ""),
                "title":            title,
                "short_description": desc,
                "publish_time":     str(art.get("publish_time", "")),
                "category":         art.get("category", ""),
                "tags":             art.get("tags", ""),
                "source":           site_name,
                "source_weight":    source_weight,
                "matched_industries": industries,
                "raw_sentiment":    sentiment,
                "macro_score":      macro_score,
                "time_decay":       decay,
                # weighted_sentiment dùng trong step_scoring — tính sẵn 1 lần
                "weighted_sentiment": round(sentiment * source_weight * decay, 4),
            })

        log.info(f"  ✅ {site_name}: {len(enriched)} articles, "
                 f"{sum(1 for a in enriched if a['matched_industries'])} tagged")
        return enriched

    except Exception as e:
        log.warning(f"  ⚠️ {site_name} failed: {e}")
        return []


# ─── Entry point ─────────────────────────────────────────────────────────────

def run():
    log.info("=== step_news_daily: START ===")

    all_articles: list[dict] = []
    for site_name, weight in FINANCE_SITES:
        articles = _crawl_site(site_name, weight)
        all_articles.extend(articles)

    # Dedup theo URL
    seen_urls: set[str] = set()
    deduped = []
    for a in all_articles:
        if a["url"] and a["url"] not in seen_urls:
            seen_urls.add(a["url"])
            deduped.append(a)

    tagged_count  = sum(1 for a in deduped if a["matched_industries"])
    macro_count   = sum(1 for a in deduped if a["macro_score"] != 0)

    log.info(f"  Total: {len(deduped)} articles "
             f"({tagged_count} industry-tagged, {macro_count} macro-tagged)")

    save_json("news_raw.json", deduped)
    log.info("=== step_news_daily: DONE ===")


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s"
    )
    run()
