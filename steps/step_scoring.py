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
from utils.formatter import clean_for_export
from utils.indicators_meta import INDICATORS_META

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(levelname)s %(message)s'
)
log = logging.getLogger(__name__)


# =====================================================
# NEWS SCORING — đọc từ news_today_index.json
# =====================================================

def build_news_scores(today_index: dict,
                      symbols_with_industry: list[dict]) -> dict:
    """
    Lookup score từ pre-computed today_index.
    Không tính toán gì thêm — daily đã làm hết.

    Trả về:
    {
      symbol: {
        "industry": float,   # 0–4
        "mention":  float,   # 0–4
        "macro":    float,   # 0–2
        "total":    float,   # 0–10
        "evidence": [...]
      }
    }
    """
    NEUTRAL     = 5.0
    NEUTRAL_IND = 2.0
    NEUTRAL_MAC = 1.0

    if not today_index:
        return {item["symbol"]: {
            "industry": NEUTRAL_IND,
            "mention":  NEUTRAL_IND,
            "macro":    NEUTRAL_MAC,
            "total":    NEUTRAL,
            "evidence": [],
        } for item in symbols_with_industry}

    by_industry      = today_index.get("by_industry",      {})
    symbol_mentions  = today_index.get("symbol_mentions",  {})
    macro_data       = today_index.get("macro",             {})
    macro_score      = float(macro_data.get("score", NEUTRAL_MAC))

    result = {}
    for item in symbols_with_industry:
        sym = item["symbol"]
        ind = item.get("icb_name") or item.get("industry") or ""

        # Industry score
        ind_data  = by_industry.get(ind, {})
        ind_score = float(ind_data.get("score", NEUTRAL_IND))

        # Symbol mention score
        sym_data  = symbol_mentions.get(sym, {})
        sym_score = float(sym_data.get("score", NEUTRAL_IND))

        total = round(ind_score + sym_score + macro_score, 2)
        total = max(0.0, min(10.0, total))

        # Evidence — kết hợp từ mention + industry + macro
        evidence = []

        for art in sym_data.get("top_articles", [])[:2]:
            evidence.append({**art, "type": "mention"})

        for art in ind_data.get("top_articles", [])[:2]:
            evidence.append({**art, "type": "industry"})

        for art in macro_data.get("top_articles", [])[:1]:
            evidence.append({**art, "type": "macro"})

        # Dedup + giới hạn 3
        seen  = set()
        top3  = []
        for ev in evidence:
            key = ev.get("title", "")
            if key not in seen:
                seen.add(key)
                top3.append(ev)
            if len(top3) >= 3:
                break

        result[sym] = {
            "industry": ind_score,
            "mention":  sym_score,
            "macro":    macro_score,
            "total":    total,
            "evidence": top3,
        }

    return result


# =====================================================
# SCORING ENGINE
# =====================================================

