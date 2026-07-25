# utils/news_tagging.py
# ============================================================================
# ĐỊNH TUYẾN TIN → MÃ / NHÓM NGÀNH (Phương án 3)
# ============================================================================
# Module này CHỈ làm MỘT việc: xác định một bài tin thuộc về mã/nhóm nào,
# và tính điểm có trọng số cho từng đích. Nó KHÔNG chấm hướng tốt/xấu —
# hướng đến từ score_sentiment() (utils/news_sentiment.py) truyền vào.
#
# BA ĐƯỜNG ĐI CỦA MỘT BÀI:
#   1. symbol_direct : mã nhắc ĐÍCH DANH (ticker / tên công ty) → điểm ĐẦY ĐỦ
#                      weighted = sentiment × source_weight × time_decay
#   2. symbol_topic  : mã trong nhóm HẸP mà bài khớp TỪ KHÓA CHỦ ĐỀ (không
#                      đích danh) → điểm × TOPIC_DECAY (0.6)
#   3. sector_heat   : nhóm RỘNG mà bài khớp → CHỈ vào "nhiệt độ ngành",
#                      KHÔNG rót xuống điểm từng mã
#
# BA QUY TẮC CHỒNG LẤN (chốt 24/07/2026):
#   R1. Đích danh THẮNG chủ đề: mã đã có trong symbol_direct thì KHÔNG nhận
#       thêm điểm topic (không đếm 2 lần cho cùng 1 mã).
#   R2. Bài khớp nhiều nhóm hẹp → mỗi nhóm nhận ×0.6 độc lập (khác mã, không
#       phải đếm trùng).
#   R3. Mỗi mã thuộc đúng 1 nhóm (đảm bảo bởi sector_map) → không mã nào nhận
#       ×0.6 từ 2 nhóm chủ đề.
#
# GIỚI HẠN ĐÃ BIẾT: nếu score_sentiment() trả 0 cho một bài (cách đếm cụm từ
# chưa bắt được hướng, VD nhiều tin khủng hoảng PNJ), thì mọi đích của bài đó
# cũng = 0 dù định tuyến ĐÚNG mã. Chấm hướng là việc của tầng AI sau này.
# ============================================================================
import re
import unicodedata

from utils.sector_map import sector_of, symbols_of, is_narrow, SECTORS
from utils.sector_topics import SECTOR_TOPICS, SECTOR_HEAT_KEYWORDS, TOPIC_DECAY

# Ticker boost: mã nhắc đích danh qua TICKER tin cậy hơn qua tên công ty
TICKER_BOOST = 1.5

_MIN_NAME_LEN = 4
_COMPANY_PREFIXES = [
    "tổng công ty cổ phần", "tổng công ty", "công ty cổ phần", "công ty tnhh",
    "công ty cp", "công ty", "tập đoàn", "ngân hàng tmcp", "ngân hàng cổ phần",
    "ngân hàng", "tcty", "tct", "ctcp",
]
_STOPLIST = {
    "VIỆT NAM", "DỊCH VỤ", "ĐẦU TƯ", "PHÁT TRIỂN", "THƯƠNG MẠI", "SẢN XUẤT",
    "XÂY DỰNG", "KINH DOANH", "VẬN TẢI", "ĐIỆN LỰC", "NƯỚC GIẢI KHÁT",
    "QUẢN LÝ", "TÀI CHÍNH",
}


# ─── Chuẩn hóa ───────────────────────────────────────────────────────────────

def _normalize(s: str) -> str:
    if not s:
        return ""
    s = unicodedata.normalize("NFC", str(s))
    return re.sub(r"\s+", " ", s.strip()).upper()


def _strip_company_prefix(name: str) -> str:
    if not name:
        return ""
    low = name.strip().lower()
    for p in _COMPANY_PREFIXES:
        if low.startswith(p + " "):
            return name.strip()[len(p) + 1:].strip()
        if low == p:
            return ""
    return name.strip()


# ─── Build context (1 lần, tái dùng cho mọi bài) ────────────────────────────

