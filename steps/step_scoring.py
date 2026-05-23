import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

os.environ["VNSTOCK_INTERACTIVE"] = "0"
os.environ["VNSTOCK_LANGUAGE"]    = "en"
os.environ["MPLCONFIGDIR"]        = "/home/runner/.config/matplotlib"

import logging
import pandas as pd
from utils.helpers import now_ict, today_str
from utils.cache import load_json, save_json, save_csv, save_display_csv
from utils.indicators_meta import INDICATORS_META

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(levelname)s %(message)s'
)
log = logging.getLogger(__name__)

# =====================================================
# NEWS SCORING HELPER
# =====================================================

def build_news_scores(news_raw: list, symbols_with_industry: list[dict]) -> dict:
    """
    Tính news_score cho từng symbol dựa trên news_raw.json.
    Trả về dict: {symbol: {"industry": float, "mention": float, "macro": float, "total": float}}
    Nếu news_raw rỗng hoặc None → tất cả symbol nhận điểm neutral (5.0).
    """
    # Neutral score = giữa thang 0–10
    NEUTRAL = 5.0

    if not news_raw:
        return {item["symbol"]: {
            "industry": NEUTRAL, "mention": NEUTRAL,
            "macro": NEUTRAL,    "total":   NEUTRAL
        } for item in symbols_with_industry}

    # Build lookup: industry → [weighted_sentiment]
    industry_scores: dict[str, list[float]] = {}
    symbol_scores:   dict[str, list[float]] = {}
    macro_scores:    list[float] = []

    for art in news_raw:
        ws = art.get("weighted_sentiment", 0.0) or 0.0
        ms = art.get("macro_score", 0.0) or 0.0

        # Industry bucket
        for ind in art.get("matched_industries", []):
            industry_scores.setdefault(ind, []).append(ws)

        # Macro bucket
        if ms != 0:
            macro_scores.append(ms)

        # Direct symbol mention trong title/tags
        title = (art.get("title") or "").upper()
        tags  = str(art.get("tags") or "").upper()
        text  = f"{title} {tags}"
        for item in symbols_with_industry:
            sym = item["symbol"]
            if sym in text:
                # boost 1.5× vì đề cập trực tiếp
                symbol_scores.setdefault(sym, []).append(ws * 1.5)

    def _raw_to_score(values: list[float], max_pts: float) -> float:
        """
        Trung bình list → clip [−5, +5] → scale tuyến tính về [0, max_pts].
        Nếu list rỗng → trả neutral (max_pts / 2).
        """
        if not values:
            return round(max_pts / 2, 2)
        avg = sum(values) / len(values)
        clipped = max(-5.0, min(5.0, avg))
        return round((clipped + 5.0) / 10.0 * max_pts, 2)

    macro_avg = _raw_to_score(macro_scores, 2.0)  # max 2 điểm

    result = {}
    for item in symbols_with_industry:
        sym = item["symbol"]
        ind = item.get("icb_name") or item.get("industry") or ""

        ind_score = _raw_to_score(industry_scores.get(ind, []), 4.0)  # max 4
        sym_score = _raw_to_score(symbol_scores.get(sym,  []), 4.0)   # max 4
        total     = round(ind_score + sym_score + macro_avg, 2)       # max 10

        result[sym] = {
            "industry": ind_score,
            "mention":  sym_score,
            "macro":    macro_avg,
            "total":    total,
        }

    return result


# =====================================================
# SCORING ENGINE
# =====================================================

