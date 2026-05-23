# steps/step_news_daily.py
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

os.environ["VNSTOCK_INTERACTIVE"] = "0"
os.environ["VNSTOCK_LANGUAGE"]    = "en"
os.environ["MPLCONFIGDIR"]        = "/home/runner/.config/matplotlib"
os.makedirs("/home/runner/.vnstock",           exist_ok=True)
os.makedirs("/home/runner/.config/matplotlib", exist_ok=True)

import re
import logging
from datetime import datetime, timezone, timedelta

from utils.cache import save_json, load_json
from utils.helpers import now_ict
from utils.industry_keywords import (
    INDUSTRY_KEYWORDS, MACRO_KEYWORDS,
    NEWS_TYPE_KEYWORDS, EFFECTIVE_DATE_PATTERNS,
)

log = logging.getLogger(__name__)
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(levelname)s %(message)s'
)

# ─── Cấu hình ────────────────────────────────────────────────────────────────

FINANCE_SITES = [
    ("baodautu",                1.2),
    ("vietstock",               1.3),
    ("thoibaotaichinhvietnam",  1.1),
    ("cafebiz",                 1.0),
    ("znews",                   1.0),
    ("vietnamnet",              1.0),
    ("tuoitre",                 1.0),
    ("vnexpress",               1.0),
    ("dantri",                  0.9),
    ("thanhnien",               0.9),
    ("tienphong",               0.9),
    ("nld",                     0.9),
    ("petrotimes",              1.0),
    ("nhandan",                 0.8),
]

LIMIT_PER_FEED  = 30
HISTORY_DAYS    = 30   # giữ tối đa 30 ngày trong history


# ─── Time helpers ─────────────────────────────────────────────────────────────

def _parse_time(raw) -> datetime | None:
    if raw is None:
        return None
    if isinstance(raw, datetime):
        return raw if raw.tzinfo else raw.replace(tzinfo=timezone.utc)
    for fmt in (
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%d %H:%M:%S%z",
        "%Y-%m-%d",
    ):
        try:
            dt = datetime.strptime(str(raw).strip()[:19], fmt)
            return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


# ─── Classify news type ───────────────────────────────────────────────────────

def _classify_news_type(text: str) -> str:
    """
    Phân loại tin: immediate / delayed / monitoring
    Ưu tiên: delayed > monitoring > immediate
    """
    t = text.lower()
    if any(kw in t for kw in NEWS_TYPE_KEYWORDS["delayed"]):
        return "delayed"
    if any(kw in t for kw in NEWS_TYPE_KEYWORDS["monitoring"]):
        return "monitoring"
    return "immediate"


# ─── Extract effective date ───────────────────────────────────────────────────

def _extract_effective_date(text: str) -> str | None:
    """
    Cố gắng parse ngày hiệu lực từ text.
    Trả về string YYYY-MM-DD hoặc None.
    """
    now  = now_ict()
    year = now.year
    t    = text.lower()

    for pattern in EFFECTIVE_DATE_PATTERNS:
        m = re.search(pattern, t)
        if not m:
            continue

        groups = [g for g in m.groups() if g is not None]
        if not groups:
            continue

        try:
            raw = groups[0]

            # Dạng quý: "quý 3" → ngày đầu quý
            if "quý" in pattern:
                quarter = int(raw)
                q_year  = int(groups[1]) if len(groups) > 1 else year
                month   = (quarter - 1) * 3 + 1
                return f"{q_year}-{month:02d}-01"

            # Dạng tháng: "tháng 6"
            if "tháng" in pattern:
                month  = int(raw)
                y      = int(groups[1]) if len(groups) > 1 else year
                # Nếu tháng đã qua trong năm nay → sang năm sau
                if month < now.month:
                    y = year + 1
                return f"{y}-{month:02d}-01"

            # Dạng ngày/tháng hoặc ngày/tháng/năm
            parts = re.split(r"[\/\-]", raw)
            if len(parts) == 2:
                d, mo = int(parts[0]), int(parts[1])
                y = year
                # Nếu tháng đã qua → sang năm sau
                if mo < now.month or (mo == now.month and d < now.day):
                    y = year + 1
                return f"{y}-{mo:02d}-{d:02d}"
            elif len(parts) == 3:
                d, mo, y = int(parts[0]), int(parts[1]), int(parts[2])
                if y < 100:
                    y += 2000
                return f"{y}-{mo:02d}-{d:02d}"

        except (ValueError, IndexError):
            continue

    return None


# ─── Impact decay ─────────────────────────────────────────────────────────────