def build_context(universe: set[str] | list[str],
                  industry_map: list) -> dict:
    """
    Dựng bảng tra cứu 1 lần:
      universe       : set mã trong rổ
      ticker_pat     : {sym: compiled word-boundary pattern}
      name_to_sym    : {TÊN CHUẨN HÓA: sym}  (chỉ mã trong universe)
      name_pat       : {tên: compiled pattern}
    """
    u = {str(s).strip().upper() for s in universe if s}

    ticker_pat = {
        s: re.compile(r"\b" + re.escape(s) + r"\b", re.UNICODE) for s in u
    }

    name_to_sym: dict[str, str] = {}
    for e in industry_map:
        sym = (e.get("symbol") or e.get("ticker") or e.get("code") or "").strip().upper()
        if not sym or sym not in u:
            continue
        short = (e.get("organ_short_name") or "").strip()
        if short and len(short) >= _MIN_NAME_LEN:
            n = _normalize(short)
            if n not in _STOPLIST and n not in name_to_sym:
                name_to_sym[n] = sym
        full = (e.get("organ_name") or "").strip()
        if full:
            stripped = _strip_company_prefix(full)
            if stripped and len(stripped) >= _MIN_NAME_LEN:
                n = _normalize(stripped)
                if n not in _STOPLIST and n not in name_to_sym \
                        and n != _normalize(short):
                    name_to_sym[n] = sym

    name_pat = {
        name: re.compile(r"\b" + re.escape(name) + r"\b", re.UNICODE)
        for name in name_to_sym
    }

    return {
        "universe": u,
        "ticker_pat": ticker_pat,
        "name_to_sym": name_to_sym,
        "name_pat": name_pat,
    }


# ─── Định tuyến 1 bài ────────────────────────────────────────────────────────

def _match_direct(title: str, desc: str, tags: str, ctx: dict) -> dict[str, float]:
    """
    Mã nhắc đích danh → {sym: multiplier}.
    ticker match: ×TICKER_BOOST | name match: ×1.0
    """
    via: dict[str, float] = {}

    text_upper = f"{title.upper()} {tags.upper()} {desc.upper()}"
    for sym, pat in ctx["ticker_pat"].items():
        if pat.search(text_upper):
            via[sym] = TICKER_BOOST

    text_norm = _normalize(f"{title} {desc} {tags}")
    for name, pat in ctx["name_pat"].items():
        if pat.search(text_norm):
            sym = ctx["name_to_sym"][name]
            via.setdefault(sym, 1.0)   # ticker đã có thì giữ boost

    return via


def _match_topics(text: str) -> dict[str, list[str]]:
    """Nhóm ngành HẸP khớp từ khóa chủ đề → {sector_key: [cụm khớp]}."""
    if not text:
        return {}
    t = text.lower()
    hits: dict[str, list[str]] = {}
    for sector, phrases in SECTOR_TOPICS.items():
        m = [p for p in phrases if p in t]
        if m:
            hits[sector] = m
    return hits


def _match_heat(text: str) -> dict[str, list[str]]:
    """Nhóm ngành RỘNG khớp từ khóa nhiệt độ → {sector_key: [cụm khớp]}."""
    if not text:
        return {}
    t = text.lower()
    hits: dict[str, list[str]] = {}
    for sector, phrases in SECTOR_HEAT_KEYWORDS.items():
        m = [p for p in phrases if p in t]
        if m:
            hits[sector] = m
    return hits


