"""
utils/news_rss.py — Lớp thu thập RSS + lấy nội dung bài (thay vnstock_news)
===========================================================================
- fetch_feed(url, source, limit): đọc 1 feed RSS → list bài THÔ (dict chuẩn hóa)
- needs_body(desc)             : mô tả có quá ngắn/rỗng không → cân nhắc fetch body
- fetch_body(url)              : tải trang bài, lấy mô tả/nội dung ngắn để enrich

QUY TẮC:
  - A3: chỉ đọc RSS để PHÁT HIỆN bài.
  - C2: fetch_body chỉ được gọi cho bài MỚI (orchestrator quyết định),
        tránh tải lại bài đã có trong history.
  - Fail-soft: mọi lỗi mạng → trả rỗng/None + log, KHÔNG raise.

Phụ thuộc: requests, feedparser, beautifulsoup4, lxml (cài trong workflow).
"""
import logging
import time
from datetime import datetime, timezone

import requests
import feedparser
from bs4 import BeautifulSoup

log = logging.getLogger(__name__)

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "vi,en;q=0.8",
}
_TIMEOUT = 12
_RETRIES = 2
_MIN_DESC_LEN = 40   # dưới ngưỡng này coi như "mô tả rỗng"


def _http_get(url: str, timeout: int = _TIMEOUT):
    """GET có retry + UA giả trình duyệt. Fail → None."""
    last_err = None
    for attempt in range(_RETRIES + 1):
        try:
            r = requests.get(url, headers=_HEADERS, timeout=timeout)
            if r.status_code == 200 and r.content:
                return r
            last_err = f"HTTP {r.status_code}"
        except Exception as e:
            last_err = str(e)
        if attempt < _RETRIES:
            time.sleep(1.0 + attempt)
    log.debug(f"    GET fail {url}: {last_err}")
    return None


def _struct_to_iso(st) -> str:
    """time.struct_time (UTC từ feedparser) → 'YYYY-MM-DD HH:MM:SS'."""
    if not st:
        return ""
    try:
        dt = datetime(*st[:6], tzinfo=timezone.utc)
        return dt.strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return ""


def _strip_html(s: str) -> str:
    if not s:
        return ""
    if "<" in s and ">" in s:
        try:
            return BeautifulSoup(s, "lxml").get_text(" ", strip=True)
        except Exception:
            return s
    return s


def fetch_feed(url: str, source: str, limit: int) -> list[dict]:
    """Đọc 1 feed RSS → list bài thô, mỗi bài là dict chuẩn hóa."""
    r = _http_get(url)
    if r is None:
        log.warning(f"  [skip] feed lỗi: {url}")
        return []

    parsed = feedparser.parse(r.content)
    entries = parsed.entries or []
    out: list[dict] = []
    for e in entries[:limit]:
        title = (e.get("title") or "").strip()
        link = (e.get("link") or "").strip()
        if not title or not link:
            continue

        desc = _strip_html(e.get("summary") or e.get("description") or "").strip()

        pub_iso = _struct_to_iso(e.get("published_parsed") or e.get("updated_parsed"))
        pub_raw = e.get("published") or e.get("updated") or ""

        cats = e.get("tags") or []
        tags = ", ".join(
            t.get("term", "") for t in cats if isinstance(t, dict)
        ) if cats else ""

        out.append({
            "title": title,
            "url": link,
            "short_description": desc,
            "publish_time": pub_iso or pub_raw,
            "category": e.get("category", "") or "",
            "tags": tags,
            "source": source,
        })

    tail = url.rsplit("/", 1)[-1]
    log.info(f"  {source}: {tail} -> {len(out)} bài")
    return out


def needs_body(desc: str) -> bool:
    """True nếu mô tả quá ngắn → nên fetch body để enrich cho chuẩn."""
    return len((desc or "").strip()) < _MIN_DESC_LEN


def fetch_body(url: str) -> str:
    """Tải trang bài, trả mô tả/nội dung ngắn (<=800 ký tự). Fail → ''."""
    if not url:
        return ""
    r = _http_get(url)
    if r is None:
        return ""
    try:
        soup = BeautifulSoup(r.content, "lxml")

        # 1) meta description / og:description (rẻ + ổn định)
        for name, attrs in [
            ("meta", {"property": "og:description"}),
            ("meta", {"name": "description"}),
        ]:
            tag = soup.find(name, attrs=attrs)
            if tag and tag.get("content"):
                txt = tag["content"].strip()
                if len(txt) >= _MIN_DESC_LEN:
                    return txt[:800]

        # 2) sapo / lead thường gặp trên báo VN
        for cls in ["sapo", "detail-sapo", "article-sapo", "knc-sapo",
                    "lead", "detail__sapo", "post-sapo"]:
            node = soup.find(class_=cls)
            if node:
                txt = node.get_text(" ", strip=True)
                if len(txt) >= _MIN_DESC_LEN:
                    return txt[:800]

        # 3) gộp vài <p> đầu tiên
        buf = []
        for p in soup.find_all("p"):
            t = p.get_text(" ", strip=True)
            if t:
                buf.append(t)
            if sum(len(x) for x in buf) > 500:
                break
        return " ".join(buf)[:800].strip()
    except Exception as e:
        log.debug(f"    body parse fail {url}: {e}")
        return ""
