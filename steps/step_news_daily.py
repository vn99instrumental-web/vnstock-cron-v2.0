"""
step_news_daily.py — Daily news crawl + index builder
=======================================================
CHANGELOG:
  2026-05-25 — Multi-layer RSS fallback (Layer 1 unified + Layer 2 manual)
  2026-05-26 — FIX BUG Macro false positive (MACRO_CONTEXT_INDUSTRIES filter)
  2026-05-26 — FIX BUG #11 Symbol mention matching:
    Báo chí VN dùng "Hòa Phát" thay vì "HPG" → trước đây chỉ 40/3338 = 1.2% match.

    Fix: thêm matching theo organ_name + organ_short_name (từ industry_map.json):
      - Ticker matching (như cũ): "HPG" → HPG
      - Short name matching: "Hòa Phát" → HPG
      - Full name matching: "Tập đoàn Hòa Phát" → HPG (sau khi strip prefix)

    Stop-list để tránh false positives:
      - Names quá ngắn (<4 chars)
      - Names trùng với common Vietnamese words
      - Generic words: "tập đoàn", "công ty"
"""
import os
import re
import sys
import unicodedata
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

os.environ["VNSTOCK_INTERACTIVE"] = "0"
os.environ["VNSTOCK_LANGUAGE"]    = "en"
os.environ["MPLCONFIGDIR"]        = "/home/runner/.config/matplotlib"
os.makedirs("/home/runner/.vnstock",           exist_ok=True)
os.makedirs("/home/runner/.config/matplotlib", exist_ok=True)

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

# ─── Config ──────────────────────────────────────────────────────────────────

FINANCE_SITES = [
    ("baodautu",               1.2),
    ("vietstock",              1.3),
    ("thoibaotaichinhvietnam", 1.1),
    ("cafebiz",                1.0),
    ("znews",                  1.0),
    ("vietnamnet",             1.0),
    ("tuoitre",                1.0),
    ("vnexpress",              1.0),
    ("dantri",                 0.9),
    ("thanhnien",              0.9),
    ("tienphong",              0.9),
    ("nld",                    0.9),
    ("petrotimes",             1.0),
    ("nhandan",                0.8),
]

LIMIT_PER_FEED = 30
HISTORY_DAYS   = 30

_RSS_FALLBACK_URLS = {
    "baodautu": [
        "https://baodautu.vn/rss/tin-moi-nhat.rss",
    ],
    "tienphong": [
        "https://tienphong.vn/rss/kinh-te-3.rss",
        "https://tienphong.vn/rss/tai-chinh-chung-khoan-105.rss",
        "https://tienphong.vn/rss/doanh-nghiep-22.rss",
    ],
}

MACRO_CONTEXT_INDUSTRIES: set[str] = {
    "Ngân hàng", "Bảo hiểm", "Dịch vụ tài chính", "Bất động sản",
    "Sản xuất Dầu khí", "Sản xuất & Phân phối Điện",
    "Kim loại", "Xây dựng và Vật liệu", "Hóa chất",
    "Nguyên vật liệu", "Công nghiệp",
}

# ─── Symbol matching config (Bug #11 fix) ────────────────────────────────────
# Min length cho company name match — quá ngắn dễ false positive
_MIN_NAME_LEN = 4

# Prefixes thường gặp trong organ_name cần strip để được short form
# Order quan trọng: longest prefix first
_COMPANY_PREFIXES = [
    "tổng công ty cổ phần",
    "tổng công ty",
    "công ty cổ phần",
    "công ty tnhh",
    "công ty cp",
    "công ty",
    "tập đoàn",
    "ngân hàng tmcp",
    "ngân hàng cổ phần",
    "ngân hàng",
    "tcty",
    "tct",
    "ctcp",
]

# Stop-list: names trùng với common Vietnamese words / sites
# (sẽ skip nếu sau strip prefix mà thành 1 trong các từ này)
_STOPLIST = {
    "VIỆT NAM", "DỊCH VỤ", "ĐẦU TƯ", "PHÁT TRIỂN", "THƯƠNG MẠI",
    "SẢN XUẤT", "XÂY DỰNG", "KINH DOANH", "VẬN TẢI", "ĐIỆN LỰC",
    "NƯỚC GIẢI KHÁT", "QUẢN LÝ", "TÀI CHÍNH",
}


def _normalize(s: str) -> str:
    """Normalize unicode (NFC) + uppercase + collapse whitespace."""
    if not s:
        return ""
    s = unicodedata.normalize("NFC", str(s))
    s = re.sub(r"\s+", " ", s.strip()).upper()
    return s


