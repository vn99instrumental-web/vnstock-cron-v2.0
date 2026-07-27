"""
step_news_daily.py — Daily news crawl + index builder
=======================================================
CHANGELOG:
  2026-05-25 — Multi-layer RSS fallback (Layer 1 unified + Layer 2 manual)
  2026-05-26 — FIX BUG Macro false positive (MACRO_CONTEXT_INDUSTRIES filter)
  2026-05-26 — FIX BUG #11 Symbol mention matching (ticker + organ names + stoplist)
  2026-07-19 — NEWS RESTART v2 (Gói 1 + 2a + Gói 3):
    1. SENTIMENT: bỏ đếm từ đơn (POSITIVE_WORDS/NEGATIVE_WORDS) → dùng
       utils/news_sentiment.py: cụm từ có chủ thể + hướng (3 mức ±1/±2/±3),
       xử lý phủ định, gap-matching "chủ thể ... hướng" (≤40 ký tự).
       Test offline: scripts/test_news_sentiment.py (28/28 pass 2026-07-19).
       raw_sentiment mới ∈ [-3, +3] (cũ: đếm từ, không chặn biên).
    2. UNIVERSE: symbol matching CHỈ trong universe V2F (~130 mã VN100+HNX30)
       thay vì 3.338 mã toàn thị trường. Nguồn: v2f_ranking.json (không tốn
       API call) → fallback v2f_universe API → fallback all (log warning).
    3. RELEVANCE FILTER: bài không match gì (không ngành, không macro,
       không nhắc mã universe) → loại khỏi history + index. raw.json vẫn
       giữ đủ để debug.
    4. ĐIỂM MỚI (schema 2): biên độ thành phần symbol ±3 / industry ±1.5 /
       macro ±0.5 (tổng đúng ±5). GIỮ NGUYÊN contract encode với consumer
       (build_news_scores trong v2f_step_scoring.py): file lưu điểm quanh
       mốc symbol/industry=2.0, macro=1.0; consumer trừ mốc để ra điểm
       đối xứng. → KHÔNG cần sửa consumer, KHÔNG bump SCORING_VERSION.
       Điểm thành phần = mean(weighted_sentiment) clamp biên độ — 1 bài
       mạnh nhắc đích danh mã đủ đẩy component symbol ra gần biên (hết
       cảnh điểm co cụm quanh 0 do lớp quy đổi 0-4 cũ).
    5. Recompute raw_sentiment bằng engine MỚI cho cả bài cũ trong history
       khi build index (đồng nhất thang điểm).
    6. METRICS mỗi run: % bài có mô tả, % universe được nhắc, phân phối
       điểm symbol, top bài ±.
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
from utils import news_rss                              # [RSS] đọc RSS thay vnstock_news
from utils.news_sources import SOURCES as _RSS_SOURCES  # [RSS] 5 nguồn RSS
from utils.news_sentiment import score_sentiment
from utils.news_tagging import build_context, aggregate, TICKER_BOOST
from utils.sector_topics import TOPIC_DECAY
from utils.sector_map import sector_name
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

# [RSS] Nguồn tin = RSS THUẦN (utils/news_sources.py). ĐÃ BỎ HẲN vnstock_news.
#       Thêm/bớt nguồn → sửa utils/news_sources.py, KHÔNG sửa file này.
FINANCE_SITES  = [(s["name"], s["weight"]) for s in _RSS_SOURCES]
_FEEDS_BY_NAME = {s["name"]: s["feeds"] for s in _RSS_SOURCES}
_MAX_BODY_FETCH   = 60      # trần fetch body/lần run (bài RSS mô tả rỗng)
_body_fetch_count = [0]     # đếm dùng chung trong 1 lần run (reset đầu run())

LIMIT_PER_FEED = 30
HISTORY_DAYS   = 30

# Biên độ thành phần điểm news (schema 2) — tổng = ±5
SYM_CAP = 3.0    # tin nhắc đích danh mã = tín hiệu mạnh nhất
IND_CAP = 1.5
MAC_CAP = 0.5

# Mốc encode giữ contract với build_news_scores (consumer trừ mốc)
SYM_CENTER = 2.0
IND_CENTER = 2.0
MAC_CENTER = 1.0

# Mô tả ≥ ngưỡng này mới tính là "có mô tả" (metrics)
_DESC_MIN_LEN = 30

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
_MIN_NAME_LEN = 4

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


def _build_company_name_map(industry_map: list,
                            universe: set[str] | None = None) -> dict[str, str]:
    """
    Build name (normalized, uppercase) → symbol mapping.

    v2 (2026-07-19): nếu universe được cung cấp → CHỈ build cho mã trong
    universe (giảm false positive từ ~3.300 tên công ty ngoài rổ trade).

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
        if universe and sym not in universe:
            continue

        short = (entry.get("organ_short_name") or "").strip()
        if short and len(short) >= _MIN_NAME_LEN:
            short_norm = _normalize(short)
            if short_norm not in _STOPLIST and short_norm not in name_to_sym:
                name_to_sym[short_norm] = sym
                n_short += 1

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


