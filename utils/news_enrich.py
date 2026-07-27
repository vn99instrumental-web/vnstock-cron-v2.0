"""
utils/news_enrich.py — Làm giàu bài + tiện ích khớp ngành/mã
=============================================================
Tái sử dụng NGUYÊN logic đã kiểm chứng (Bug #9 macro filter, Bug #11 symbol
match) từ step_news_daily cũ, tách ra module riêng để news collector gọi.

CHỨC NĂNG:
  - enrich_article(): gắn ngành, phân loại tin (immediate/delayed/monitoring),
    ngày hiệu lực, cảm xúc thô (import từ news_sentiment), độ tươi (time_decay).
  - Tiện ích khớp MÃ (ticker + tên công ty) — được aggregate gọi trên toàn bộ bài.

Nguồn dữ liệu tái dùng:
  - utils/industry_keywords.py : INDUSTRY_KEYWORDS / MACRO_KEYWORDS /
    NEWS_TYPE_KEYWORDS / EFFECTIVE_DATE_PATTERNS
  - output/market/industry_map.json : symbol/organ_name/organ_short_name
"""
import re
import unicodedata
from datetime import datetime, timezone

from utils.helpers import now_ict
from utils.industry_keywords import (
    INDUSTRY_KEYWORDS, MACRO_KEYWORDS,
    NEWS_TYPE_KEYWORDS, EFFECTIVE_DATE_PATTERNS,
)
from utils.news_sentiment import score_sentiment

# ─── Macro filter (Bug #9): tin vĩ mô TIÊU CỰC chỉ áp khi bài có industry tài chính ─
MACRO_CONTEXT_INDUSTRIES: set[str] = {
    "Ngân hàng", "Bảo hiểm", "Dịch vụ tài chính", "Bất động sản",
    "Sản xuất Dầu khí", "Sản xuất & Phân phối Điện",
    "Kim loại", "Xây dựng và Vật liệu", "Hóa chất",
    "Nguyên vật liệu", "Công nghiệp",
}

# ─── Symbol matching config (Bug #11) ────────────────────────────────────────
_MIN_NAME_LEN = 4
_COMPANY_PREFIXES = [
    "tổng công ty cổ phần", "tổng công ty", "công ty cổ phần",
    "công ty tnhh", "công ty cp", "công ty", "tập đoàn",
    "ngân hàng tmcp", "ngân hàng cổ phần", "ngân hàng",
    "tcty", "tct", "ctcp",
]
_STOPLIST = {
    "VIỆT NAM", "DỊCH VỤ", "ĐẦU TƯ", "PHÁT TRIỂN", "THƯƠNG MẠI",
    "SẢN XUẤT", "XÂY DỰNG", "KINH DOANH", "VẬN TẢI", "ĐIỆN LỰC",
    "NƯỚC GIẢI KHÁT", "QUẢN LÝ", "TÀI CHÍNH",
}


def normalize(s: str) -> str:
    """Chuẩn hóa unicode (NFC) + IN HOA + gộp khoảng trắng."""
    if not s:
        return ""
    s = unicodedata.normalize("NFC", str(s))
    return re.sub(r"\s+", " ", s.strip()).upper()


def strip_company_prefix(name: str) -> str:
    """Bỏ tiền tố công ty ('Công ty CP', 'Tập đoàn'...) → còn tên lõi."""
    if not name:
        return ""
    norm = name.strip()
    low = norm.lower()
    for prefix in _COMPANY_PREFIXES:
        if low.startswith(prefix + " "):
            return norm[len(prefix) + 1:].strip()
        if low == prefix:
            return ""
    return norm


def build_company_name_map(industry_map: list) -> dict:
    """Map tên công ty (đã chuẩn hóa, IN HOA) → mã. Deterministic khi trùng."""
    name_to_sym: dict[str, str] = {}
    for entry in industry_map:
        sym = entry.get("symbol") or entry.get("ticker") or entry.get("code")
        if not sym:
            continue
        short = (entry.get("organ_short_name") or "").strip()
        if short and len(short) >= _MIN_NAME_LEN:
            sn = normalize(short)
            if sn not in _STOPLIST and sn not in name_to_sym:
                name_to_sym[sn] = sym
        full = (entry.get("organ_name") or "").strip()
        if full:
            stripped = strip_company_prefix(full)
            if stripped and len(stripped) >= _MIN_NAME_LEN:
                fn = normalize(stripped)
                if (fn not in _STOPLIST and fn not in name_to_sym
                        and fn != normalize(short)):
                    name_to_sym[fn] = sym
    return name_to_sym