def _strip_company_prefix(name: str) -> str:
    """Strip common Vietnamese company prefixes. Returns stripped name."""
    if not name:
        return ""
    norm = name.strip()
    norm_lower = norm.lower()
    for prefix in _COMPANY_PREFIXES:
        if norm_lower.startswith(prefix + " "):
            return norm[len(prefix) + 1:].strip()
        if norm_lower == prefix:
            return ""
    return norm


def _build_company_name_map(industry_map: list) -> dict[str, str]:
    """
    Build name (normalized, uppercase) → symbol mapping.

    Sources:
      1. organ_short_name (nếu có và len ≥ MIN_NAME_LEN)
      2. organ_name strip prefix (nếu có và len ≥ MIN_NAME_LEN)
      3. Skip nếu trong _STOPLIST

    Conflicts: nếu 2 symbols cùng name → ưu tiên 1 cái đầu (deterministic).
    """
    name_to_sym: dict[str, str] = {}
    n_short = n_full = n_skip = 0

    for entry in industry_map:
        sym = entry.get("symbol") or entry.get("ticker") or entry.get("code")
        if not sym:
            continue

        # Try organ_short_name first
        short = (entry.get("organ_short_name") or "").strip()
        if short and len(short) >= _MIN_NAME_LEN:
            short_norm = _normalize(short)
            if short_norm not in _STOPLIST and short_norm not in name_to_sym:
                name_to_sym[short_norm] = sym
                n_short += 1

        # Then organ_name (strip prefix)
        full = (entry.get("organ_name") or "").strip()
        if full:
            stripped = _strip_company_prefix(full)
            if stripped and len(stripped) >= _MIN_NAME_LEN:
                full_norm = _normalize(stripped)
                if (full_norm not in _STOPLIST
                    and full_norm not in name_to_sym
                    and full_norm != _normalize(short)):
                    name_to_sym[full_norm] = sym
                    n_full += 1
                elif full_norm in _STOPLIST:
                    n_skip += 1

    log.info(
        f"  Company name map: {len(name_to_sym)} names "
        f"({n_short} short, {n_full} full prefix-stripped, {n_skip} stoplist-skip)"
    )
    return name_to_sym


# ─── Time helpers ─────────────────────────────────────────────────────────────

def _parse_time(raw) -> datetime | None:
    if raw is None:
        return None
    if isinstance(raw, datetime):
        return raw if raw.tzinfo else raw.replace(tzinfo=timezone.utc)
    for fmt in (
        "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%d %H:%M:%S%z", "%Y-%m-%d",
    ):
        try:
            dt = datetime.strptime(str(raw).strip()[:19], fmt)
            return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


def _classify_news_type(text: str) -> str:
    t = text.lower()
    if any(kw in t for kw in NEWS_TYPE_KEYWORDS["delayed"]):
        return "delayed"
    if any(kw in t for kw in NEWS_TYPE_KEYWORDS["monitoring"]):
        return "monitoring"
    return "immediate"


def _extract_effective_date(text: str) -> str | None:
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
            if "quý" in pattern:
                quarter = int(raw)
                q_year  = int(groups[1]) if len(groups) > 1 else year
                month   = (quarter - 1) * 3 + 1
                return f"{q_year}-{month:02d}-01"
            if "tháng" in pattern:
                month = int(raw)
                y     = int(groups[1]) if len(groups) > 1 else year
                if month < now.month:
                    y = year + 1
                return f"{y}-{month:02d}-01"
            parts = re.split(r"[\/\-]", raw)
            if len(parts) == 2:
                d, mo = int(parts[0]), int(parts[1])
                y = year
                if mo < now.month or (mo == now.month and d < now.day):
                    y = year + 1
                return f"{y}-{mo:02d}-{d:02d}"
            elif len(parts) == 3:
                d, mo, y = int(parts[0]), int(parts[1]), int(parts[2])
                if y < 100: y += 2000
                return f"{y}-{mo:02d}-{d:02d}"
        except (ValueError, IndexError):
            continue
    return None