def score_symbol(row: dict, context: dict, news_scores: dict) -> dict:
    s      = {}   # scores
    sigs   = []   # signal list
    market = context.get("market_valuation", "FAIR")

    def add(group, pts, reason):
        s[group] = s.get(group, 0) + pts
        sigs.append(f"{reason} {'+' if pts > 0 else ''}{pts}")

    # ── TREND (max 25) ──
    ema20 = row.get("ema20")
    ema50 = row.get("ema50")
    price = row.get("price")

    if ema20 and ema50:
        if ema20 > ema50:
            add("trend", 15, "EMA20>EMA50")
        else:
            add("trend", -15, "EMA20<EMA50")

    if price and ema20:
        if price > ema20:
            add("trend", 5, "Price>EMA20")
        else:
            add("trend", -5, "Price<EMA20")

    adx = row.get("adx")
    if adx:
        if adx > 25:
            add("trend", 5, f"ADX={adx} strong")
        elif adx < 20:
            add("trend", 0, f"ADX={adx} sideways")

    # ── MOMENTUM (max 20) ──
    rsi = row.get("rsi")
    if rsi:
        if rsi < 30:
            add("momentum", 15, f"RSI={rsi} oversold")
        elif rsi > 70:
            add("momentum", -10, f"RSI={rsi} overbought")
        elif 40 <= rsi <= 60:
            add("momentum", 5, f"RSI={rsi} neutral")

    macd_hist = row.get("macd_hist")
    if macd_hist is not None:
        if macd_hist > 0:
            add("momentum", 10, f"MACD hist={macd_hist}>0")
        else:
            add("momentum", -10, f"MACD hist={macd_hist}<0")

    stoch_k = row.get("stoch_k")
    if stoch_k:
        if stoch_k < 20:
            add("momentum", 5, f"Stoch K={stoch_k} oversold")
        elif stoch_k > 80:
            add("momentum", -5, f"Stoch K={stoch_k} overbought")

    # ── VOLUME (max 15) ──
    cmf = row.get("cmf")
    if cmf is not None:
        if cmf > 0.1:
            add("volume", 10, f"CMF={cmf} inflow")
        elif cmf < -0.1:
            add("volume", -10, f"CMF={cmf} outflow")

    mfi = row.get("mfi")
    if mfi:
        if mfi < 20:
            add("volume", 10, f"MFI={mfi} oversold")
        elif mfi > 80:
            add("volume", -5, f"MFI={mfi} overbought")
        else:
            add("volume", 0, f"MFI={mfi} neutral")

    obv = row.get("obv")
    ema_cross = row.get("ema_cross_pct")
    if obv and ema_cross:
        if (obv > 0 and ema_cross > 0) or (obv < 0 and ema_cross < 0):
            add("volume", 5, "OBV confirms trend")
        else:
            add("volume", -5, "OBV divergence")

    # ── FOREIGN FLOW (max 20) ──
    ff_net_5d  = row.get("ff_net_val_5d")
    ff_net_20d = row.get("ff_net_val_20d")
    ff_trend   = row.get("ff_trend")
    ff_accel   = row.get("ff_acceleration")

    if ff_net_5d is not None:
        if ff_net_5d > 0:
            add("ff", 5, "FF net buy 5d")
        else:
            add("ff", -5, "FF net sell 5d")

    if ff_net_20d is not None:
        if ff_net_20d > 0:
            add("ff", 5, "FF net buy 20d")
        else:
            add("ff", -5, "FF net sell 20d")

    if ff_trend is not None:
        if ff_trend > 0:
            add("ff", 5, f"FF trend accumulating")
        else:
            add("ff", -5, f"FF trend distributing")

    if ff_accel is not None:
        if ff_accel > 0:
            add("ff", 5, "FF accelerating")
        else:
            add("ff", -5, "FF decelerating")

    # ── FUNDAMENTAL (max 15) ──
    r_pe = row.get("r_pe")
    r_pb = row.get("r_pb")
    roe  = row.get("r_roe")

    if r_pe:
        if r_pe < 10:
            add("fundamental", 10, f"PE={r_pe} very cheap")
        elif r_pe < 15:
            add("fundamental", 7,  f"PE={r_pe} cheap")
        elif r_pe <= 25:
            add("fundamental", 3,  f"PE={r_pe} fair")
        else:
            add("fundamental", -5, f"PE={r_pe} expensive")

    if r_pb:
        if r_pb < 1:
            add("fundamental", 5,  f"PB={r_pb} below book")
        elif r_pb <= 2:
            add("fundamental", 3,  f"PB={r_pb} fair")
        elif r_pb <= 3:
            add("fundamental", 0,  f"PB={r_pb} neutral")
        else:
            add("fundamental", -3, f"PB={r_pb} expensive")

    if roe:
        if roe > 20:
            add("fundamental", 5,  f"ROE={roe}% excellent")
        elif roe > 15:
            add("fundamental", 3,  f"ROE={roe}% good")
        elif roe > 10:
            add("fundamental", 0,  f"ROE={roe}% neutral")
        elif roe < 5:
            add("fundamental", -3, f"ROE={roe}% weak")

    # ── CASH FLOW QUALITY (max 10) ──
    cfo     = row.get("cf_operating")
    cf_qual = row.get("cf_quality_ratio")

    if cfo is not None:
        if cfo > 0:
            add("cf", 5, "CFO>0 real cash")
        else:
            add("cf", -10, "CFO<0 cash burn")

    if cf_qual is not None:
        if cf_qual > 1:
            add("cf", 5, f"CF quality={cf_qual} high")
        elif cf_qual < 0.5:
            add("cf", -5, f"CF quality={cf_qual} low")

    # ── MARKET CONTEXT (max 5) ──
    if market == "CHEAP":
        add("context", 5, "Market CHEAP")
    elif market == "EXPENSIVE":
        add("context", -5, "Market EXPENSIVE")
    else:
        add("context", 0, "Market FAIR")

    # ── NEWS SENTIMENT (max 10) ──
    sym = row["symbol"]
    ns  = news_scores.get(sym, {})
    news_score = ns.get("total", 5.0)   # 5.0 = neutral nếu không có data
    # clip về [0, 10]
    news_score = round(max(0.0, min(10.0, news_score)), 2)

    # Label để đưa vào signals string
    if news_score >= 8:
        news_label = "News VERY_POS"
    elif news_score >= 6:
        news_label = "News POS"
    elif news_score >= 4:
        news_label = "News NEUTRAL"
    elif news_score >= 2:
        news_label = "News NEG"
    else:
        news_label = "News VERY_NEG"
    sigs.append(f"{news_label} +{news_score}")

    # ── TOTAL ──
    trend_score       = max(-25, min(25, s.get("trend",       0)))
    momentum_score    = max(-20, min(20, s.get("momentum",    0)))
    volume_score      = max(-15, min(15, s.get("volume",      0)))
    ff_score          = max(-20, min(20, s.get("ff",          0)))
    fundamental_score = max(-15, min(15, s.get("fundamental", 0)))
    cf_score          = max(-10, min(10, s.get("cf",          0)))
    context_score     = max(-5,  min(5,  s.get("context",     0)))
    # news không clip âm — sàn đã là 0
    news_score_final  = news_score  # 0–10

    total = (trend_score + momentum_score + volume_score +
             ff_score + fundamental_score + cf_score +
             context_score + news_score_final)

    if total >= 70:
        decision = "STRONG BUY"
    elif total >= 50:
        decision = "BUY"
    elif total >= 30:
        decision = "NEUTRAL"
    elif total >= 10:
        decision = "SELL"
    else:
        decision = "STRONG SELL"

    return {
        "symbol"              : row["symbol"],
        "group"               : row.get("group"),
        "industry"            : row.get("industry"),
        "time"                : row.get("time"),
        "date"                : row.get("date"),
        "market_valuation"    : market,
        "r_pe"                : row.get("r_pe"),
        "r_pb"                : row.get("r_pb"),
        "r_roe"               : row.get("r_roe"),
        "ff_trend"            : row.get("ff_trend"),
        "ff_consistency"      : row.get("ff_consistency"),
        "ff_acceleration"     : row.get("ff_acceleration"),
        "cf_quality_ratio"    : row.get("cf_quality_ratio"),
        "trend_score"         : trend_score,
        "momentum_score"      : momentum_score,
        "volume_score"        : volume_score,
        "ff_score"            : ff_score,
        "fundamental_score"   : fundamental_score,
        "cf_score"            : cf_score,
        "context_score"       : context_score,
        "news_score"          : news_score_final,        # ← MỚI
        "news_industry"       : ns.get("industry", 5.0), # ← MỚI (breakdown)
        "news_mention"        : ns.get("mention",  5.0), # ← MỚI (breakdown)
        "news_macro"          : ns.get("macro",    1.0), # ← MỚI (breakdown)
        "total_score"         : total,
        "decision"            : decision,
        "signals"             : " | ".join(sigs),
    }