def _impact_decay(article: dict, now: datetime) -> float:
    """
    Tính decay theo news_type và effective_date.

    immediate : decay nhanh theo giờ
    delayed   : peak tại effective_date, buildup trước, giảm sau
    monitoring: decay chậm theo ngày
    """
    news_type      = article.get("news_type", "immediate")
    publish_time   = _parse_time(article.get("publish_time"))
    effective_date = _parse_time(article.get("effective_date"))

    # Ensure timezone
    if publish_time and not publish_time.tzinfo:
        publish_time = publish_time.replace(tzinfo=timezone.utc)

    if news_type == "immediate":
        if publish_time is None:
            return 0.5
        age_hours = (now - publish_time).total_seconds() / 3600
        if age_hours < 0:    return 1.00
        if age_hours < 1:    return 1.00
        if age_hours < 6:    return 0.85
        if age_hours < 12:   return 0.65
        if age_hours < 24:   return 0.40
        return 0.20

    elif news_type == "delayed":
        if effective_date is None:
            # Không parse được effective_date → treat như monitoring
            if publish_time is None:
                return 0.40
            age_days = (now - publish_time).total_seconds() / 86400
            if age_days < 1:  return 0.70
            if age_days < 3:  return 0.55
            if age_days < 7:  return 0.40
            return 0.20

        if not effective_date.tzinfo:
            effective_date = effective_date.replace(tzinfo=timezone.utc)

        days_delta = (effective_date - now).total_seconds() / 86400

        if days_delta > 7:      return 0.20   # xa, chưa cần quan tâm
        if days_delta > 3:      return 0.40   # trong tuần — awareness
        if days_delta > 1:      return 0.65   # 2-3 ngày nữa — buildup
        if days_delta > 0:      return 0.85   # ngày mai — sắp có hiệu lực
        if days_delta > -1:     return 1.00   # HÔM NAY có hiệu lực — peak
        if days_delta > -3:     return 0.70   # vừa có hiệu lực — còn tác động
        if days_delta > -7:     return 0.40   # 1 tuần sau — giảm dần
        return 0.10                            # đã cũ

    elif news_type == "monitoring":
        if publish_time is None:
            return 0.40
        age_days = (now - publish_time).total_seconds() / 86400
        if age_days < 1:  return 0.80
        if age_days < 3:  return 0.60
        if age_days < 7:  return 0.40
        return 0.20

    else:
        # Fallback
        if publish_time is None:
            return 0.40
        age_hours = (now - publish_time).total_seconds() / 3600
        if age_hours < 6:   return 0.85
        if age_hours < 24:  return 0.40
        return 0.20


# ─── Sentiment ────────────────────────────────────────────────────────────────

POSITIVE_WORDS = [
    "tăng", "tích cực", "khởi sắc", "hưởng lợi", "cơ hội",
    "tăng trưởng", "vượt kỳ vọng", "lợi nhuận cao", "kỷ lục",
    "bứt phá", "phục hồi", "tốt", "thuận lợi", "tăng mạnh",
    "lạc quan", "triển vọng", "tích lũy", "đột phá",
]

NEGATIVE_WORDS = [
    "giảm", "tiêu cực", "rủi ro", "áp lực", "sụt giảm", "thua lỗ",
    "bị phạt", "điều tra", "nợ xấu", "mất thanh khoản", "cảnh báo",
    "khó khăn", "giảm mạnh", "thất bại", "vi phạm", "bắt giữ",
    "lo ngại", "bất ổn", "suy giảm", "thua lỗ", "vỡ nợ",
]


def _score_sentiment(text: str) -> float:
    t   = text.lower()
    pos = sum(1 for w in POSITIVE_WORDS if w in t)
    neg = sum(1 for w in NEGATIVE_WORDS if w in t)
    return float(pos - neg)


def _score_macro(text: str) -> float:
    t = text.lower()
    return float(sum(
        bias for kw, bias in MACRO_KEYWORDS.items()
        if kw.lower() in t
    ))


def _tag_industries(text: str) -> list[str]:
    t = text.lower()
    return [
        ind for ind, keywords in INDUSTRY_KEYWORDS.items()
        if any(kw.lower() in t for kw in keywords)
    ]


# ─── Crawl một site ───────────────────────────────────────────────────────────