# ─── Universe (2026-07-19) ───────────────────────────────────────────────────

def _load_universe() -> set[str]:
    """
    Universe V2F (~130 mã VN100+HNX30) cho symbol matching.

    Chain (rẻ → đắt):
      1. output/v2f_ranking.json — commit từ intraday run gần nhất, 0 API call
      2. utils/v2f_universe.fetch_index_members — VCI API (throttled)
      3. set() rỗng → caller fallback match toàn bộ industry_map (hành vi cũ)
    """
    # 1. v2f_ranking.json
    rank = load_json("v2f_ranking.json") or []
    syms = {
        str(r.get("symbol", "")).strip().upper()
        for r in rank if isinstance(r, dict) and r.get("symbol")
    }
    syms.discard("")
    if len(syms) >= 50:
        log.info(f"  Universe: {len(syms)} mã từ v2f_ranking.json")
        return syms

    # 2. API fallback
    try:
        from utils.v2f_universe import fetch_index_members, INDEX_GROUPS
        api_syms: set[str] = set()
        for grp in INDEX_GROUPS:
            api_syms.update(fetch_index_members(grp))
        api_syms.discard("")
        if api_syms:
            log.info(f"  Universe: {len(api_syms)} mã từ v2f_universe API "
                     f"({'+'.join(INDEX_GROUPS)})")
            return api_syms
    except Exception as e:
        log.warning(f"  Universe API fallback lỗi: {e}")

    log.warning("  ⚠️ Không load được universe — fallback match TOÀN BỘ "
                "industry_map (hành vi cũ, nhiều false positive hơn)")
    return set()


def _match_symbols(art: dict,
                   ticker_patterns: dict[str, re.Pattern],
                   name_to_sym: dict[str, str],
                   name_patterns: dict[str, re.Pattern]) -> tuple[set, set]:
    """
    Trả (via_ticker, via_name) — set mã match trong 1 bài.
    Ticker: word-boundary trên text UPPER gốc.
    Name  : word-boundary trên text đã _normalize.
    """
    title = (art.get("title") or "")
    desc  = (art.get("short_description") or "")
    tags  = str(art.get("tags") or "")

    via_ticker: set[str] = set()
    via_name:   set[str] = set()

    text_for_ticker = f"{title.upper()} {tags.upper()} {desc.upper()}"
    for sym, pattern in ticker_patterns.items():
        if pattern.search(text_for_ticker):
            via_ticker.add(sym)

    text_normalized = _normalize(f"{title} {desc} {tags}")
    for name, pattern in name_patterns.items():
        if pattern.search(text_normalized):
            sym = name_to_sym[name]
            if sym not in via_ticker:
                via_name.add(sym)

    return via_ticker, via_name


# ─── Time helpers ─────────────────────────────────────────────────────────────