def build_ticker_patterns(industry_map: list) -> dict:
    """Map mã → regex word-boundary để dò ticker trong text IN HOA."""
    syms = {
        (r.get("symbol") or r.get("ticker") or r.get("code"))
        for r in industry_map
        if (r.get("symbol") or r.get("ticker") or r.get("code"))
    }
    return {s: re.compile(r"\b" + re.escape(s) + r"\b", re.UNICODE) for s in syms}


# ─── Time helpers ─────────────────────────────────────────────────────────────
def parse_time(raw):
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


# ─── Enrich pieces ────────────────────────────────────────────────────────────
def classify_news_type(text: str) -> str:
    t = text.lower()
    if any(kw in t for kw in NEWS_TYPE_KEYWORDS["delayed"]):
        return "delayed"
    if any(kw in t for kw in NEWS_TYPE_KEYWORDS["monitoring"]):
        return "monitoring"
    return "immediate"


def extract_effective_date(text: str):
    """Trích ngày hiệu lực (cho tin 'delayed') từ tiêu đề/mô tả. None nếu không có."""
    now = now_ict()
    year = now.year
    t = text.lower()
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
                q_year = int(groups[1]) if len(groups) > 1 else year
                month = (quarter - 1) * 3 + 1
                return f"{q_year}-{month:02d}-01"
            if "tháng" in pattern:
                month = int(raw)
                y = int(groups[1]) if len(groups) > 1 else year
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


def tag_industries(text: str) -> list:
    t = text.lower()
    return [
        ind for ind, keywords in INDUSTRY_KEYWORDS.items()
        if any(kw.lower() in t for kw in keywords)
    ]


def score_macro(text: str, industries=None) -> float:
    t = text.lower()
    total = 0.0
    has_fin = bool(set(industries or []) & MACRO_CONTEXT_INDUSTRIES)
    for kw, bias in MACRO_KEYWORDS.items():
        if kw.lower() in t:
            if bias >= 0:
                total += bias
            elif has_fin:
                total += bias
    return float(total)


def impact_decay(article: dict, now: datetime) -> float:
    """Độ 'tươi' của tin (0..1). Tin cũ / xa ngày hiệu lực → nhẹ dần."""
    news_type = article.get("news_type", "immediate")
    publish_time = parse_time(article.get("publish_time"))
    effective_date = parse_time(article.get("effective_date"))

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


def enrich_article(art: dict, source: str, source_weight: float,
                   now: datetime) -> dict:
    """Bài thô → bài đã làm giàu (ngành/type/effective_date/cảm xúc/độ tươi)."""
    title = art.get("title") or ""
    desc = (art.get("short_description") or art.get("description")
            or art.get("summary") or "")
    text = f"{title} {desc}"

    news_type = classify_news_type(text)
    effective_date = extract_effective_date(text) if news_type == "delayed" else None
    industries = tag_industries(text)
    raw_sentiment = score_sentiment(text)
    macro_score = score_macro(text, industries)

    meta = {
        "publish_time": str(art.get("publish_time", "")),
        "news_type": news_type,
        "effective_date": effective_date,
    }
    decay = impact_decay(meta, now)
    url = art.get("url") or art.get("link") or ""

    return {
        "url": url,
        "title": title,
        "short_description": desc,
        "publish_time": str(art.get("publish_time")
                            or art.get("pubDate")
                            or art.get("published") or ""),
        "category": art.get("category", ""),
        "tags": art.get("tags", ""),
        "source": source,
        "source_weight": source_weight,
        "news_type": news_type,
        "effective_date": effective_date,
        "matched_industries": industries,
        "raw_sentiment": raw_sentiment,
        "macro_score": macro_score,
        "time_decay": decay,
        "weighted_sentiment": round(raw_sentiment * source_weight * decay, 4),
    }