def _crawl_site(site_name: str, source_weight: float) -> list[dict]:
    try:
        from vnstock_news import Crawler
        crawler = Crawler(site_name=site_name)
        raw     = crawler.get_articles_from_feed(limit_per_feed=LIMIT_PER_FEED)

        if not isinstance(raw, list):
            try:
                raw = raw.to_dict("records")
            except Exception:
                raw = []

        enriched = []
        now      = now_ict()

        for art in raw:
            title = art.get("title") or ""
            desc  = art.get("short_description") or ""
            text  = f"{title} {desc}"

            news_type      = _classify_news_type(text)
            effective_date = _extract_effective_date(text) \
                             if news_type == "delayed" else None
            industries     = _tag_industries(text)
            raw_sentiment  = _score_sentiment(text)
            macro_score    = _score_macro(text)

            # Tính decay dựa trên news_type + effective_date
            art_with_meta = {
                "publish_time"  : str(art.get("publish_time", "")),
                "news_type"     : news_type,
                "effective_date": effective_date,
            }
            decay = _impact_decay(art_with_meta, now)

            enriched.append({
                "url"               : art.get("url", ""),
                "title"             : title,
                "short_description" : desc,
                "publish_time"      : str(art.get("publish_time", "")),
                "category"          : art.get("category", ""),
                "tags"              : art.get("tags", ""),
                "source"            : site_name,
                "source_weight"     : source_weight,
                "news_type"         : news_type,
                "effective_date"    : effective_date,
                "matched_industries": industries,
                "raw_sentiment"     : raw_sentiment,
                "macro_score"       : macro_score,
                "time_decay"        : decay,
                "weighted_sentiment": round(
                    raw_sentiment * source_weight * decay, 4),
            })

        tagged = sum(1 for a in enriched if a["matched_industries"])
        log.info(f"  ✅ {site_name}: {len(enriched)} articles, "
                 f"{tagged} tagged, "
                 f"{sum(1 for a in enriched if a['news_type']=='delayed')} delayed")
        return enriched

    except Exception as e:
        log.warning(f"  ⚠️ {site_name} failed: {e}")
        return []


# ─── History management ───────────────────────────────────────────────────────

def _update_history(new_articles: list) -> list:
    """
    Merge bài mới vào history.
    Giữ lại:
      - Bài trong HISTORY_DAYS ngày gần nhất
      - Bài delayed có effective_date chưa quá 3 ngày
    """
    history = load_json("news_history.json") or []
    now     = now_ict()
    cutoff  = now - timedelta(days=HISTORY_DAYS)

    # Merge — dedup theo URL
    existing_urls = {a["url"] for a in history if a.get("url")}
    added = 0
    for art in new_articles:
        if art.get("url") and art["url"] not in existing_urls:
            history.append(art)
            existing_urls.add(art["url"])
            added += 1

    # Prune
    def _should_keep(art: dict) -> bool:
        pub = _parse_time(art.get("publish_time"))
        if pub and pub.replace(tzinfo=timezone.utc) < \
                cutoff.replace(tzinfo=timezone.utc):
            # Bài cũ — chỉ giữ nếu delayed + effective_date còn trong tương lai gần
            if art.get("news_type") == "delayed" and art.get("effective_date"):
                eff = _parse_time(art["effective_date"])
                if eff:
                    days_after = (now - eff).total_seconds() / 86400
                    return days_after <= 3   # giữ đến 3 ngày sau effective
            return False
        return True

    before = len(history)
    history = [a for a in history if _should_keep(a)]
    pruned  = before - len(history)

    log.info(f"  History: +{added} new, -{pruned} pruned, "
             f"{len(history)} total")
    save_json("news_history.json", history)
    return history


# ─── Pre-compute today index ──────────────────────────────────────────────────