def _parse_time(raw) -> datetime | None:
    """
    v3 FIX (2026-07-19, log run 80408946108): RSS pubDate dạng RFC 2822
    ("Sun, 19 Jul 2026 10:30:00 +0700") KHÔNG parse được bằng strptime cũ
    → decay luôn rơi về fallback 0.5, history không prune được theo tuổi.
    Thêm layer RFC 2822 + ISO 8601 đầy đủ trước strptime legacy.
    """
    if raw is None:
        return None
    if isinstance(raw, datetime):
        return raw if raw.tzinfo else raw.replace(tzinfo=timezone.utc)

    s = str(raw).strip()
    if not s or s.lower() in ("none", "nat", "nan"):
        return None

    # 1. RFC 2822 (RSS pubDate): "Sun, 19 Jul 2026 10:30:00 +0700"
    try:
        from email.utils import parsedate_to_datetime
        dt = parsedate_to_datetime(s)
        if dt is not None:
            return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        pass

    # 2. ISO 8601 đầy đủ (kể cả offset / 'Z'): "2026-07-19T10:30:00+07:00"
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except ValueError:
        pass

    # 3. Legacy strptime (cắt [:19] — mất offset, coi như UTC)
    for fmt in (
        "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%d %H:%M:%S%z", "%Y-%m-%d",
    ):
        try:
            dt = datetime.strptime(s[:19], fmt)
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
                if y < 100:
                    y += 2000
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
        if publish_time is None:
            return 0.5
        age_hours = (now - publish_time).total_seconds() / 3600
        if age_hours < 0:   return 1.00
        if age_hours < 1:   return 1.00
        if age_hours < 6:   return 0.85
        if age_hours < 12:  return 0.65
        if age_hours < 24:  return 0.40
        return 0.20

    elif news_type == "delayed":
        if effective_date is None:
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
        if days_delta > 7:   return 0.20
        if days_delta > 3:   return 0.40
        if days_delta > 1:   return 0.65
        if days_delta > 0:   return 0.85
        if days_delta > -1:  return 1.00
        if days_delta > -3:  return 0.70
        if days_delta > -7:  return 0.40
        return 0.10

    elif news_type == "monitoring":
        if publish_time is None:
            return 0.40
        age_days = (now - publish_time).total_seconds() / 86400
        if age_days < 1:  return 0.80
        if age_days < 3:  return 0.60
        if age_days < 7:  return 0.40
        return 0.20

    if publish_time is None:
        return 0.40
    age_hours = (now - publish_time).total_seconds() / 3600
    if age_hours < 6:  return 0.85
    if age_hours < 24: return 0.40
    return 0.20


# ─── Sentiment / tagging (v2: engine mới) ────────────────────────────────────

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
    raw_sentiment  = score_sentiment(text)          # v2: engine cụm từ mới
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


# ─── Crawl layer (RSS-only) ──────────────────────────────────────────────────

def _crawl_site(site_name: str, source_weight: float) -> list[dict]:
    """Crawl 1 nguồn qua RSS (bỏ hẳn vnstock_news). Trả bài ĐÃ enrich."""
    feeds = _FEEDS_BY_NAME.get(site_name, [])
    if not feeds:
        log.warning(f"  ⚠️ {site_name}: không có feed RSS khai báo")
        return []

    now = now_ict()
    enriched = []
    for url in feeds:
        for raw in news_rss.fetch_feed(url, site_name, LIMIT_PER_FEED):
            # mô tả rỗng → fetch body (có trần _MAX_BODY_FETCH cho cả run)
            if news_rss.needs_body(raw.get("short_description", "")):
                if _body_fetch_count[0] < _MAX_BODY_FETCH:
                    body = news_rss.fetch_body(raw.get("url", ""))
                    if body:
                        raw["short_description"] = body
                        _body_fetch_count[0] += 1
            try:
                enriched.append(_enrich_article(raw, site_name, source_weight, now))
            except Exception as e:
                log.debug(f"  {site_name}: enrich fail: {e}")

    tagged  = sum(1 for a in enriched if a["matched_industries"])
    delayed = sum(1 for a in enriched if a["news_type"] == "delayed")
    log.info(f"  ✅ {site_name} (RSS): {len(enriched)} bài, "
             f"{tagged} tagged, {delayed} delayed")
    return enriched