def score_symbol(row: dict, context: dict, news_scores: dict) -> dict:
    """
    Tính điểm cho một symbol.

    Kiến trúc pass-through:
    - out = dict(row)  →  copy toàn bộ deep_raw fields vào output
    - Scoring chỉ thêm/override các field điểm số
    - Không filter field nào → downstream nhận đầy đủ data
    - signals_display.csv tự filter qua INDICATORS_META

    Scoring groups & caps:
      Trend        : max ±30  (EMA cross 15 + Price>EMA 5 + ADX 5 + Supertrend 5)
      Momentum     : max ±23  (RSI 15 + MACD 10 + Stoch zone 5 + Stoch cross 3)
      Volume       : max ±20  (CMF 10 + MFI 10 + OBV 5 + BB position 5)
      Foreign Flow : max ±20  (FF net5d 5 + FF net20d 5 + FF trend 5 + FF accel 5)
      Fundamental  : max ±18  (PE 10 + PB 5 + ROE 5)  — sửa từ 15 → 18 cho đúng code
      Cash Flow    : max ±10  (CFO 5 + CF quality 5)
      Market Ctx   : max ±5
      News         : 0–10
    Total max tích cực ~ 136, thực tế dải hữu ích -50 → +100
    Thresholds: ≥70 STRONG BUY | ≥50 BUY | ≥30 NEUTRAL | ≥10 SELL | <10 STRONG SELL
    """
    s      = {}
    sigs   = []
    market = context.get("market_valuation", "FAIR")

    def add(group, pts, reason):
        s[group] = s.get(group, 0) + pts
        sigs.append(f"{reason} {'+' if pts > 0 else ''}{pts}")

    # ── VOLATILITY FILTER ──
    # Nếu ATR% < 0.5% → thị trường đang flat/tích lũy
    # Giảm độ tin cậy EMA cross và MACD xuống 50%
    price   = row.get("price") or 1
    atr_pct = row.get("atr_pct") or 0
    volatility_ok = atr_pct >= 0.5
    ema_macd_weight = 1.0 if volatility_ok else 0.5

    # ── TREND (max 30) ──
    ema20 = row.get("ema20")
    ema50 = row.get("ema50")

    if ema20 and ema50:
        raw_pts = 15 if ema20 > ema50 else -15
        pts     = round(raw_pts * ema_macd_weight)
        label   = "EMA20>EMA50" if ema20 > ema50 else "EMA20<EMA50"
        if not volatility_ok:
            label += "(flat×0.5)"
        add("trend", pts, label)

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

    supertrend = row.get("supertrend")
    if supertrend and price:
        if price > supertrend:
            add("trend", 5, f"ST={supertrend} bullish")
        else:
            add("trend", -5, f"ST={supertrend} bearish")

    # ── MOMENTUM (max 23) ──
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
        raw_pts = 10 if macd_hist > 0 else -10
        pts     = round(raw_pts * ema_macd_weight)
        label   = f"MACD hist={macd_hist}>0" if macd_hist > 0 \
                  else f"MACD hist={macd_hist}<0"
        if not volatility_ok:
            label += "(flat×0.5)"
        add("momentum", pts, label)

    stoch_k = row.get("stoch_k")
    stoch_d = row.get("stoch_d")
    if stoch_k is not None:
        # Zone score
        if stoch_k < 20:
            add("momentum", 5,  f"Stoch K={stoch_k} oversold")
        elif stoch_k > 80:
            add("momentum", -5, f"Stoch K={stoch_k} overbought")
        # Cross score — K vượt D (chỉ tính ở vùng không cực đoan)
        if stoch_k is not None and stoch_d is not None:
            if stoch_k > stoch_d and stoch_k < 80:
                add("momentum", 3,  f"Stoch K>{stoch_d} cross up")
            elif stoch_k < stoch_d and stoch_k > 20:
                add("momentum", -3, f"Stoch K<{stoch_d} cross down")

    # ── VOLUME (max 20) ──
    cmf = row.get("cmf")
    if cmf is not None:
        if cmf > 0.1:
            add("volume", 10, f"CMF={cmf} inflow")
        elif cmf < -0.1:
            add("volume", -10, f"CMF={cmf} outflow")

    mfi = row.get("mfi")
    if mfi is not None:
        if mfi < 20:
            add("volume", 10, f"MFI={mfi} oversold")
        elif mfi > 80:
            add("volume", -5, f"MFI={mfi} overbought")
        else:
            add("volume", 0,  f"MFI={mfi} neutral")

    obv       = row.get("obv")
    ema_cross = row.get("ema_cross_pct")
    if obv is not None and ema_cross is not None:
        if (obv > 0 and ema_cross > 0) or (obv < 0 and ema_cross < 0):
            add("volume", 5,  "OBV confirms trend")
        else:
            add("volume", -5, "OBV divergence")

    # BB position: 0=lower band, 1=upper band, >1=breakout, <0=breakdown
    bb_pos = row.get("bb_position")
    if bb_pos is not None:
        if bb_pos < 0.2:
            add("volume", 5,  f"BB pos={bb_pos} near lower (oversold zone)")
        elif bb_pos > 0.8:
            add("volume", -5, f"BB pos={bb_pos} near upper (overbought zone)")
        # 0.2–0.8: neutral, không cộng không trừ

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
            add("ff", 5, "FF trend accumulating")
        else:
            add("ff", -5, "FF trend distributing")

    if ff_accel is not None:
        if ff_accel > 0:
            add("ff", 5, "FF accelerating")
        else:
            add("ff", -5, "FF decelerating")

    # ── FUNDAMENTAL (max 18) ──
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
            add("cf", 5,   "CFO>0 real cash")
        else:
            add("cf", -10, "CFO<0 cash burn")

    if cf_qual is not None:
        if cf_qual > 1:
            add("cf", 5,  f"CF quality={cf_qual} high")
        elif cf_qual < 0.5:
            add("cf", -5, f"CF quality={cf_qual} low")

    # ── MARKET CONTEXT (max 5) ──
    if market == "CHEAP":
        add("context", 5,  "Market CHEAP")
    elif market == "EXPENSIVE":
        add("context", -5, "Market EXPENSIVE")
    else:
        add("context", 0,  "Market FAIR")

    # ── NEWS SENTIMENT (max 10) ──
    sym        = row["symbol"]
    ns         = news_scores.get(sym, {})
    news_score = float(ns.get("total", 5.0))
    news_score = round(max(0.0, min(10.0, news_score)), 2)

    if news_score >= 8:   news_label = "News VERY_POS"
    elif news_score >= 6: news_label = "News POS"
    elif news_score >= 4: news_label = "News NEUTRAL"
    elif news_score >= 2: news_label = "News NEG"
    else:                 news_label = "News VERY_NEG"

    evidence    = ns.get("evidence", [])
    top_article = evidence[0] if evidence else None

    if top_article:
        eff_hint = ""
        if top_article.get("news_type") == "delayed" \
                and top_article.get("effective_date"):
            eff_hint = f" eff:{top_article['effective_date']}"
        art_hint = (f"[{top_article['title'][:40]}..."
                    f" · {top_article['source']}"
                    f" · {top_article['time'][11:16]}"
                    f"{eff_hint}]")
    else:
        art_hint = "[no news]"

    sigs.append(f"{news_label} +{news_score} {art_hint}")

    # ── TOTAL — apply caps ──
    trend_score       = max(-30, min(30, s.get("trend",       0)))
    momentum_score    = max(-23, min(23, s.get("momentum",    0)))
    volume_score      = max(-20, min(20, s.get("volume",      0)))
    ff_score          = max(-20, min(20, s.get("ff",          0)))
    fundamental_score = max(-18, min(18, s.get("fundamental", 0)))
    cf_score          = max(-10, min(10, s.get("cf",          0)))
    context_score     = max(-5,  min(5,  s.get("context",     0)))
    news_score_final  = news_score

    total = (trend_score + momentum_score + volume_score +
             ff_score + fundamental_score + cf_score +
             context_score + news_score_final)

    if total >= 70:   decision = "STRONG BUY"
    elif total >= 50: decision = "BUY"
    elif total >= 30: decision = "NEUTRAL"
    elif total >= 10: decision = "SELL"
    else:             decision = "STRONG SELL"

    # ── PASS-THROUGH + SCORING FIELDS ──
    # Bắt đầu từ toàn bộ deep_raw row, sau đó override/thêm scoring fields.
    # Bất kỳ field mới nào thêm vào step_all.get_ta() sẽ tự động xuất hiện
    # trong signals.json mà không cần sửa file này.
    out = dict(row)
    out.update({
        "market_valuation"    : market,
        "atr_pct"             : row.get("atr_pct"),   # đảm bảo luôn có dù row cũ
        "trend_score"         : trend_score,
        "momentum_score"      : momentum_score,
        "volume_score"        : volume_score,
        "ff_score"            : ff_score,
        "fundamental_score"   : fundamental_score,
        "cf_score"            : cf_score,
        "context_score"       : context_score,
        "news_score"          : news_score_final,
        "news_industry"       : ns.get("industry", 2.0),
        "news_mention"        : ns.get("mention",  2.0),
        "news_macro"          : ns.get("macro",    1.0),
        "news_evidence"       : evidence,
        "total_score"         : total,
        "decision"            : decision,
        "signals"             : " | ".join(sigs),
    })
    return out