def _build_today_index(all_articles: list) -> dict:
    """
    Pre-compute scores theo industry và symbol từ toàn bộ articles
    (today + history). Intraday chỉ đọc file này, không tính lại.

    Output structure:
    {
      "date": "2026-05-23",
      "generated_at": "08:05",
      "by_industry": {
        "Ngân hàng": {
          "score": 7.2,        # 0–4 scale
          "article_count": 5,
          "delayed_count": 2,
          "top_articles": [...]
        }
      },
      "macro": {
        "score": 1.4,          # 0–2 scale
        "top_articles": [...]
      },
      "symbol_mentions": {
        "VCB": {
          "score": 3.8,        # 0–4 scale (trước boost)
          "article_count": 2,
          "top_articles": [...]
        }
      }
    }
    """
    now = now_ict()

    # Recalculate decay với now hiện tại
    for art in all_articles:
        art["time_decay"] = _impact_decay(art, now)
        art["weighted_sentiment"] = round(
            art.get("raw_sentiment", 0)
            * art.get("source_weight", 1.0)
            * art["time_decay"], 4
        )

    def _raw_to_score(values: list[float], max_pts: float) -> float:
        if not values:
            return round(max_pts / 2, 2)
        avg     = sum(values) / len(values)
        clipped = max(-5.0, min(5.0, avg))
        return round((clipped + 5.0) / 10.0 * max_pts, 2)

    def _top_articles(tuples: list[tuple], n: int = 3) -> list[dict]:
        sorted_t  = sorted(tuples, key=lambda x: abs(x[0]), reverse=True)
        seen_urls = set()
        result    = []
        for contrib, art in sorted_t:
            url = art.get("url", "")
            if url in seen_urls:
                continue
            seen_urls.add(url)
            result.append({
                "title"          : (art.get("title") or "")[:80],
                "source"         : art.get("source", ""),
                "time"           : str(art.get("publish_time", ""))[:16],
                "news_type"      : art.get("news_type", "immediate"),
                "effective_date" : art.get("effective_date"),
                "industries"     : art.get("matched_industries", []),
                "contribution"   : round(contrib, 3),
            })
            if len(result) >= n:
                break
        return result

    # ── By industry ──
    industry_tuples: dict[str, list[tuple]] = {}
    for art in all_articles:
        ws = art.get("weighted_sentiment", 0.0)
        for ind in art.get("matched_industries", []):
            industry_tuples.setdefault(ind, []).append((ws, art))

    by_industry = {}
    for ind, tuples in industry_tuples.items():
        vals = [v for v, _ in tuples]
        by_industry[ind] = {
            "score"         : _raw_to_score(vals, 4.0),
            "article_count" : len(tuples),
            "delayed_count" : sum(
                1 for _, a in tuples
                if a.get("news_type") == "delayed"),
            "top_articles"  : _top_articles(tuples, n=3),
        }

    # ── Macro ──
    macro_tuples = [
        (art.get("macro_score", 0) * art.get("time_decay", 0.5), art)
        for art in all_articles
        if art.get("macro_score", 0) != 0
    ]
    macro_vals = [v for v, _ in macro_tuples]

    # ── Symbol mentions ──
    # Lấy tất cả symbols từ industry_map để match
    industry_map = load_json("industry_map.json") or []
    all_symbols  = list({
        r["symbol"] for r in industry_map
        if r.get("symbol")
    })

    symbol_tuples: dict[str, list[tuple]] = {}
    for art in all_articles:
        title = (art.get("title") or "").upper()
        tags  = str(art.get("tags") or "").upper()
        text  = f"{title} {tags}"
        ws    = art.get("weighted_sentiment", 0.0)
        for sym in all_symbols:
            if sym in text:
                symbol_tuples.setdefault(sym, []).append(
                    (ws * 1.5, art))   # boost 1.5×

    symbol_mentions = {}
    for sym, tuples in symbol_tuples.items():
        vals = [v for v, _ in tuples]
        symbol_mentions[sym] = {
            "score"         : _raw_to_score(vals, 4.0),
            "article_count" : len(tuples),
            "top_articles"  : _top_articles(tuples, n=2),
        }

    return {
        "date"            : now.strftime("%Y-%m-%d"),
        "generated_at"    : now.strftime("%H:%M"),
        "by_industry"     : by_industry,
        "macro"           : {
            "score"       : _raw_to_score(macro_vals, 2.0),
            "article_count": len(macro_tuples),
            "top_articles": _top_articles(macro_tuples, n=2),
        },
        "symbol_mentions" : symbol_mentions,
    }


# ─── Entry point ──────────────────────────────────────────────────────────────

def run():
    log.info("=== step_news_daily: START ===")

    # 1. Crawl RSS
    all_articles: list[dict] = []
    for site_name, weight in FINANCE_SITES:
        articles = _crawl_site(site_name, weight)
        all_articles.extend(articles)

    # Dedup theo URL
    seen_urls: set[str] = set()
    deduped = []
    for a in all_articles:
        if a.get("url") and a["url"] not in seen_urls:
            seen_urls.add(a["url"])
            deduped.append(a)

    tagged_count  = sum(1 for a in deduped if a["matched_industries"])
    delayed_count = sum(1 for a in deduped if a["news_type"] == "delayed")
    macro_count   = sum(1 for a in deduped if a["macro_score"] != 0)

    log.info(f"  Today: {len(deduped)} articles "
             f"({tagged_count} industry-tagged, "
             f"{delayed_count} delayed, "
             f"{macro_count} macro-tagged)")

    # 2. Lưu news_raw.json (hôm nay)
    save_json("news_raw.json", deduped)

    # 3. Merge vào history
    history = _update_history(deduped)

    # 4. Merge today + history để pre-compute
    seen   = set()
    merged = []
    for art in deduped + history:
        url = art.get("url", "")
        if url and url not in seen:
            seen.add(url)
            merged.append(art)

    # 5. Pre-compute today index
    log.info("  Building today index...")
    today_index = _build_today_index(merged)
    save_json("news_today_index.json", today_index)

    # Log summary
    n_ind = len(today_index["by_industry"])
    n_sym = len(today_index["symbol_mentions"])
    log.info(f"  Index: {n_ind} industries, {n_sym} symbols mentioned")
    log.info("=== step_news_daily: DONE ===")


if __name__ == "__main__":
    run()