# ─── History ─────────────────────────────────────────────────────────────────

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
        # v2 FIX (2026-07-19, log run 80408379183): bài không parse được
        # publish_time bị giữ VĨNH VIỄN → history phình 12.290 bài legacy,
        # pha loãng mọi điểm về 0. Không rõ tuổi → loại (bài mới của hôm
        # nay vẫn vào index qua danh sách `kept`, không mất tín hiệu).
        if pub is None:
            return False
        if pub.replace(tzinfo=timezone.utc) < \
                cutoff.replace(tzinfo=timezone.utc):
            if art.get("news_type") == "delayed" and art.get("effective_date"):
                eff = _parse_time(art["effective_date"])
                if eff:
                    days_after = (now - eff).total_seconds() / 86400
                    # v5 FIX: chặn 2 đầu — điều kiện cũ (days_after <= 3)
                    # vô tình giữ VĨNH VIỄN bài có effective_date xa trong
                    # tương lai (days_after âm sâu vẫn <= 3). Chỉ giữ bài
                    # sắp hiệu lực trong 7 ngày hoặc vừa hiệu lực ≤ 3 ngày.
                    return -7 <= days_after <= 3
            return False
        return True

    before  = len(history)
    history = [a for a in history if _should_keep(a)]
    pruned  = before - len(history)

    log.info(f"  History: +{added} new, -{pruned} pruned, {len(history)} total")

    save_json("news/history.json",    history)
    save_json("news_history.json",    history)
    return history


# ─── Index (schema 2) ────────────────────────────────────────────────────────

# Cửa sổ bài được vào index (ngày). Decay đã giảm trọng số bài cũ nhưng
# KHÔNG chống được pha loãng mean() khi số bài cũ áp đảo → cần cắt cứng.
INDEX_WINDOW_DAYS = 7


def _is_index_fresh(art: dict, now: datetime, today_urls: set[str]) -> bool:
    """
    v2 FIX (2026-07-19): chỉ đưa vào index bài thỏa 1 trong 3:
      1. Nằm trong batch crawl HÔM NAY (kể cả publish_time lỗi)
      2. publish_time parse được và ≤ INDEX_WINDOW_DAYS ngày
      3. news_type=delayed có effective_date trong ±INDEX_WINDOW_DAYS
         (văn bản ban hành lâu nhưng sắp/vừa hiệu lực vẫn có giá trị)
    """
    if art.get("url", "") in today_urls:
        return True

    if art.get("news_type") == "delayed" and art.get("effective_date"):
        eff = _parse_time(art.get("effective_date"))
        if eff:
            delta_days = abs((eff.replace(tzinfo=timezone.utc)
                              - now.replace(tzinfo=timezone.utc)
                              ).total_seconds()) / 86400
            if delta_days <= INDEX_WINDOW_DAYS:
                return True

    pub = _parse_time(art.get("publish_time"))
    if pub is None:
        return False
    age_days = (now.replace(tzinfo=timezone.utc)
                - pub.replace(tzinfo=timezone.utc)).total_seconds() / 86400
    return age_days <= INDEX_WINDOW_DAYS