def _impact_decay(article: dict, now: datetime) -> float:
    news_type      = article.get("news_type", "immediate")
    publish_time   = _parse_time(article.get("publish_time"))
    effective_date = _parse_time(article.get("effective_date"))

    if publish_time and not publish_time.tzinfo:
        publish_time = publish_time.replace(tzinfo=timezone.utc)

    if news_type == "immediate":
        if publish_time is None: return 0.5
        age_hours = (now - publish_time).total_seconds() / 3600
        if age_hours < 0:   return 1.00
        if age_hours < 1:   return 1.00
        if age_hours < 6:   return 0.85
        if age_hours < 12:  return 0.65
        if age_hours < 24:  return 0.40
        return 0.20

    elif news_type == "delayed":
        if effective_date is None:
            if publish_time is None: return 0.40
            age_days = (now - publish_time).total_seconds() / 86400
            if age_days < 1:  return 0.70
            if age_days < 3:  return 0.55
            if age_days < 7:  return 0.40
            return 0.20
        if not effective_date.tzinfo:
            effective_date = effective_date.replace(tzinfo=timezone.utc)
        days_delta = (effective_date - now).total_seconds() / 86400
        if days_delta > 7:   return 0.20
        if days_delta > 3:   return 0.40
        if days_delta > 1:   return 0.65
        if days_delta > 0:   return 0.85
        if days_delta > -1:  return 1.00
        if days_delta > -3:  return 0.70
        if days_delta > -7:  return 0.40
        return 0.10

    elif news_type == "monitoring":
        if publish_time is None: return 0.40
        age_days = (now - publish_time).total_seconds() / 86400
        if age_days < 1:  return 0.80
        if age_days < 3:  return 0.60
        if age_days < 7:  return 0.40
        return 0.20

    if publish_time is None: return 0.40
    age_hours = (now - publish_time).total_seconds() / 3600
    if age_hours < 6:  return 0.85
    if age_hours < 24: return 0.40
    return 0.20


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
    "lo ngại", "bất ổn", "suy giảm", "vỡ nợ",
]


def _score_sentiment(text: str) -> float:
    t   = text.lower()
    pos = sum(1 for w in POSITIVE_WORDS if w in t)
    neg = sum(1 for w in NEGATIVE_WORDS if w in t)
    return float(pos - neg)


def _score_macro(text: str, industries: list | None = None) -> float:
    t = text.lower()
    total = 0.0
    industries_set = set(industries or [])
    has_fin_context = bool(industries_set & MACRO_CONTEXT_INDUSTRIES)

    for kw, bias in MACRO_KEYWORDS.items():
        if kw.lower() in t:
            if bias >= 0:
                total += bias
            elif has_fin_context:
                total += bias
    return float(total)


def _tag_industries(text: str) -> list[str]:
    t = text.lower()
    return [
        ind for ind, keywords in INDUSTRY_KEYWORDS.items()
        if any(kw.lower() in t for kw in keywords)
    ]


def _enrich_article(art: dict, site_name: str, source_weight: float,
                    now: datetime) -> dict:
    title = art.get("title") or ""
    desc  = art.get("short_description") or art.get("description") or \
            art.get("summary") or ""
    text  = f"{title} {desc}"

    news_type      = _classify_news_type(text)
    effective_date = _extract_effective_date(text) \
                     if news_type == "delayed" else None
    industries     = _tag_industries(text)
    raw_sentiment  = _score_sentiment(text)
    macro_score    = _score_macro(text, industries)

    art_meta = {
        "publish_time"  : str(art.get("publish_time", "")),
        "news_type"     : news_type,
        "effective_date": effective_date,
    }
    decay = _impact_decay(art_meta, now)

    url = art.get("url") or art.get("link") or ""

    return {
        "url"               : url,
        "title"             : title,
        "short_description" : desc,
        "publish_time"      : str(art.get("publish_time")
                                  or art.get("pubDate")
                                  or art.get("published") or ""),
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
        "weighted_sentiment": round(raw_sentiment * source_weight * decay, 4),
    }


def _try_unified_crawler(site_name: str) -> list | None:
    try:
        from vnstock_news import Crawler
        crawler = Crawler(site_name=site_name)
        raw = crawler.get_articles(limit=LIMIT_PER_FEED)
        if not isinstance(raw, list):
            try:
                raw = raw.to_dict("records")
            except Exception:
                raw = []
        return raw if raw else None
    except Exception as e:
        log.debug(f"  {site_name}: Layer 1 (unified) error: {e}")
        return None


