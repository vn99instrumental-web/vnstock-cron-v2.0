"""
debug_news_full.py — Comprehensive vnstock_news diagnostic
============================================================
Bug user reported: news chỉ có title, không có short_description.

Investigate:
  1. Crawler.get_articles() — current Layer 1 method — fields returned?
  2. Crawler.get_articles_from_feed() — RSS only path — fields returned?
  3. RSS class direct — different description_format?
  4. Sitemap class direct
  5. Compare structure across 5 sites (different parsers may differ)
  6. Is there get_article_content() method để fetch full body?
  7. Different params: limit, description_format, language

Output sẽ help identify:
  - Field name có khác? (description vs summary vs excerpt vs lead)
  - Có method nào trả về full content not just title?
  - Site nào trả description tốt hơn?
"""
import os
import sys
import traceback

os.environ["VNSTOCK_INTERACTIVE"] = "0"
os.environ["VNSTOCK_LANGUAGE"]    = "en"
os.environ["MPLCONFIGDIR"]        = "/home/runner/.config/matplotlib"
os.makedirs("/home/runner/.vnstock",           exist_ok=True)
os.makedirs("/home/runner/.config/matplotlib", exist_ok=True)

import json

try:
    import vnstock_news
    print(f"vnstock_news version: "
          f"{getattr(vnstock_news, '__version__', 'unknown')}")
    # List available classes
    print(f"vnstock_news public attrs: "
          f"{[a for a in dir(vnstock_news) if not a.startswith('_')]}")
except Exception as e:
    print(f"vnstock_news import failed: {e}")
    sys.exit(1)


# Sites diverse — different parsers
TEST_SITES = ["vnexpress", "vietstock", "baodautu", "cafebiz", "tienphong"]


def section(title: str):
    print(f"\n{'=' * 80}")
    print(f"  {title}")
    print(f"{'=' * 80}")


def dump_article(art, idx: int):
    """Dump single article structure."""
    if not isinstance(art, dict):
        print(f"    [{idx}] type={type(art).__name__}: {str(art)[:100]}")
        return

    print(f"    [{idx}] keys = {sorted(art.keys())}")

    # Show key fields specifically
    for fld in ["title", "url", "link", "publish_time", "pubDate",
                "category", "tags", "author"]:
        if fld in art:
            val = str(art.get(fld) or "")[:80]
            print(f"        {fld}: {val}")

    # Description-related fields (the BUG!)
    desc_fields = ["short_description", "description", "summary",
                   "excerpt", "content_excerpt", "lead", "intro",
                   "abstract", "snippet", "preview", "content"]
    desc_present = False
    for fld in desc_fields:
        if fld in art:
            val = art.get(fld) or ""
            length = len(str(val))
            preview = str(val)[:100].replace('\n', ' ')
            print(f"        {fld} ({length} chars): {preview}"
                  f"{'...' if length > 100 else ''}")
            if val and len(str(val)) > 10:
                desc_present = True

    if not desc_present:
        print(f"        ⚠️ NO DESCRIPTION FIELD HAS DATA")


def safe_call(label: str, fn):
    """Run fn, return result or None on error."""
    try:
        return fn()
    except Exception as e:
        print(f"    ❌ {label}: {type(e).__name__}: {e}")
        return None


# =====================================================
# 1. Crawler.get_articles() — current Layer 1
# =====================================================

def test_crawler_get_articles(site_name: str):
    section(f"Crawler({site_name}).get_articles() — current Layer 1")

    try:
        from vnstock_news import Crawler
    except ImportError as e:
        print(f"  ❌ Cannot import Crawler: {e}")
        return

    crawler = safe_call("create Crawler",
                       lambda: Crawler(site_name=site_name))
    if not crawler:
        return

    # Show available methods
    methods = [m for m in dir(crawler)
               if not m.startswith('_') and callable(getattr(crawler, m))]
    print(f"  Available methods: {methods}")

    # Test get_articles
    print(f"\n  • get_articles(limit=3):")
    raw = safe_call("get_articles",
                   lambda: crawler.get_articles(limit=3))

    if raw is None:
        return
    if not isinstance(raw, list):
        print(f"    Returned type: {type(raw).__name__}")
        try:
            print(f"    Repr: {raw!r}"[:300])
        except Exception:
            pass
        return
    if not raw:
        print(f"    Returned empty list")
        return

    print(f"  Got {len(raw)} articles. First 3 dumps:")
    for i, art in enumerate(raw[:3]):
        dump_article(art, i)
        print()


# =====================================================
# 2. Crawler.get_articles_from_feed() — RSS only path
# =====================================================