def _build_today_index(all_articles: list, ctx: dict) -> dict:
    """
    SCHEMA 3 (2026-07-24) — Phương án 3 qua utils/news_tagging.

    THAY ĐỔI so với schema 2:
      - symbol_mentions tính từ news_tagging.aggregate(): gồm điểm ĐÍCH DANH
        (ticker ×1.5 / tên công ty ×1.0) + điểm CHỦ ĐỀ nhóm hẹp (×0.6).
        → mã không nhắc tên vẫn nhận điểm nếu bài khớp từ khóa chủ đề ngành
          hẹp (VD tin "kim cương" → PNJ).
      - by_industry GIỮ TRUNG TÍNH (mọi ngành = IND_CENTER) → consumer đọc
        ra 0. Điểm ngành ICB cũ đã bỏ: news_score giờ CHỈ phản ánh tin về
        chính mã, không "ăn ké" điểm ngành (chốt 24/07).
      - macro GIỮ TRUNG TÍNH (= MAC_CENTER) → consumer đọc ra 0. Macro là
        hằng số cắt ngang, vô dụng cho xếp hạng mã (bằng chứng what-if 24/07:
        100% flip decision đến từ hằng số macro, 0% từ tin thật).
      - THÊM sector_heat: nhiệt độ 5 nhóm ngành RỘNG (nhánh song song, CHƯA
        nối scoring — để sẵn cho dashboard).

    Contract encode symbol_mentions GIỮ NGUYÊN: score = SYM_CENTER + clamp(
    aggregate, ±SYM_CAP) → consumer build_news_scores không đổi, KHÔNG bump
    SCORING_VERSION.

    Recompute sentiment + decay bằng engine mới cho MỌI bài (đồng nhất thang).
    """
    now = now_ict()

    for art in all_articles:
        text = f"{art.get('title','')} {art.get('short_description','')}"
        art["raw_sentiment"] = score_sentiment(text)
        art["time_decay"]    = _impact_decay(art, now)
        # weighted_sentiment vẫn giữ để metrics/top articles dùng
        art["weighted_sentiment"] = round(
            art["raw_sentiment"] * art.get("source_weight", 1.0)
            * art["time_decay"], 4)

    # ── Định tuyến + gộp qua news_tagging ──
    agg = aggregate(all_articles, ctx)
    sym_scores   = agg["symbol_score"]       # {sym: điểm thô đã gộp mean}
    sym_articles = agg["symbol_articles"]    # {sym: [{title,source,val,kind}]}
    heat_raw     = agg["sector_heat"]        # {sector: {score, n}}

    n_direct = sum(1 for arts in sym_articles.values()
                   for a in arts if a["kind"] == "direct")
    n_topic  = sum(1 for arts in sym_articles.values()
                   for a in arts if a["kind"] == "topic")
    log.info(f"  Tagging: {len(sym_scores)} mã có điểm "
             f"({n_direct} lượt đích danh, {n_topic} lượt chủ đề ×{TOPIC_DECAY})")

    def _clamp_center(raw: float, center: float, cap: float) -> float:
        return round(center + max(-cap, min(cap, raw)), 2)

    # ── symbol_mentions (schema 3) ──
    symbol_mentions = {}
    for sym, raw in sym_scores.items():
        arts = sym_articles.get(sym, [])
        kinds = {a["kind"] for a in arts}
        top = sorted(arts, key=lambda a: abs(a["val"]), reverse=True)[:3]
        symbol_mentions[sym] = {
            "score"        : _clamp_center(raw, SYM_CENTER, SYM_CAP),
            "article_count": len(arts),
            "match_kind"   : "direct" if "direct" in kinds
                             else ("topic" if "topic" in kinds else "none"),
            "top_articles" : [
                {"title": a["title"], "source": a["source"],
                 "url": a.get("url", ""),
                 "contribution": round(a["val"], 3), "kind": a["kind"]}
                for a in top
            ],
        }

    # ── by_industry TRUNG TÍNH (điểm ngành ICB bỏ khỏi news_score) ──
    by_industry: dict[str, dict] = {}

    # ── macro TRUNG TÍNH (hằng số cắt ngang bỏ khỏi news_score) ──
    macro = {"score": round(MAC_CENTER, 2), "article_count": 0, "top_articles": []}

    # ── sector_heat: nhiệt độ nhóm RỘNG (song song, chưa nối scoring) ──
    sector_heat = {}
    for sector, d in heat_raw.items():
        sector_heat[sector] = {
            "name" : sector_name(sector),
            "score": round(d["score"], 3),   # điểm thô (chưa encode), để hiển thị
            "n"    : d["n"],
        }
    if sector_heat:
        hot = sorted(sector_heat.items(), key=lambda kv: abs(kv[1]["score"]),
                     reverse=True)[:3]
        log.info("  Sector heat (nhóm rộng): "
                 + " | ".join(f"{v['name']} {v['score']:+.2f}({v['n']})"
                              for _, v in hot))

    return {
        "schema"         : 3,
        "generated_at"   : now.strftime("%Y-%m-%d %H:%M:%S"),
        "by_industry"    : by_industry,     # rỗng → consumer đọc ra 0
        "symbol_mentions": symbol_mentions,
        "macro"          : macro,           # trung tính → consumer đọc ra 0
        "sector_heat"    : sector_heat,     # MỚI, chưa nối scoring
    }