def _try_manual_rss(site_name: str) -> list | None:
    if site_name not in _RSS_FALLBACK_URLS:
        return None

    try:
        from vnstock_news.core.rss import RSS
    except Exception as e:
        log.warning(f"  {site_name}: Layer 2 import RSS failed: {e}")
        return None

    for rss_url in _RSS_FALLBACK_URLS[site_name]:
        try:
            rss = RSS(rss_url=rss_url, description_format='text')
            items = rss.fetch()
            if items and isinstance(items, list) and len(items) > 0:
                log.info(f"  {site_name}: Layer 2 RSS {rss_url} returned "
                         f"{len(items)} items")
                return items
        except Exception as e:
            log.debug(f"  {site_name}: RSS {rss_url} failed: {e}")
            continue

    return None


def _crawl_site(site_name: str, source_weight: float) -> list[dict]:
    raw_articles = None
    layer_used   = None

    raw_articles = _try_unified_crawler(site_name)
    if raw_articles:
        layer_used = "L1 unified"

    if not raw_articles:
        raw_articles = _try_manual_rss(site_name)
        if raw_articles:
            layer_used = "L2 manual RSS"

    if not raw_articles:
        log.warning(f"  ⚠️ {site_name} failed: all layers exhausted "
                    f"(check RSS config or update vnstock_news)")
        return []

    enriched = []
    now      = now_ict()
    for art in raw_articles[:LIMIT_PER_FEED]:
        if not isinstance(art, dict):
            continue
        try:
            enriched.append(_enrich_article(art, site_name, source_weight, now))
        except Exception as e:
            log.debug(f"  {site_name}: enrich article failed: {e}")
            continue

    tagged  = sum(1 for a in enriched if a["matched_industries"])
    delayed = sum(1 for a in enriched if a["news_type"] == "delayed")
    log.info(f"  ✅ {site_name} ({layer_used}): {len(enriched)} articles, "
             f"{tagged} tagged, {delayed} delayed")
    return enriched


def _update_history(new_articles: list) -> list:
    history = load_json("news/history.json") or \
              load_json("news_history.json") or []
    now     = now_ict()
    cutoff  = now - timedelta(days=HISTORY_DAYS)

    existing_urls = {a["url"] for a in history if a.get("url")}
    added = 0
    for art in new_articles:
        if art.get("url") and art["url"] not in existing_urls:
            history.append(art)
            existing_urls.add(art["url"])
            added += 1

    def _should_keep(art: dict) -> bool:
        pub = _parse_time(art.get("publish_time"))
        if pub and pub.replace(tzinfo=timezone.utc) < \
                cutoff.replace(tzinfo=timezone.utc):
            if art.get("news_type") == "delayed" and art.get("effective_date"):
                eff = _parse_time(art["effective_date"])
                if eff:
                    days_after = (now - eff).total_seconds() / 86400
                    return days_after <= 3
            return False
        return True

    before  = len(history)
    history = [a for a in history if _should_keep(a)]
    pruned  = before - len(history)

    log.info(f"  History: +{added} new, -{pruned} pruned, {len(history)} total")

    save_json("news/history.json",    history)
    save_json("news_history.json",    history)
    return history


