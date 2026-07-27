"""
utils/news_aggregate.py — Tổng hợp bài → insight theo ngành / mã / vĩ mô
========================================================================
Xuất 2 output từ CÙNG một lần tính:
  - today_index : schema CŨ (để scoring hiện tại đọc không vỡ — quyết định D1)
  - insights    : bản MỚI, giàu hơn (tổng/TB cảm xúc, đếm bài, thống kê nguồn)

QUAN TRỌNG: đây mới là tín hiệu THÔ. Việc quy 'score' ngành/mã cuối cùng để
bước SCORING làm sau (sẽ đọc insights.json). Không đụng công thức chấm điểm ở đây.

Khớp MÃ (ticker + tên công ty) làm ở tầng này, trên toàn bộ bài — mirror bản cũ.
"""
import logging

from utils.news_enrich import (
    normalize, build_company_name_map, build_ticker_patterns,
    score_macro, impact_decay,
)

log = logging.getLogger(__name__)


def _raw_to_score(values, max_pts):
    """Trung bình cảm xúc [-5..5] → thang [0..max_pts] (giữ nguyên bản cũ)."""
    if not values:
        return round(max_pts / 2, 2)
    avg = sum(values) / len(values)
    clipped = max(-5.0, min(5.0, avg))
    return round((clipped + 5.0) / 10.0 * max_pts, 2)


def _top_articles(tuples, n=3):
    """Lấy n bài đóng góp mạnh nhất (theo |contribution|), khử trùng URL."""
    st = sorted(tuples, key=lambda x: abs(x[0]), reverse=True)
    seen, result = set(), []
    for contrib, art in st:
        url = art.get("url", "")
        if url in seen:
            continue
        seen.add(url)
        result.append({
            "title": (art.get("title") or "")[:80],
            "source": art.get("source", ""),
            "time": str(art.get("publish_time", ""))[:16],
            "news_type": art.get("news_type", "immediate"),
            "effective_date": art.get("effective_date"),
            "industries": art.get("matched_industries", []),
            "url": url,
            "contribution": round(contrib, 3),
        })
        if len(result) >= n:
            break
    return result


def _recompute_dynamic(all_articles, now):
    """Tính lại macro_score/time_decay/weighted_sentiment cho MỌI bài (cả history)."""
    for art in all_articles:
        art["macro_score"] = score_macro(
            f"{art.get('title', '')} {art.get('short_description', '')}",
            art.get("matched_industries", []),
        )
        art["time_decay"] = impact_decay(art, now)
        art["weighted_sentiment"] = round(
            art.get("raw_sentiment", 0)
            * art.get("source_weight", 1.0)
            * art["time_decay"], 4
        )


def _match_symbols(all_articles, industry_map):
    """Gắn mã cho từng bài (ticker ×1.5, tên công ty ×1.2). Trả symbol_tuples."""
    ticker_patterns = build_ticker_patterns(industry_map)
    name_to_sym = build_company_name_map(industry_map)

    symbol_tuples: dict[str, list] = {}
    n_ticker = n_name = 0
    for art in all_articles:
        title = art.get("title") or ""
        desc = art.get("short_description") or ""
        tags = str(art.get("tags") or "")
        text_norm = normalize(f"{title} {desc} {tags}")
        text_up = f"{title.upper()} {tags.upper()} {desc.upper()}"
        ws = art.get("weighted_sentiment", 0.0)

        matched = set()
        for sym, pat in ticker_patterns.items():
            if pat.search(text_up) and sym not in matched:
                matched.add(sym)
                symbol_tuples.setdefault(sym, []).append((ws * 1.5, art))
                n_ticker += 1
        for name, sym in name_to_sym.items():
            if sym in matched:
                continue
            if name in text_norm:
                matched.add(sym)
                symbol_tuples.setdefault(sym, []).append((ws * 1.2, art))
                n_name += 1
        art["matched_symbols"] = sorted(matched)  # annotate cho raw.json/insights

    log.info(f"  Khớp mã: {len(symbol_tuples)} mã "
             f"({n_ticker} qua ticker, {n_name} qua tên công ty)")
    return symbol_tuples