def tag_article(article: dict, ctx: dict) -> dict:
    """
    Định tuyến 1 bài. article cần: title, short_description, tags,
    raw_sentiment, source_weight, time_decay (đã enrich bởi step_news_daily).

    Returns:
      {
        "symbol_direct": {sym: weighted_score},   # điểm đầy đủ
        "symbol_topic":  {sym: weighted_score},   # đã ×TOPIC_DECAY
        "sector_heat":   {sector_key: weighted_score},
        "evidence": {
            "direct_syms": [...],
            "topic_hits":  {sector: [cụm]},
            "heat_hits":   {sector: [cụm]},
        }
      }
    """
    title = article.get("title") or ""
    desc  = article.get("short_description") or ""
    tags  = str(article.get("tags") or "")

    sentiment = float(article.get("raw_sentiment", 0.0))
    sw        = float(article.get("source_weight", 1.0))
    decay     = float(article.get("time_decay", 0.5))
    base      = sentiment * sw * decay

    # ── Đường 1: đích danh ──
    direct_mult = _match_direct(title, desc, tags, ctx)
    symbol_direct = {sym: round(base * mult, 4) for sym, mult in direct_mult.items()}

    full_text = f"{title} {desc} {tags}"

    # ── Đường 2: chủ đề nhóm HẸP → điểm mã ×0.6 ──
    topic_hits = _match_topics(full_text)
    symbol_topic: dict[str, float] = {}
    topic_ev: dict[str, list] = {}
    for sector, phrases in topic_hits.items():
        if not is_narrow(sector):
            continue  # an toàn: SECTOR_TOPICS chỉ chứa nhóm hẹp, chặn kép
        topic_ev[sector] = phrases
        for sym in symbols_of(sector):
            if sym in symbol_direct:   # R1: đích danh thắng chủ đề
                continue
            symbol_topic[sym] = round(base * TOPIC_DECAY, 4)

    # ── Đường 3: nhiệt độ nhóm RỘNG (không rót xuống mã) ──
    heat_hits = _match_heat(full_text)
    sector_heat: dict[str, float] = {}
    heat_ev: dict[str, list] = {}
    for sector, phrases in heat_hits.items():
        sector_heat[sector] = round(base, 4)
        heat_ev[sector] = phrases

    return {
        "symbol_direct": symbol_direct,
        "symbol_topic":  symbol_topic,
        "sector_heat":   sector_heat,
        "evidence": {
            "direct_syms": sorted(direct_mult.keys()),
            "topic_hits":  topic_ev,
            "heat_hits":   heat_ev,
        },
    }


# ─── Gộp nhiều bài → điểm theo mã / nhiệt độ ngành ──────────────────────────

def aggregate(articles: list[dict], ctx: dict) -> dict:
    """
    Gộp toàn bộ bài → điểm news theo mã + nhiệt độ ngành rộng.

    QUAN TRỌNG (schema 3): ĐỊNH TUYẾN tách khỏi CHẤM ĐIỂM. Một mã được định
    tuyến tới (có bài nhắc đích danh HOẶC khớp chủ đề ngành hẹp) sẽ LUÔN có
    mặt trong symbol_score — kể cả khi điểm = 0 vì sentiment chưa bắt được
    hướng. Lý do: dashboard/cảnh báo cần biết "mã X đang có tin" độc lập với
    hướng. (Bằng chứng: tin khủng hoảng PNJ bị engine chấm 0 — nhưng PNJ VẪN
    phải nổi lên là "có tin bất thường".)

    symbol_score[sym] = mean(mọi đóng góp direct + topic của các BÀI KHÁC
    NHAU cho sym). Cùng 1 bài không đếm 2 lần (R1 đã chặn).
    sector_heat[sector] = {"score": mean, "n": số bài}
    """
    sym_contribs: dict[str, list[float]] = {}
    sym_articles: dict[str, list[dict]]  = {}
    heat_contribs: dict[str, list[float]] = {}

    for art in articles:
        tagged = tag_article(art, ctx)
        for sym, val in tagged["symbol_direct"].items():
            sym_contribs.setdefault(sym, []).append(val)
            sym_articles.setdefault(sym, []).append(
                {"title": (art.get("title") or "")[:80],
                 "source": art.get("source", ""),
                 "val": val, "kind": "direct"})
        for sym, val in tagged["symbol_topic"].items():
            sym_contribs.setdefault(sym, []).append(val)
            sym_articles.setdefault(sym, []).append(
                {"title": (art.get("title") or "")[:80],
                 "source": art.get("source", ""),
                 "val": val, "kind": "topic"})
        for sector, val in tagged["sector_heat"].items():
            heat_contribs.setdefault(sector, []).append(val)

    symbol_score = {
        sym: round(sum(vals) / len(vals), 4)
        for sym, vals in sym_contribs.items()
    }
    sector_heat = {
        sector: {"score": round(sum(v) / len(v), 4), "n": len(v)}
        for sector, v in heat_contribs.items()
    }

    return {
        "symbol_score": symbol_score,
        "symbol_articles": sym_articles,
        "sector_heat": sector_heat,
    }