def _build_today_index(all_articles: list) -> dict:
    """
    Pre-compute scores by industry, symbol, macro.

    v2 (Bug #9 fix): Recompute macro_score with tighter industry filter
    v3 (Bug #11 fix): Match symbol_mentions by ticker + organ_name + organ_short_name
    """
    now = now_ict()

    # Recompute macro_score với filter mới (cho cả articles cũ từ history)
    for art in all_articles:
        art["macro_score"] = _score_macro(
            f"{art.get('title','')} {art.get('short_description','')}",
            art.get("matched_industries", [])
        )
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
                "title"         : (art.get("title") or "")[:80],
                "source"        : art.get("source", ""),
                "time"          : str(art.get("publish_time", ""))[:16],
                "news_type"     : art.get("news_type", "immediate"),
                "effective_date": art.get("effective_date"),
                "industries"    : art.get("matched_industries", []),
                "contribution"  : round(contrib, 3),
            })
            if len(result) >= n:
                break
        return result

    # By industry
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
            "delayed_count" : sum(1 for _, a in tuples if a.get("news_type") == "delayed"),
            "top_articles"  : _top_articles(tuples, n=3),
        }

    # Macro
    macro_tuples = [
        (art.get("macro_score", 0) * art.get("time_decay", 0.5), art)
        for art in all_articles
        if art.get("macro_score", 0) != 0
    ]
    macro_vals = [v for v, _ in macro_tuples]

    log.info(f"  Macro: {len(macro_tuples)} articles tagged "
             f"(after MACRO_CONTEXT filter)")

    # ── Symbol mentions (v3 Bug #11: ticker + company name matching) ──
    industry_map = load_json("market/industry_map.json") or \
                   load_json("industry_map.json") or []

    # Universe of all tickers
    all_symbols = list({
        r.get("symbol") or r.get("ticker") or r.get("code")
        for r in industry_map
        if r.get("symbol") or r.get("ticker") or r.get("code")
    })
    log.info(f"  Symbol universe: {len(all_symbols)} tickers")

    # Ticker patterns (word boundary)
    ticker_patterns = {
        sym: re.compile(r'\b' + re.escape(sym) + r'\b', re.UNICODE)
        for sym in all_symbols
    }

    # v3: Build company name → symbol map
    name_to_sym = _build_company_name_map(industry_map)

    symbol_tuples: dict[str, list[tuple]] = {}
    n_via_ticker = 0
    n_via_name   = 0

    for art in all_articles:
        # Match against title + tags + short_description
        title = (art.get("title") or "")
        desc  = (art.get("short_description") or "")
        tags  = str(art.get("tags") or "")
        text_normalized = _normalize(f"{title} {desc} {tags}")
        ws = art.get("weighted_sentiment", 0.0)

        # Match symbols hit per article (avoid double-count)
        matched_syms = set()

        # 1. Ticker matching
        # Use original text (not normalized) for ticker — case-sensitive in regex
        text_for_ticker = f"{title.upper()} {tags.upper()} {desc.upper()}"
        for sym, pattern in ticker_patterns.items():
            if pattern.search(text_for_ticker):
                if sym not in matched_syms:
                    matched_syms.add(sym)
                    symbol_tuples.setdefault(sym, []).append((ws * 1.5, art))
                    n_via_ticker += 1

        # 2. Company name matching (substring with unicode normalization)
        for name, sym in name_to_sym.items():
            if sym in matched_syms:
                continue  # Already matched via ticker
            if name in text_normalized:
                matched_syms.add(sym)
                # Lower confidence weight (1.2x) cho name match vs ticker (1.5x)
                symbol_tuples.setdefault(sym, []).append((ws * 1.2, art))
                n_via_name += 1

    symbol_mentions: dict[str, dict] = {}
    for sym, tuples in symbol_tuples.items():
        vals = [v for v, _ in tuples]
        symbol_mentions[sym] = {
            "score"         : _raw_to_score(vals, 4.0),
            "article_count" : len(tuples),
            "top_articles"  : _top_articles(tuples, n=2),
        }

    log.info(
        f"  symbol_mentions: {len(symbol_mentions)} symbols matched "
        f"({n_via_ticker} hits via ticker, {n_via_name} hits via company name)"
    )

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


def _log_vnstock_news_version():
    try:
        import vnstock_news
        version = getattr(vnstock_news, "__version__", None) or \
                  getattr(vnstock_news, "VERSION", None) or \
                  "unknown"
        log.info(f"  vnstock_news version: {version}")
        if version != "unknown" and isinstance(version, str):
            try:
                major, minor = map(int, version.split(".")[:2])
                if (major, minor) < (2, 2):
                    log.warning(
                        f"  ⚠️ vnstock_news {version} is older than v2.2.0 — "
                        f"baodautu/tienphong/nhandan RSS có thể fail. "
                        f"Consider upgrading."
                    )
            except (ValueError, AttributeError):
                pass
    except Exception as e:
        log.debug(f"  Could not detect vnstock_news version: {e}")


def run():
    log.info("=== step_news_daily: START ===")
    _log_vnstock_news_version()

    all_articles: list[dict] = []
    for site_name, weight in FINANCE_SITES:
        articles = _crawl_site(site_name, weight)
        all_articles.extend(articles)

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

    save_json("news/raw.json",   deduped)
    save_json("news_raw.json",   deduped)

    history = _update_history(deduped)

    seen   = set()
    merged = []
    for art in deduped + history:
        url = art.get("url", "")
        if url and url not in seen:
            seen.add(url)
            merged.append(art)

    log.info("  Building today index...")
    today_index = _build_today_index(merged)

    save_json("news/today_index.json", today_index)
    save_json("news_today_index.json", today_index)

    n_ind = len(today_index["by_industry"])
    n_sym = len(today_index["symbol_mentions"])
    log.info(f"  Index: {n_ind} industries, {n_sym} symbols mentioned")
    log.info("=== step_news_daily: DONE ===")


if __name__ == "__main__":
    run()