def test_crawler_from_feed(site_name: str):
    section(f"Crawler({site_name}).get_articles_from_feed() — RSS only")

    try:
        from vnstock_news import Crawler
    except ImportError:
        return

    crawler = safe_call("create Crawler",
                       lambda: Crawler(site_name=site_name))
    if not crawler:
        return

    if not hasattr(crawler, "get_articles_from_feed"):
        print(f"  ⚠️ get_articles_from_feed not available")
        return

    print(f"\n  • get_articles_from_feed(limit_per_feed=3):")
    raw = safe_call("get_articles_from_feed",
                   lambda: crawler.get_articles_from_feed(limit_per_feed=3))

    if not raw or not isinstance(raw, list) or len(raw) == 0:
        print(f"    No articles returned ({type(raw).__name__})")
        return

    print(f"  Got {len(raw)} articles. First 2 dumps:")
    for i, art in enumerate(raw[:2]):
        dump_article(art, i)
        print()


# =====================================================
# 3. Crawler — other methods (full content fetch?)
# =====================================================

def test_crawler_other_methods(site_name: str):
    section(f"Crawler({site_name}) — other methods")

    try:
        from vnstock_news import Crawler
    except ImportError:
        return

    crawler = safe_call("create Crawler",
                       lambda: Crawler(site_name=site_name))
    if not crawler:
        return

    # Get one article URL first
    raw = safe_call("get sample",
                   lambda: crawler.get_articles(limit=1))
    sample_url = None
    if raw and isinstance(raw, list) and len(raw) > 0:
        art = raw[0]
        if isinstance(art, dict):
            sample_url = art.get("url") or art.get("link")

    if not sample_url:
        print(f"  ⚠️ No sample URL — skipping content fetch tests")
        return

    print(f"  Sample URL: {sample_url}")

    # Try methods that might fetch full content
    candidate_methods = [
        "get_article_content",
        "get_full_article",
        "fetch_article",
        "get_content",
        "parse_article",
        "get_article",
    ]

    for method_name in candidate_methods:
        if hasattr(crawler, method_name):
            print(f"\n  • {method_name}({sample_url!r}):")
            method = getattr(crawler, method_name)
            result = safe_call(method_name,
                              lambda m=method: m(sample_url))
            if result is None:
                continue
            if isinstance(result, dict):
                dump_article(result, 0)
            elif isinstance(result, str):
                print(f"    Returned string ({len(result)} chars):")
                print(f"    {result[:300]}{'...' if len(result) > 300 else ''}")
            else:
                print(f"    Returned: {type(result).__name__}")
                print(f"    Repr: {str(result)[:300]}")


# =====================================================
# 4. RSS class direct
# =====================================================

def test_rss_class():
    section("RSS class direct")

    try:
        from vnstock_news.core.rss import RSS
    except ImportError as e:
        print(f"  ❌ Cannot import RSS: {e}")
        return

    print(f"  RSS class: {RSS}")
    print(f"  Methods: {[m for m in dir(RSS) if not m.startswith('_')]}")

    # Test with known good URL
    test_url = "https://baodautu.vn/rss/tin-moi-nhat.rss"

    # Test 1: description_format='text'
    print(f"\n  • RSS(rss_url, description_format='text').fetch():")
    rss = safe_call("create RSS text",
                   lambda: RSS(rss_url=test_url, description_format='text'))
    if rss:
        items = safe_call("fetch text",
                         lambda: rss.fetch())
        if items and isinstance(items, list) and len(items) > 0:
            print(f"    Got {len(items)} items. First 2:")
            for i, item in enumerate(items[:2]):
                dump_article(item, i)
                print()

    # Test 2: description_format='html'
    print(f"\n  • RSS(rss_url, description_format='html').fetch():")
    rss = safe_call("create RSS html",
                   lambda: RSS(rss_url=test_url, description_format='html'))
    if rss:
        items = safe_call("fetch html",
                         lambda: rss.fetch())
        if items and isinstance(items, list) and len(items) > 0:
            print(f"    Got {len(items)} items. First 1:")
            dump_article(items[0], 0)
            print()

    # Test 3: no description_format param
    print(f"\n  • RSS(rss_url).fetch() [default]:")
    rss = safe_call("create RSS default",
                   lambda: RSS(rss_url=test_url))
    if rss:
        items = safe_call("fetch default",
                         lambda: rss.fetch())
        if items and isinstance(items, list) and len(items) > 0:
            print(f"    Got {len(items)} items. First 1:")
            dump_article(items[0], 0)


# =====================================================
# 5. Sitemap class direct
# =====================================================

def test_sitemap_class(site_name: str):
    section(f"Sitemap class direct ({site_name})")

    try:
        from vnstock_news.core.sitemap import Sitemap
    except ImportError as e:
        print(f"  ❌ Cannot import Sitemap from core.sitemap: {e}")
        try:
            from vnstock_news import Sitemap
            print(f"  ✓ Imported Sitemap from top-level")
        except ImportError:
            print(f"  ❌ Sitemap not found at top-level either")
            return

    print(f"  Sitemap class: {Sitemap}")
    print(f"  Methods: {[m for m in dir(Sitemap) if not m.startswith('_')]}")

    # Try create with site_name
    sm = safe_call(f"Sitemap({site_name})",
                  lambda: Sitemap(site_name=site_name))
    if sm:
        # Try fetch / get
        for method_name in ["fetch", "get_articles", "list", "parse"]:
            if hasattr(sm, method_name):
                print(f"\n  • Sitemap.{method_name}():")
                method = getattr(sm, method_name)
                # Try with limit if supported, else no-arg
                result = safe_call(method_name,
                    lambda m=method: m(limit=3) if "limit" in (m.__code__.co_varnames if hasattr(m, "__code__") else []) else m())
                if result and isinstance(result, list) and len(result) > 0:
                    print(f"    Got {len(result)} items. First 1:")
                    dump_article(result[0], 0)