# ─── Metrics (v2) ────────────────────────────────────────────────────────────

def _log_metrics(deduped: list, kept: list, today_index: dict,
                 universe: set[str]) -> None:
    n_all  = len(deduped)
    n_desc = sum(1 for a in deduped
                 if len(a.get("short_description") or "") >= _DESC_MIN_LEN)
    log.info("  ── METRICS ──────────────────────────────────")
    log.info(f"  Articles: {n_all} crawled, "
             f"{n_desc} có mô tả ≥{_DESC_MIN_LEN} ký tự "
             f"({(n_desc / n_all * 100) if n_all else 0:.0f}%)")
    log.info(f"  Relevance filter: giữ {len(kept)}/{n_all} "
             f"({(len(kept) / n_all * 100) if n_all else 0:.0f}%)")

    mentions = today_index.get("symbol_mentions", {})
    if universe:
        log.info(f"  Universe coverage: {len(mentions)}/{len(universe)} mã "
                 f"được nhắc ({len(mentions) / len(universe) * 100:.0f}%)")
    else:
        log.info(f"  Symbols mentioned: {len(mentions)} (universe unavailable)")

    comps = [round(d.get("score", SYM_CENTER) - SYM_CENTER, 2)
             for d in mentions.values()]
    n_pos  = sum(1 for c in comps if c >= 0.5)
    n_neg  = sum(1 for c in comps if c <= -0.5)
    n_spos = sum(1 for c in comps if c >= 1.5)
    n_sneg = sum(1 for c in comps if c <= -1.5)
    log.info(f"  Symbol comp distribution: {n_pos} pos (≥+0.5, trong đó "
             f"{n_spos} ≥+1.5) | {n_neg} neg (≤-0.5, trong đó {n_sneg} ≤-1.5) "
             f"| {len(comps) - n_pos - n_neg} neutral")

    ranked = sorted(deduped, key=lambda a: a.get("weighted_sentiment", 0.0))
    for art in ranked[-3:][::-1]:
        if art.get("weighted_sentiment", 0) > 0:
            log.info(f"  TOP+ {art['weighted_sentiment']:+.2f} "
                     f"[{art.get('source','')}] {(art.get('title') or '')[:70]}")
    for art in ranked[:3]:
        if art.get("weighted_sentiment", 0) < 0:
            log.info(f"  TOP- {art['weighted_sentiment']:+.2f} "
                     f"[{art.get('source','')}] {(art.get('title') or '')[:70]}")
    log.info("  ─────────────────────────────────────────────")


# ─── Version check ───────────────────────────────────────────────────────────

def _log_vnstock_news_version():
    try:
        import vnstock_news
        version = getattr(vnstock_news, "__version__", None)
        if version is None:
            try:
                from importlib.metadata import version as _v
                version = _v("vnstock_news")
            except Exception:
                version = "unknown"
        log.info(f"  vnstock_news version: {version}")
        if version not in (None, "unknown"):
            try:
                major, minor = map(int, str(version).split(".")[:2])
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


# ─── Main ────────────────────────────────────────────────────────────────────