def _stats(tuples):
    """Thống kê THÔ cho 1 nhóm (ngành/mã): đếm bài + tổng/TB cảm xúc + top bài."""
    vals = [v for v, _ in tuples]
    return {
        "article_count": len(tuples),
        "sentiment_sum": round(sum(vals), 4),
        "sentiment_avg": round(sum(vals) / len(vals), 4) if vals else 0.0,
        "delayed_count": sum(1 for _, a in tuples if a.get("news_type") == "delayed"),
        "top_articles": _top_articles(tuples, n=5),
    }


def build_outputs(all_articles, industry_map, now):
    """
    Trả (today_index, insights) trong 1 lần:
      recompute dynamic → gom ngành/vĩ mô → khớp mã → dựng cả 2 output.
    """
    _recompute_dynamic(all_articles, now)

    # by_industry
    industry_tuples: dict[str, list] = {}
    for art in all_articles:
        ws = art.get("weighted_sentiment", 0.0)
        for ind in art.get("matched_industries", []):
            industry_tuples.setdefault(ind, []).append((ws, art))

    # macro (chỉ bài có macro_score != 0)
    macro_tuples = [
        (art.get("macro_score", 0) * art.get("time_decay", 0.5), art)
        for art in all_articles if art.get("macro_score", 0) != 0
    ]
    macro_vals = [v for v, _ in macro_tuples]

    # symbols
    symbol_tuples = _match_symbols(all_articles, industry_map)

    # ─── today_index (SCHEMA CŨ — backward compat) ─────────────────────────
    by_industry_old = {}
    for ind, tuples in industry_tuples.items():
        vals = [v for v, _ in tuples]
        by_industry_old[ind] = {
            "score": _raw_to_score(vals, 4.0),
            "article_count": len(tuples),
            "delayed_count": sum(1 for _, a in tuples if a.get("news_type") == "delayed"),
            "top_articles": _top_articles(tuples, n=3),
        }
    symbol_mentions_old = {}
    for sym, tuples in symbol_tuples.items():
        vals = [v for v, _ in tuples]
        symbol_mentions_old[sym] = {
            "score": _raw_to_score(vals, 4.0),
            "article_count": len(tuples),
            "top_articles": _top_articles(tuples, n=2),
        }
    today_index = {
        "date": now.strftime("%Y-%m-%d"),
        "generated_at": now.strftime("%H:%M"),
        "by_industry": by_industry_old,
        "macro": {
            "score": _raw_to_score(macro_vals, 2.0),
            "article_count": len(macro_tuples),
            "top_articles": _top_articles(macro_tuples, n=2),
        },
        "symbol_mentions": symbol_mentions_old,
    }

    # ─── insights (BẢN MỚI — giàu, THÔ) ────────────────────────────────────
    by_industry_new = {ind: _stats(t) for ind, t in industry_tuples.items()}
    by_symbol_new = {sym: _stats(t) for sym, t in symbol_tuples.items()}

    source_stats: dict[str, dict] = {}
    for art in all_articles:
        src = art.get("source", "?")
        source_stats.setdefault(src, {"article_count": 0})
        source_stats[src]["article_count"] += 1

    insights = {
        "date": now.strftime("%Y-%m-%d"),
        "generated_at": now.strftime("%H:%M:%S"),
        "totals": {
            "articles": len(all_articles),
            "industries_tagged": len(by_industry_new),
            "symbols_tagged": len(by_symbol_new),
            "macro_tagged": len(macro_tuples),
        },
        "by_industry": dict(sorted(
            by_industry_new.items(),
            key=lambda kv: kv[1]["article_count"], reverse=True)),
        "by_symbol": dict(sorted(
            by_symbol_new.items(),
            key=lambda kv: kv[1]["article_count"], reverse=True)),
        "macro": {
            "article_count": len(macro_tuples),
            "sentiment_sum": round(sum(macro_vals), 4),
            "sentiment_avg": round(sum(macro_vals) / len(macro_vals), 4) if macro_vals else 0.0,
            "top_articles": _top_articles(macro_tuples, n=5),
        },
        "source_stats": source_stats,
    }
    return today_index, insights