# =====================================================
# MAIN
# =====================================================

if __name__ == "__main__":
    log.info(f"Time: {now_ict():%Y-%m-%d %H:%M:%S} ICT")

    # Load inputs
    deep_raw  = load_json("deep_raw.json")
    context   = load_json("context.json")
    news_raw  = load_json("news_raw.json")   # ← MỚI (None nếu daily chưa chạy)
    ctx       = context[0] if context else {}

    if not deep_raw:
        log.error("Không tìm thấy deep_raw.json")
        sys.exit(1)

    if news_raw is None:
        log.warning("news_raw.json không tìm thấy — news_score sẽ là neutral (5.0)")

    # Build news scores cho tất cả symbols 1 lần — không tính lại trong loop
    symbols_with_industry = [
        {"symbol": r["symbol"], "icb_name": r.get("industry", "")}
        for r in deep_raw
    ]
    news_scores = build_news_scores(news_raw or [], symbols_with_industry)

    log.info(f"Scoring {len(deep_raw)} symbols...")

    # Score từng symbol
    scored_rows = []
    for row in deep_raw:
        result = score_symbol(row, ctx, news_scores)
        scored_rows.append(result)
        log.info(f"  [{result['symbol']}] "
                 f"score={result['total_score']} "
                 f"(news={result['news_score']}) "
                 f"→ {result['decision']}")

    df_signals = pd.DataFrame(scored_rows)

    # ── File 1: signals.json ──
    save_json("signals.json",
              df_signals.to_dict(orient="records"))

    # ── File 2: signals.csv ──
    save_csv("signals.csv", df_signals)

    # ── File 3: signals_display.csv ──
    display_cols = [c for c in df_signals.columns
                    if c in INDICATORS_META]
    df_display = df_signals[display_cols].copy()
    save_display_csv(
        "signals_display.csv",
        df_display,
        INDICATORS_META
    )

    log.info(f"Exported {len(df_signals)} rows")
    log.info("=== SCORING DONE ===")