# =====================================================
# MAIN
# =====================================================

if __name__ == "__main__":
    log.info(f"Time: {now_ict():%Y-%m-%d %H:%M:%S} ICT")

    deep_raw    = load_json("deep_raw.json")
    context     = load_json("context.json")
    today_index = load_json("news_today_index.json")
    ctx         = context[0] if context else {}

    if not deep_raw:
        log.error("Không tìm thấy deep_raw.json")
        sys.exit(1)

    if today_index is None:
        log.warning("news_today_index.json không tìm thấy "
                    "— news_score sẽ là neutral (5.0)")

    symbols_with_industry = [
        {"symbol": r["symbol"], "icb_name": r.get("industry", "")}
        for r in deep_raw
    ]
    news_scores = build_news_scores(today_index or {}, symbols_with_industry)

    log.info(f"Scoring {len(deep_raw)} symbols...")

    scored_rows = []
    for row in deep_raw:
        result = score_symbol(row, ctx, news_scores)
        scored_rows.append(result)

        ev_summary = "; ".join(
            f"{e.get('type','?')}:{e.get('source','?')}:"
            f"{e.get('title','')[:25]}"
            for e in result["news_evidence"]
        ) or "no evidence"

        log.info(f"  [{result['symbol']}] "
                 f"score={result['total_score']} "
                 f"(T={result['trend_score']} M={result['momentum_score']} "
                 f"V={result['volume_score']} FF={result['ff_score']}) "
                 f"atr%={result.get('atr_pct')} "
                 f"→ {result['decision']} | {ev_summary}")

    df_signals = pd.DataFrame(scored_rows)

    # ── signals.json — raw numbers (consistent với deep_raw) ──
    save_json("signals.json",
              df_signals.to_dict(orient="records"))

    # ── signals.csv — qua clean_for_export (tỷ đồng, format chuẩn) ──
    # Tách news_evidence ra trước vì không qua clean_for_export được
    news_evidence_col = df_signals["news_evidence"].apply(
        lambda evs: " | ".join(
            f"{e.get('type','?')}·{e.get('source','?')}·"
            f"{e.get('title','')[:40]}·"
            f"{str(e.get('time',''))[5:16]}·"
            f"{e.get('contribution', 0):+.2f}"
            f"{' eff:'+e['effective_date'] if e.get('effective_date') else ''}"
            for e in (evs or [])
        )
    ) if "news_evidence" in df_signals.columns else pd.Series(
        [""] * len(df_signals))

    df_for_csv = df_signals.drop(columns=["news_evidence"], errors="ignore")
    df_csv     = clean_for_export(df_for_csv)
    df_csv["news_evidence"] = news_evidence_col.values
    save_csv("signals.csv", df_csv)

    # ── signals_display.csv ──
    # Filter chỉ những col có trong INDICATORS_META (bao gồm cả raw TA
    # vì pass-through đảm bảo chúng có trong df_signals)
    display_cols = [c for c in df_signals.columns if c in INDICATORS_META]
    df_display   = df_signals[display_cols].copy()

    if "news_evidence" in df_display.columns:
        df_display["news_evidence"] = df_display["news_evidence"].apply(
            lambda evs: " | ".join(
                f"[{e.get('type','?')}] "
                f"{e.get('source','?')}: "
                f"{e.get('title','')[:50]} "
                f"({str(e.get('time',''))[5:16]}) "
                f"{e.get('contribution', 0):+.2f}"
                f"{' →eff:'+e['effective_date'] if e.get('effective_date') else ''}"
                for e in (evs or [])
            )
        )

    save_display_csv("signals_display.csv", df_display, INDICATORS_META)

    log.info(f"Exported {len(df_signals)} rows, "
             f"{len(df_signals.columns)} cols total, "
             f"{len(display_cols)} cols in display")
    log.info("=== SCORING DONE ===")