def run():
    log.info("=== step_news_daily: START (RSS-only crawl) ===")
    _body_fetch_count[0] = 0          # [RSS] reset đếm fetch body mỗi run

    # 1. Crawl
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

    # raw.json giữ TẤT CẢ bài (kể cả bị filter) để debug
    save_json("news/raw.json", deduped)
    save_json("news_raw.json", deduped)

    # 2. Universe + matching maps (build 1 lần, dùng cho filter + index)
    universe     = _load_universe()
    industry_map = load_json("market/industry_map.json") or \
                   load_json("industry_map.json") or []

    if universe:
        match_symbols_set = universe
    else:
        match_symbols_set = {
            r.get("symbol") or r.get("ticker") or r.get("code")
            for r in industry_map
            if r.get("symbol") or r.get("ticker") or r.get("code")
        }
    log.info(f"  Symbol matching scope: {len(match_symbols_set)} tickers")

    ticker_patterns = {
        sym: re.compile(r'\b' + re.escape(sym) + r'\b', re.UNICODE)
        for sym in match_symbols_set
    }
    name_to_sym = _build_company_name_map(
        industry_map, universe=match_symbols_set)
    name_patterns = {
        name: re.compile(r'\b' + re.escape(name) + r'\b', re.UNICODE)
        for name in name_to_sym
    }

    # Context cho news_tagging (schema 3) — build 1 lần, dùng cho index
    tag_ctx = build_context(match_symbols_set, industry_map)

    # 3. Relevance filter (2026-07-19; +topic 2026-07-24): bài không liên
    #    quan gì → loại khỏi history + index (raw.json vẫn giữ đủ). Giữ nếu:
    #    (a) có ngành ICB / macro (cũ), (b) nhắc mã universe, HOẶC
    #    (c) khớp từ khóa CHỦ ĐỀ/nhiệt độ ngành (news_tagging) — để tin kiểu
    #        "kim cương" (không nhắc PNJ, không tag ICB) vẫn sống.
    from utils.sector_topics import SECTOR_TOPICS, SECTOR_HEAT_KEYWORDS
    _all_topic_phrases = [p for ps in SECTOR_TOPICS.values() for p in ps] + \
                         [p for ps in SECTOR_HEAT_KEYWORDS.values() for p in ps]

    def _matches_topic(art: dict) -> bool:
        t = f"{art.get('title','')} {art.get('short_description','')} " \
            f"{art.get('tags','')}".lower()
        return any(p in t for p in _all_topic_phrases)

    kept = []
    for art in deduped:
        if art["matched_industries"] or art["macro_score"] != 0:
            kept.append(art)
            continue
        via_ticker, via_name = _match_symbols(
            art, ticker_patterns, name_to_sym, name_patterns)
        if via_ticker or via_name or _matches_topic(art):
            kept.append(art)
    log.info(f"  Relevance filter: giữ {len(kept)}/{len(deduped)} bài")

    # 4. History (chỉ bài relevant)
    history = _update_history(kept)

    seen   = set()
    merged = []
    for art in kept + history:
        url = art.get("url", "")
        if url and url not in seen:
            seen.add(url)
            merged.append(art)

    # 4b. Freshness window (2026-07-19): chặn pha loãng mean() bởi bài cũ
    now_run    = now_ict()
    today_urls = {a.get("url", "") for a in kept if a.get("url")}
    n_before   = len(merged)
    merged     = [a for a in merged
                  if _is_index_fresh(a, now_run, today_urls)]
    log.info(f"  Freshness window ≤{INDEX_WINDOW_DAYS}d: "
             f"giữ {len(merged)}/{n_before} bài cho index")

    # 5. Index (schema 3 — news_tagging / Phương án 3)
    log.info("  Building today index (schema 3, news_tagging)...")
    today_index = _build_today_index(merged, tag_ctx)

    save_json("news/today_index.json", today_index)
    save_json("news_today_index.json", today_index)

    n_sym  = len(today_index["symbol_mentions"])
    n_heat = len(today_index.get("sector_heat", {}))
    log.info(f"  Index: {n_sym} mã có điểm, {n_heat} nhóm ngành có nhiệt độ "
             f"(by_industry & macro trung tính = 0)")

    # 6. Metrics
    _log_metrics(deduped, kept, today_index, universe)

    log.info("=== step_news_daily: DONE ===")


if __name__ == "__main__":
    run()