# =====================================================
# 6. Discover all classes/modules in vnstock_news
# =====================================================

def test_discover_classes():
    section("Discover vnstock_news public API")

    import vnstock_news
    pub_attrs = [a for a in dir(vnstock_news) if not a.startswith('_')]
    print(f"  Top-level public attrs: {pub_attrs}")

    for attr in pub_attrs:
        obj = getattr(vnstock_news, attr, None)
        if obj is None:
            continue
        attr_type = type(obj).__name__
        print(f"\n  • {attr} ({attr_type}):")
        if hasattr(obj, '__doc__') and obj.__doc__:
            doc = obj.__doc__.strip().split('\n')[0]
            print(f"      doc: {doc[:120]}")
        # If class, list methods
        if isinstance(obj, type):
            methods = [m for m in dir(obj) if not m.startswith('_')]
            print(f"      methods: {methods[:15]}")

    # Try common submodules
    print(f"\n  Trying common submodules:")
    for sub in ["core", "sites", "parsers", "config"]:
        try:
            mod = __import__(f"vnstock_news.{sub}", fromlist=[sub])
            attrs = [a for a in dir(mod) if not a.startswith('_')]
            print(f"  • vnstock_news.{sub}: {attrs[:15]}")
        except ImportError:
            pass


# =====================================================
# 7. Compare structure across sites (focus on description)
# =====================================================

def test_compare_sites():
    section("Compare description availability across sites")

    try:
        from vnstock_news import Crawler
    except ImportError:
        return

    summary = {}
    for site in TEST_SITES:
        try:
            crawler = Crawler(site_name=site)
            raw = crawler.get_articles(limit=5)
            if not raw or not isinstance(raw, list):
                summary[site] = {"status": "no data"}
                continue

            # Count articles with description
            with_desc = 0
            without_desc = 0
            avg_desc_len = 0
            desc_total = 0
            seen_fields = set()

            for art in raw:
                if not isinstance(art, dict):
                    continue
                seen_fields.update(art.keys())

                desc = (art.get("short_description") or
                       art.get("description") or
                       art.get("summary") or "")
                if desc and len(str(desc)) > 20:
                    with_desc += 1
                    desc_total += len(str(desc))
                else:
                    without_desc += 1

            avg_desc_len = (desc_total / with_desc) if with_desc > 0 else 0
            summary[site] = {
                "total": len(raw),
                "with_desc": with_desc,
                "without_desc": without_desc,
                "avg_desc_len": int(avg_desc_len),
                "fields": sorted(seen_fields),
            }
        except Exception as e:
            summary[site] = {"status": f"error: {e}"}

    print(f"\n  Summary table:\n")
    print(f"  {'site':<25} {'total':>6} {'w/desc':>8} {'no-desc':>8} "
          f"{'avg-len':>8}  fields")
    print(f"  {'-' * 100}")
    for site, info in summary.items():
        if "status" in info:
            print(f"  {site:<25} {info['status']}")
        else:
            fields_str = ", ".join(info["fields"][:6])
            if len(info["fields"]) > 6:
                fields_str += f", ... (+{len(info['fields'])-6})"
            print(f"  {site:<25} {info['total']:>6} {info['with_desc']:>8} "
                  f"{info['without_desc']:>8} {info['avg_desc_len']:>8}  "
                  f"{fields_str}")


# =====================================================
# MAIN
# =====================================================

def main():
    print("=" * 80)
    print("  vnstock_news Diagnostic — Why no short_description?")
    print("=" * 80)

    # Discovery first
    test_discover_classes()

    # 1. Test get_articles on 3 sites
    for site in ["vnexpress", "baodautu", "vietstock"]:
        test_crawler_get_articles(site)

    # 2. Test get_articles_from_feed
    for site in ["baodautu", "vnexpress"]:
        test_crawler_from_feed(site)

    # 3. Test other Crawler methods (full content fetch)
    test_crawler_other_methods("vnexpress")

    # 4. RSS class direct
    test_rss_class()

    # 5. Sitemap class
    test_sitemap_class("vnexpress")

    # 6. Compare description availability across all sites
    test_compare_sites()

    print("\n" + "=" * 80)
    print("  DONE — Identify:")
    print("    1. Which method has description data")
    print("    2. Which field name to use (desc vs summary vs excerpt vs ...)")
    print("    3. Is there a way to fetch full article body?")
    print("    4. Sites with best description coverage")
    print("=" * 80)


if __name__ == "__main__":
    main()
