"""
step_scoring.py — Scoring engine v3 (Phase 1+2 improvements)
============================================================
CHANGELOG:
  2026-05-25 — FIX negative PE/PB scoring
  2026-05-26 — Threshold calibration (Bug #10)
  2026-05-27 — Phase 1+2 improvements:
    Phase 1:
      1. Growth: prefer YoY > QoQ (less seasonal noise)
      2. News range -5 to +5 (symmetric, catch negative news)
      3. Order Flow integration (read order_flow.json, new group ±10)
      4. Sector-aware CF (skip CFO penalty cho Banking/Securities/RealEstate)
      5. Debt/Equity in fundamental scoring
      6. Confluence bonus (multi-group agreement ±10)
    Phase 2:
      7. EMA200 in trend scoring (replace redundant Price>EMA20)
      8. Volume MA ratio (today vs 20d avg)
      9. New Volatility group ±5 (BB position moved here from Volume)
      10. Bull-trap detection (confidence field + pattern flag)
      11. PE — kept as-is (KBS pe_ratio is typically TTM)

  2026-06-01 — Phase 2.11 SIGN CALIBRATION (backtest 281 symbols, 15 months):
    Backtest xác nhận thị trường VN mean-reverting ở khung 1-5 ngày.
    V2 sửa dấu đạt hit_avg 0.550 (vs 0.480), ổn định 13/15 tháng.
    Ba thay đổi có bằng chứng vững nhất:
      A. Price vs EMA200 → ĐẢO thành mean-reversion (spearman -0.055)
         Dùng % distance: xa trên → trừ, xa dưới → cộng
      B. CMF → ĐẢO (spearman -0.043): inflow mạnh → overbought → trừ
      C. MFI → ĐỔI sang trend-following (threshold edge +0.58%):
         >60 bullish, <40 bearish (KHÔNG còn mean-rev <20/>80)
    GIỮ NGUYÊN: RSI, BB (đã đúng mean-rev), EMA cross, Supertrend, ADX,
                MACD, Stoch, và tất cả group khác. Caps không đổi.

  New thresholds: ≥80 SB | ≥40 BUY | ≥-15 NEUTRAL | ≥-40 SELL | <-40 SS

  New output fields:
    - confidence (HIGH/MEDIUM/LOW)
    - pattern_flags (CONSENSUS_BULL, CONSENSUS_BEAR, BULL_TRAP_RISK,
                     VALUE_OPPORTUNITY, MIXED)
    - order_flow_score, volatility_score, confluence_bonus
"""
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
# SECTOR-AWARE RULES (Phase 1.4)
# =====================================================
# Industries có CFO âm là business model bình thường, không penalize.
# - Banking: deposits/loans flow, CF accounting khác hoàn toàn
# - Securities brokers: hold securities for clients → CFO thường âm
# - Real Estate: cyclical, big CF khi sale projects
# - Insurance: premium float, claims payment timing

SECTOR_CF_SKIP_SIGN = {
    "Ngân hàng",
    "Dịch vụ tài chính",   # bao gồm securities brokers
    "Bảo hiểm",
    "Bất động sản",
}

# D/E thresholds không meaningful cho ngân hàng/bảo hiểm (vốn dài hạn)
SECTOR_SKIP_DE = {
    "Ngân hàng",
    "Bảo hiểm",
    "Dịch vụ tài chính",
}

def _is_sector_match(industry: str, sector_set: set) -> bool:
    """Match industry against sector set (case-insensitive substring)."""
    if not industry:
        return False
    ind_lower = industry.lower()
    return any(s.lower() in ind_lower for s in sector_set)


# =====================================================
# NEWS SCORING — Phase 1.2 (symmetric -5 to +5)
# =====================================================

def build_news_scores(today_index: dict,
                      symbols_with_industry: list[dict]) -> dict:
    """
    v2 (Phase 1.2): News total range -5 to +5 (symmetric).
    Trước đây: 0-10 (asymmetric — không catch negative news).

    Note: today_index file keeps 0-10 format for backward-compat;
    conversion happens here at consumption.
    """
    NEUTRAL_TOTAL = 0.0  # was 5.0 (mid of 0-10)
    NEUTRAL_IND   = 0.0  # was 2.0
    NEUTRAL_MAC   = 0.0  # was 1.0

    if not today_index:
        return {item["symbol"]: {
            "industry": NEUTRAL_IND,
            "mention" : NEUTRAL_IND,
            "macro"   : NEUTRAL_MAC,
            "total"   : NEUTRAL_TOTAL,
            "evidence": [],
        } for item in symbols_with_industry}

    by_industry     = today_index.get("by_industry",     {})
    symbol_mentions = today_index.get("symbol_mentions", {})
    macro_data      = today_index.get("macro",            {})

    # Convert 0-max range to -max/2 to +max/2 (centered)
    # Industry scores in file are 0-4 → -2 to +2
    # Symbol mentions 0-4 → -2 to +2
    # Macro 0-2 → -1 to +1
    macro_score_raw = float(macro_data.get("score", 1.0))
    macro_score     = macro_score_raw - 1.0  # center: 1.0 = neutral

    result = {}
    for item in symbols_with_industry:
        sym = item["symbol"]
        ind = item.get("icb_name") or item.get("industry") or ""

        ind_data      = by_industry.get(ind, {})
        ind_score_raw = float(ind_data.get("score", 2.0))
        ind_score     = ind_score_raw - 2.0   # center: 2.0 = neutral

        sym_data      = symbol_mentions.get(sym, {})
        sym_score_raw = float(sym_data.get("score", 2.0))
        sym_score     = sym_score_raw - 2.0   # center: 2.0 = neutral

        total = round(ind_score + sym_score + macro_score, 2)
        total = max(-5.0, min(5.0, total))  # clamp to symmetric range

        evidence = []
        for art in sym_data.get("top_articles", [])[:2]:
            evidence.append({**art, "type": "mention"})
        for art in ind_data.get("top_articles", [])[:2]:
            evidence.append({**art, "type": "industry"})
        for art in macro_data.get("top_articles", [])[:1]:
            evidence.append({**art, "type": "macro"})

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
            "mention" : sym_score,
            "macro"   : macro_score,
            "total"   : total,
            "evidence": top3,
        }
    return result


# =====================================================
# ORDER FLOW SCORING (Phase 1.3)
# =====================================================

ORDER_FLOW_PATTERN_SCORES = {
    "ACCUMULATION":          +5,
    "SPIKE_BUY":             +5,
    "INSTITUTIONAL_ACTIVITY": 0,   # neutral, refined by buy_ratio below
    "NORMAL":                 0,
    "FLAT":                   0,
    "CONTENTION":             0,
    "WEAK":                  -3,
    "DISTRIBUTION":          -5,
    "SPIKE_SELL":            -5,
    "ERROR":                  0,
    "INSUFFICIENT_DATA":      0,
}


def score_order_flow(of_data: dict) -> tuple[int, list[str]]:
    """
    Score order flow signals. Returns (score, list of signal labels).
    Max ±10.
    """
    if not of_data:
        return 0, []

    summary = of_data.get("summary", {}) if isinstance(of_data, dict) else {}
    pattern   = summary.get("pattern", "")
    buy_ratio = summary.get("buy_ratio_today")
    vol_spike = summary.get("vol_spike_pct")
    poc_div   = summary.get("poc_diverge", False)
    trader    = summary.get("trader_type", "")

    of_score = 0
    sigs     = []

    # Pattern score
    pattern_pts = ORDER_FLOW_PATTERN_SCORES.get(pattern, 0)
    if pattern_pts != 0:
        of_score += pattern_pts
        sigs.append(f"OF pattern={pattern} {'+' if pattern_pts > 0 else ''}{pattern_pts}")

    # Institutional refinement
    if pattern == "INSTITUTIONAL_ACTIVITY":
        if buy_ratio is not None:
            if buy_ratio > 0.55:
                of_score += 3
                sigs.append(f"OF institutional buying +3")
            elif buy_ratio < 0.45:
                of_score -= 3
                sigs.append(f"OF institutional selling -3")

    # Volume spike with direction
    if vol_spike is not None and vol_spike > 100:
        if buy_ratio is not None:
            if buy_ratio > 0.60:
                of_score += 3
                sigs.append(f"OF vol+{vol_spike:.0f}% buy {buy_ratio:.2f}")
            elif buy_ratio < 0.40:
                of_score -= 3
                sigs.append(f"OF vol+{vol_spike:.0f}% sell {buy_ratio:.2f}")

    # POC divergence with institutional → strong signal already counted
    # (in pattern). Skip double-count.

    of_score = max(-10, min(10, of_score))
    return of_score, sigs


# =====================================================
# MAIN SCORING ENGINE
# =====================================================


# ═════════════════════════════════════════════════════════════════
# DEPTH SCORE (max ±5) — Phase 3: Order book bid/ask
# Đọc bid_price_1..3 / ask_price_1..3 từ deep_raw (Market.equity)
# Chỉ có data khi market_open; ngoài giờ GD → tất cả None → return 0
# Wall hợp lệ: vol >= WALL_MIN_VOL = 5000
# ═════════════════════════════════════════════════════════════════
WALL_MIN_VOL = 5_000

def score_depth(row: dict) -> tuple[int, list[str]]:
    cur_price = row.get("price")
    if not cur_price or cur_price <= 0:
        return 0, []

    # Thu thập bid/ask từ row (3 mức)
    bids = []
    asks = []
    for i in (1, 2, 3):
        bp = row.get(f"bid_price_{i}")
        bv = row.get(f"bid_vol_{i}")
        ap = row.get(f"ask_price_{i}")
        av = row.get(f"ask_vol_{i}")
        if bp and bv and bv >= WALL_MIN_VOL:
            bids.append((float(bp), float(bv)))
        if ap and av and av >= WALL_MIN_VOL:
            asks.append((float(ap), float(av)))

    if not bids and not asks:
        return 0, []   # ngoài giờ GD hoặc không có data

    depth_score = 0
    sigs = []

    # ── Ask walls (tường bán phía trên) ──
    ask_walls_near  = [(p, v) for p, v in asks if 0 < (p - cur_price) / cur_price <= 0.02]
    ask_walls_mid   = [(p, v) for p, v in asks if 0.02 < (p - cur_price) / cur_price <= 0.05]
    ask_walls_clear = not ask_walls_near and not ask_walls_mid

    if ask_walls_near:
        best = max(ask_walls_near, key=lambda x: x[1])
        pct  = (best[0] - cur_price) / cur_price * 100
        depth_score -= 2
        sigs.append(f"AskWall {best[0]:,.0f} ({best[1]/1000:.0f}K cp, +{pct:.1f}%) -2")
    elif ask_walls_mid:
        best = max(ask_walls_mid, key=lambda x: x[1])
        pct  = (best[0] - cur_price) / cur_price * 100
        depth_score -= 1
        sigs.append(f"AskWall {best[0]:,.0f} ({best[1]/1000:.0f}K cp, +{pct:.1f}%) -1")
    elif ask_walls_clear:
        depth_score += 1
        sigs.append("AskClear (no wall ≤5%) +1")

    # ── Bid walls (tường mua phía dưới) ──
    bid_walls_near = [(p, v) for p, v in bids if 0 < (cur_price - p) / cur_price <= 0.02]
    bid_walls_mid  = [(p, v) for p, v in bids if 0.02 < (cur_price - p) / cur_price <= 0.05]
    no_bid_wall    = not bid_walls_near and not bid_walls_mid

    if bid_walls_near:
        best = max(bid_walls_near, key=lambda x: x[1])
        pct  = (cur_price - best[0]) / cur_price * 100
        depth_score += 2
        sigs.append(f"BidWall {best[0]:,.0f} ({best[1]/1000:.0f}K cp, -{pct:.1f}%) +2")
    elif bid_walls_mid:
        best = max(bid_walls_mid, key=lambda x: x[1])
        pct  = (cur_price - best[0]) / cur_price * 100
        depth_score += 1
        sigs.append(f"BidWall {best[0]:,.0f} ({best[1]/1000:.0f}K cp, -{pct:.1f}%) +1")
    elif no_bid_wall:
        depth_score -= 1
        sigs.append("NoBidWall (no support ≤5%) -1")

    depth_score = max(-5, min(5, depth_score))
    return depth_score, sigs


def score_symbol(row: dict, context: dict, news_scores: dict,
                 order_flow_map: dict) -> dict:
    """
    Scoring groups & caps (v3 — Phase 1+2):
      Trend         ±30  (EMA20/50 cross, ADX, Supertrend, Price>EMA200)
      Momentum      ±23  (RSI, MACD hist, Stoch K/D)
      Volume        ±20  (CMF, MFI, OBV, Volume MA ratio)
      Volatility    ±5   NEW (BB position)
      Order Flow    ±10  NEW (pattern from step_order_flow)
      Foreign Flow  ±20  (FF metrics)
      Fundamental   ±20  (PE, PB, ROE, D/E NEW)
      Cash Flow     ±10  (CFO sign — sector-aware skip, CF quality)
      Growth        ±10  (YoY preferred, QoQ fallback)
      Market Ctx    ±5
      News          ±5   (symmetric, was 0-10)
      Confluence    ±10  NEW (multi-group agreement bonus)

    Total realistic range: ~-100 to +110 (max ±168 theoretical)
    Thresholds: ≥80 SB | ≥40 BUY | ≥-15 NEUTRAL | ≥-40 SELL | <-40 SS

    Output fields added:
      confidence (HIGH/MEDIUM/LOW)
      pattern_flags (list of: CONSENSUS_BULL, CONSENSUS_BEAR,
                              BULL_TRAP_RISK, VALUE_OPPORTUNITY, MIXED)
    """
    s    = {}
    sigs = []
    market = context.get("market_valuation", "FAIR")
    industry = row.get("industry", "")

    def add(group, pts, reason):
        s[group] = s.get(group, 0) + pts
        sigs.append(f"{reason} {'+' if pts > 0 else ''}{pts}")

    # Volatility filter
    price          = row.get("price") or 1
    atr_pct        = row.get("atr_pct") or 0
    volatility_ok  = atr_pct >= 0.5
    ema_macd_weight = 1.0 if volatility_ok else 0.5

    # ═════════════════════════════════════════════
    # TREND (max ±30) — Phase 2.7: EMA200 included
    # ═════════════════════════════════════════════
    ema20      = row.get("ema20")
    ema50      = row.get("ema50")
    ema200     = row.get("ema200")
    adx        = row.get("adx")
    supertrend = row.get("supertrend")

    # EMA20 vs EMA50 cross (medium-term trend)
    if ema20 and ema50:
        raw_pts = 15 if ema20 > ema50 else -15
        pts     = round(raw_pts * ema_macd_weight)
        label   = "EMA20>EMA50" if ema20 > ema50 else "EMA20<EMA50"
        if not volatility_ok: label += "(flat×0.5)"
        add("trend", pts, label)

    # Price vs EMA200 — MEAN-REVERSION (Phase 2.11 calibrated: spearman -0.055)
    # Backtest: giá xa TRÊN EMA200 → dễ điều chỉnh giảm; xa DƯỚI → dễ bật lên.
    # Dùng % distance để bắt mức độ overextension thay vì chỉ trên/dưới.
    if price and ema200:
        dist_pct = (price - ema200) / ema200 * 100
        if dist_pct > 15:    add("trend", -8, f"Price {dist_pct:.0f}%>EMA200 (overextended)")
        elif dist_pct > 5:   add("trend", -5, f"Price {dist_pct:.0f}%>EMA200 (extended)")
        elif dist_pct < -15: add("trend",  8, f"Price {dist_pct:.0f}%<EMA200 (oversold)")
        elif dist_pct < -5:  add("trend",  5, f"Price {dist_pct:.0f}%<EMA200 (below)")
    elif price and ema20:
        # Fallback nếu chưa đủ 200 ngày (history < 200) — cũng mean-rev
        dist20 = (price - ema20) / ema20 * 100
        if dist20 > 5:    add("trend", -3, "Price>EMA20 extended (no EMA200)")
        elif dist20 < -5: add("trend",  3, "Price<EMA20 (no EMA200)")

    # ADX trend strength
    if adx:
        if adx > 25:
            add("trend", 5, f"ADX={adx} strong")
        elif adx < 20:
            add("trend", 0, f"ADX={adx} sideways")

    # Supertrend
    if supertrend and price:
        if price > supertrend:
            add("trend",  5, f"ST={supertrend} bullish")
        else:
            add("trend", -5, f"ST={supertrend} bearish")

    # ═════════════════════════════════════════════
    # MOMENTUM (max ±23)
    # ═════════════════════════════════════════════
    rsi = row.get("rsi")
    if rsi:
        if rsi < 30:          add("momentum",  15, f"RSI={rsi} oversold")
        elif rsi > 70:        add("momentum", -10, f"RSI={rsi} overbought")
        elif 40 <= rsi <= 60: add("momentum",   5, f"RSI={rsi} neutral")

    macd_hist = row.get("macd_hist")
    if macd_hist is not None:
        raw_pts = 10 if macd_hist > 0 else -10
        pts     = round(raw_pts * ema_macd_weight)
        label   = f"MACD hist={macd_hist}>0" if macd_hist > 0 \
                  else f"MACD hist={macd_hist}<0"
        if not volatility_ok: label += "(flat×0.5)"
        add("momentum", pts, label)

    stoch_k = row.get("stoch_k")
    stoch_d = row.get("stoch_d")
    if stoch_k is not None:
        if stoch_k < 20:   add("momentum",  5, f"Stoch K={stoch_k} oversold")
        elif stoch_k > 80: add("momentum", -5, f"Stoch K={stoch_k} overbought")
        if stoch_k is not None and stoch_d is not None:
            if stoch_k > stoch_d and stoch_k < 80:
                add("momentum",  3, f"Stoch K>{stoch_d} cross up")
            elif stoch_k < stoch_d and stoch_k > 20:
                add("momentum", -3, f"Stoch K<{stoch_d} cross down")

    # ═════════════════════════════════════════════
    # VOLUME (max ±20) — Phase 2.8: add vol_ma_ratio,
    #                    Phase 2.9: remove BB position (moved to Volatility)
    # ═════════════════════════════════════════════
    cmf = row.get("cmf")
    if cmf is not None:
        # MEAN-REVERSION (Phase 2.11 calibrated: spearman -0.043)
        # Inflow mạnh (CMF cao) → đã mua nhiều → dễ điều chỉnh giảm.
        # Outflow mạnh (CMF thấp) → bán quá đà → dễ bật lên.
        if cmf > 0.1:    add("volume", -8, f"CMF={cmf} inflow (overbought)")
        elif cmf < -0.1: add("volume",  8, f"CMF={cmf} outflow (oversold)")

    mfi = row.get("mfi")
    if mfi is not None:
        # TREND-FOLLOWING (Phase 2.11 calibrated: threshold edge +0.58%)
        # Backtest: MFI cao = momentum dòng tiền vào → bullish (KHÔNG mean-rev).
        # Quan hệ phi tuyến — chỉ vùng 40-80 mới predictive theo hướng trend.
        if mfi > 60:   add("volume",  6, f"MFI={mfi} strong inflow")
        elif mfi < 40: add("volume", -6, f"MFI={mfi} weak")

    obv       = row.get("obv")
    ema_cross = row.get("ema_cross_pct")
    if obv is not None and ema_cross is not None:
        if (obv > 0 and ema_cross > 0) or (obv < 0 and ema_cross < 0):
            add("volume",  4, "OBV confirms trend")
        else:
            add("volume", -4, "OBV divergence")

    # Phase 2.8 NEW: Volume MA ratio
    vol_ratio = row.get("vol_ma_ratio")
    if vol_ratio is not None:
        if vol_ratio > 2.0:
            add("volume",  5, f"Vol={vol_ratio}x avg breakout")
        elif vol_ratio > 1.5:
            add("volume",  3, f"Vol={vol_ratio}x avg elevated")
        elif vol_ratio < 0.5:
            add("volume", -3, f"Vol={vol_ratio}x avg weak")

    # ═════════════════════════════════════════════
    # VOLATILITY (max ±5) — Phase 2.9 NEW GROUP
    # ═════════════════════════════════════════════
    bb_pos = row.get("bb_position")
    if bb_pos is not None:
        if bb_pos < 0.2:
            add("volatility",  5, f"BB pos={bb_pos} near lower (oversold)")
        elif bb_pos > 0.8:
            add("volatility", -5, f"BB pos={bb_pos} near upper (overbought)")

    # ═════════════════════════════════════════════
    # ORDER FLOW (max ±10) — Phase 1.3 NEW GROUP
    # ═════════════════════════════════════════════
    sym = row["symbol"]
    of_score, of_sigs = score_order_flow(order_flow_map.get(sym, {}))
    s["order_flow"] = of_score
    sigs.extend(of_sigs)

    # ═════════════════════════════════════════════
    # DEPTH (max ±5) — Phase 3: bid/ask order book
    # ═════════════════════════════════════════════
    d_score, d_sigs = score_depth(row)
    s["depth"] = d_score
    sigs.extend(d_sigs)

    # ═════════════════════════════════════════════
    # FOREIGN FLOW (max ±20)
    # ═════════════════════════════════════════════
    ff_net_5d  = row.get("ff_net_val_5d")
    ff_net_20d = row.get("ff_net_val_20d")
    ff_trend   = row.get("ff_trend")
    ff_accel   = row.get("ff_acceleration")

    if ff_net_5d  is not None:
        add("ff",  5 if ff_net_5d  > 0 else -5,
            "FF net buy 5d" if ff_net_5d > 0 else "FF net sell 5d")
    if ff_net_20d is not None:
        add("ff",  5 if ff_net_20d > 0 else -5,
            "FF net buy 20d" if ff_net_20d > 0 else "FF net sell 20d")
    if ff_trend   is not None:
        add("ff",  5 if ff_trend   > 0 else -5,
            "FF trend accumulating" if ff_trend > 0 else "FF trend distributing")
    if ff_accel   is not None:
        add("ff",  5 if ff_accel   > 0 else -5,
            "FF accelerating" if ff_accel > 0 else "FF decelerating")

    # ═════════════════════════════════════════════
    # FUNDAMENTAL (max ±20) — Phase 1.5: D/E added
    # ═════════════════════════════════════════════
    r_pe = row.get("r_pe")
    r_pb = row.get("r_pb")
    roe  = row.get("r_roe")
    de   = row.get("bs_debt_to_equity")

    # PE
    if r_pe is not None and r_pe > 0:
        if r_pe < 10:    add("fundamental",  10, f"PE={r_pe} very cheap")
        elif r_pe < 15:  add("fundamental",   7, f"PE={r_pe} cheap")
        elif r_pe <= 25: add("fundamental",   3, f"PE={r_pe} fair")
        else:            add("fundamental",  -5, f"PE={r_pe} expensive")
    elif r_pe is not None and r_pe < 0:
        add("fundamental", -5, f"PE={r_pe} negative (loss)")

    # PB
    if r_pb is not None and r_pb > 0:
        if r_pb < 1:     add("fundamental",  5, f"PB={r_pb} below book")
        elif r_pb <= 2:  add("fundamental",  3, f"PB={r_pb} fair")
        elif r_pb <= 3:  add("fundamental",  0, f"PB={r_pb} neutral")
        else:            add("fundamental", -3, f"PB={r_pb} expensive")
    elif r_pb is not None and r_pb < 0:
        add("fundamental", -5, f"PB={r_pb} negative equity")

    # ROE
    if roe:
        if roe > 20:     add("fundamental",  5, f"ROE={roe}% excellent")
        elif roe > 15:   add("fundamental",  3, f"ROE={roe}% good")
        elif roe > 10:   add("fundamental",  0, f"ROE={roe}% neutral")
        elif roe < 5:    add("fundamental", -3, f"ROE={roe}% weak")

    # Phase 1.5 NEW: D/E (skip for banks/insurance — high D/E is normal)
    if de is not None and not _is_sector_match(industry, SECTOR_SKIP_DE):
        if de < 0.3:    add("fundamental",  3, f"D/E={de} very low")
        elif de < 1.0:  add("fundamental",  1, f"D/E={de} healthy")
        elif de < 2.0:  add("fundamental",  0, f"D/E={de} moderate")
        elif de < 3.0:  add("fundamental", -2, f"D/E={de} high")
        else:           add("fundamental", -3, f"D/E={de} very high")

    # ═════════════════════════════════════════════
    # CASH FLOW (max ±10) — Phase 1.4: sector-aware
    # ═════════════════════════════════════════════
    cfo     = row.get("cf_operating")
    cf_qual = row.get("cf_quality_ratio")

    # Sector-aware: skip CFO sign penalty for financials/RE
    skip_cf_sign = _is_sector_match(industry, SECTOR_CF_SKIP_SIGN)

    if cfo is not None:
        if skip_cf_sign:
            # For securities/banks/RE/insurance: don't penalize CFO sign
            # (it's business model dependent, not a quality signal)
            add("cf", 0, f"CFO={cfo:.0f} (sector-skip)")
        else:
            if cfo > 0:
                add("cf",   5, "CFO>0 real cash")
            else:
                add("cf", -10, "CFO<0 cash burn")

    if cf_qual is not None and not skip_cf_sign:
        if cf_qual > 1:     add("cf",  5, f"CF quality={cf_qual} high")
        elif cf_qual < 0.5: add("cf", -5, f"CF quality={cf_qual} low")

    # ═════════════════════════════════════════════
    # GROWTH (max ±10) — Phase 1.1: prefer YoY
    # ═════════════════════════════════════════════
    # Prefer YoY (less seasonal noise) over QoQ
    rev_g_yoy  = row.get("is_rev_growth_yoy")
    rev_g_qoq  = row.get("is_rev_growth")
    np_g_yoy   = row.get("is_profit_growth_yoy")
    np_g_qoq   = row.get("is_profit_growth")

    # FIX 2026-06-03: NaN khác None — pd.notna() lọc cả None lẫn NaN.
    # Trước đây NaN lọt qua "is not None" → chấm -1 với label "nan%" (sai).
    rev_g_yoy  = rev_g_yoy if pd.notna(rev_g_yoy) else None
    rev_g_qoq  = rev_g_qoq if pd.notna(rev_g_qoq) else None
    np_g_yoy   = np_g_yoy  if pd.notna(np_g_yoy)  else None
    np_g_qoq   = np_g_qoq  if pd.notna(np_g_qoq)  else None

    rev_g     = rev_g_yoy if rev_g_yoy is not None else rev_g_qoq
    rev_label = "RevG-YoY" if rev_g_yoy is not None else "RevG-QoQ"
    np_g     = np_g_yoy if np_g_yoy is not None else np_g_qoq
    np_label = "ProfitG-YoY" if np_g_yoy is not None else "ProfitG-QoQ"

    if rev_g is not None:
        if rev_g > 0.20:    add("growth",  5, f"{rev_label}={rev_g:.1%} strong")
        elif rev_g > 0.10:  add("growth",  3, f"{rev_label}={rev_g:.1%} good")
        elif rev_g > 0:     add("growth",  1, f"{rev_label}={rev_g:.1%} positive")
        elif rev_g < -0.10: add("growth", -3, f"{rev_label}={rev_g:.1%} declining")
        else:               add("growth", -1, f"{rev_label}={rev_g:.1%} slight decline")

    if np_g is not None:
        if np_g > 0.20:    add("growth",  5, f"{np_label}={np_g:.1%} strong")
        elif np_g > 0.10:  add("growth",  3, f"{np_label}={np_g:.1%} good")
        elif np_g > 0:     add("growth",  1, f"{np_label}={np_g:.1%} positive")
        elif np_g < -0.10: add("growth", -3, f"{np_label}={np_g:.1%} declining")
        else:              add("growth", -1, f"{np_label}={np_g:.1%} slight decline")

    # ═════════════════════════════════════════════
    # MARKET CONTEXT (max ±5) — REGIME-AWARE (2026-06-03)
    # Kết hợp valuation (đắt/rẻ) + regime (xu hướng VNINDEX).
    # Lý do: "rẻ trong downtrend" = bẫy giá trị (bắt dao rơi) → KHÔNG thưởng.
    #        "giảm sâu" = rủi ro hệ thống → phạt điểm bất kể valuation.
    # Ma trận:
    #                 UPTREND  SIDEWAYS  DOWNTREND  DEEP_DOWN
    #   CHEAP           +5        +3         0          -2
    #   FAIR            +2         0        -2          -4
    #   EXPENSIVE       -2        -3        -4          -5
    # regime=UNKNOWN (API fail) → fallback valuation thuần (CHEAP+5/EXP-5).
    # ═════════════════════════════════════════════
    regime = context.get("market_regime", "UNKNOWN")

    CONTEXT_MATRIX = {
        "CHEAP":     {"UPTREND": 5, "SIDEWAYS": 3, "DOWNTREND":  0, "DEEP_DOWN": -2},
        "FAIR":      {"UPTREND": 2, "SIDEWAYS": 0, "DOWNTREND": -2, "DEEP_DOWN": -4},
        "EXPENSIVE": {"UPTREND": -2,"SIDEWAYS": -3,"DOWNTREND": -4, "DEEP_DOWN": -5},
    }

    if regime == "UNKNOWN":
        # Fallback: valuation thuần như logic cũ (không có data trend)
        if market == "CHEAP":       add("context",  5, "Market CHEAP")
        elif market == "EXPENSIVE": add("context", -5, "Market EXPENSIVE")
        else:                       add("context",  0, "Market FAIR")
    else:
        pts = CONTEXT_MATRIX.get(market, CONTEXT_MATRIX["FAIR"]).get(regime, 0)
        regime_vn = {
            "UPTREND": "uptrend", "SIDEWAYS": "sideways",
            "DOWNTREND": "downtrend", "DEEP_DOWN": "giam sau",
        }.get(regime, regime)
        add("context", pts, f"Market {market}+{regime_vn}")

    # ═════════════════════════════════════════════
    # NEWS (max ±5) — Phase 1.2 symmetric
    # ═════════════════════════════════════════════
    ns         = news_scores.get(sym, {})
    news_score = float(ns.get("total", 0.0))
    news_score = round(max(-5.0, min(5.0, news_score)), 2)

    if news_score >= 3:    news_label = "News VERY_POS"
    elif news_score >= 1:  news_label = "News POS"
    elif news_score > -1:  news_label = "News NEUTRAL"
    elif news_score > -3:  news_label = "News NEG"
    else:                  news_label = "News VERY_NEG"

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

    sigs.append(f"{news_label} {'+' if news_score > 0 else ''}{news_score} {art_hint}")

    # ═════════════════════════════════════════════
    # Apply caps to each group
    # ═════════════════════════════════════════════
    trend_score       = max(-30, min(30, s.get("trend",       0)))
    momentum_score    = max(-23, min(23, s.get("momentum",    0)))
    volume_score      = max(-20, min(20, s.get("volume",      0)))
    volatility_score  = max(-5,  min(5,  s.get("volatility",  0)))
    depth_score       = max(-5,  min(5,  s.get("depth",       0)))
    order_flow_score  = max(-10, min(10, s.get("order_flow",  0)))
    ff_score          = max(-20, min(20, s.get("ff",          0)))
    fundamental_score = max(-20, min(20, s.get("fundamental", 0)))
    cf_score          = max(-10, min(10, s.get("cf",          0)))
    growth_score      = max(-10, min(10, s.get("growth",      0)))
    context_score     = max(-5,  min(5,  s.get("context",     0)))
    news_score_final  = news_score

    # ═════════════════════════════════════════════
    # CONFLUENCE BONUS (max ±10) — Phase 1.6
    # Reward when multiple INDEPENDENT groups agree.
    # ═════════════════════════════════════════════
    # Count scoreable independent groups (skip context which is macro-only)
    group_scores = {
        "trend": trend_score, "momentum": momentum_score,
        "volume": volume_score, "volatility": volatility_score,
        "order_flow": order_flow_score, "depth": depth_score, "ff": ff_score,
        "fundamental": fundamental_score, "cf": cf_score,
        "growth": growth_score, "news": news_score_final,
    }

    # Threshold for "meaningful" signal: ≥ 30% of group cap
    SIGNAL_THRESHOLD_PCT = 0.30
    GROUP_CAPS = {
        "trend": 30, "momentum": 23, "volume": 20, "volatility": 5,
        "order_flow": 10, "depth": 5, "ff": 20, "fundamental": 20,
        "cf": 10, "growth": 10, "news": 5,
    }

    positive_groups = 0
    negative_groups = 0
    for g, score in group_scores.items():
        cap = GROUP_CAPS[g]
        if score >= cap * SIGNAL_THRESHOLD_PCT:
            positive_groups += 1
        elif score <= -cap * SIGNAL_THRESHOLD_PCT:
            negative_groups += 1

    confluence_bonus = 0
    confluence_label = ""
    if positive_groups >= 7:
        confluence_bonus = 10
        confluence_label = f"CONFLUENCE strong bull ({positive_groups}/10 groups)"
    elif positive_groups >= 5:
        confluence_bonus = 5
        confluence_label = f"CONFLUENCE bull ({positive_groups}/10 groups)"
    elif negative_groups >= 7:
        confluence_bonus = -10
        confluence_label = f"CONFLUENCE strong bear ({negative_groups}/10 groups)"
    elif negative_groups >= 5:
        confluence_bonus = -5
        confluence_label = f"CONFLUENCE bear ({negative_groups}/10 groups)"

    if confluence_bonus != 0:
        sigs.append(f"{confluence_label} {'+' if confluence_bonus > 0 else ''}{confluence_bonus}")

    # ═════════════════════════════════════════════
    # TOTAL SCORE
    # ═════════════════════════════════════════════
    total = (trend_score + momentum_score + volume_score + volatility_score +
             order_flow_score + depth_score + ff_score + fundamental_score + cf_score +
             growth_score + context_score + news_score_final + confluence_bonus)

    # ═════════════════════════════════════════════
    # DECISION (recalibrated for new max range)
    # ═════════════════════════════════════════════
    if total >= 80:    decision = "STRONG BUY"
    elif total >= 40:  decision = "BUY"
    elif total >= -15: decision = "NEUTRAL"
    elif total >= -40: decision = "SELL"
    else:              decision = "STRONG SELL"

    # ═════════════════════════════════════════════
    # CONFIDENCE + PATTERN FLAGS — Phase 2.10
    # ═════════════════════════════════════════════
    # Technical vs Fundamental alignment check
    tech_score = (trend_score + momentum_score + volume_score +
                  volatility_score + order_flow_score)
    fund_score = fundamental_score + cf_score + growth_score

    pattern_flags = []
    confidence = "MEDIUM"

    # Bull-trap risk: tech strong + fund weak
    if tech_score >= 40 and fund_score <= -15:
        pattern_flags.append("BULL_TRAP_RISK")
        confidence = "LOW"
    # Value opportunity: tech weak + fund strong
    elif tech_score <= -30 and fund_score >= 15:
        pattern_flags.append("VALUE_OPPORTUNITY")
        confidence = "MEDIUM"
    # Strong consensus (both confirm)
    elif tech_score >= 30 and fund_score >= 15:
        pattern_flags.append("CONSENSUS_BULL")
        confidence = "HIGH"
    elif tech_score <= -30 and fund_score <= -15:
        pattern_flags.append("CONSENSUS_BEAR")
        confidence = "HIGH"
    # Mixed but neither extreme
    elif abs(tech_score) < 20 and abs(fund_score) < 10:
        pattern_flags.append("UNCLEAR")
        confidence = "LOW"

    # ═════════════════════════════════════════════
    # Output
    # ═════════════════════════════════════════════
    out = dict(row)
    out.update({
        "market_valuation"    : market,
        "atr_pct"             : row.get("atr_pct"),
        "trend_score"         : trend_score,
        "momentum_score"      : momentum_score,
        "volume_score"        : volume_score,
        "volatility_score"    : volatility_score,    # NEW
        "order_flow_score"    : order_flow_score,    # NEW
        "depth_score"         : depth_score,          # Phase 3
        "ff_score"            : ff_score,
        "fundamental_score"   : fundamental_score,
        "cf_score"            : cf_score,
        "growth_score"        : growth_score,
        "context_score"       : context_score,
        "news_score"          : news_score_final,
        "confluence_bonus"    : confluence_bonus,    # NEW
        "tech_score"          : tech_score,          # NEW (computed)
        "fund_score"          : fund_score,          # NEW (computed)
        "news_industry"       : ns.get("industry", 0.0),
        "news_mention"        : ns.get("mention",  0.0),
        "news_macro"          : ns.get("macro",    0.0),
        "news_evidence"       : evidence,
        "total_score"         : total,
        "decision"            : decision,
        "confidence"          : confidence,           # NEW
        "pattern_flags"       : pattern_flags,        # NEW
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
    order_flow  = load_json("order_flow.json")    # Phase 1.3 NEW input
    ctx         = context[0] if context else {}

    if not deep_raw:
        log.error("deep_raw.json not found")
        import sys; sys.exit(1)

    if today_index is None:
        log.warning("news_today_index.json not found — news_score = neutral (0)")

    if order_flow is None:
        log.warning("order_flow.json not found — order_flow_score = 0 (run step_order_flow trước)")
        order_flow = []

    # Build symbol → order_flow_data map
    order_flow_map = {}
    if isinstance(order_flow, list):
        for r in order_flow:
            if isinstance(r, dict) and r.get("symbol"):
                order_flow_map[r["symbol"]] = r

    symbols_with_industry = [
        {"symbol": r["symbol"], "icb_name": r.get("industry", "")}
        for r in deep_raw
    ]
    news_scores = build_news_scores(today_index or {}, symbols_with_industry)

    log.info(f"Scoring {len(deep_raw)} symbols (order_flow={len(order_flow_map)} entries)...")

    scored_rows = []
    for row in deep_raw:
        result = score_symbol(row, ctx, news_scores, order_flow_map)
        scored_rows.append(result)

        flags_str = ",".join(result.get("pattern_flags", [])) or "-"
        log.info(
            f"  [{result['symbol']}] "
            f"score={result['total_score']:.2f} "
            f"(T={result['trend_score']} M={result['momentum_score']} "
            f"V={result['volume_score']} Vol={result['volatility_score']} "
            f"OF={result['order_flow_score']} "
            f"FF={result['ff_score']} F={result['fundamental_score']} "
            f"CF={result['cf_score']} G={result['growth_score']} "
            f"N={result['news_score']:.1f} "
            f"Conf={result['confluence_bonus']}) "
            f"→ {result['decision']} [{result['confidence']}] [{flags_str}]"
        )

    df_signals = pd.DataFrame(scored_rows)

    # signals.json
    save_json("signals.json", df_signals.to_dict(orient="records"))

    # signals.csv
    news_evidence_col = df_signals["news_evidence"].apply(
        lambda evs: " | ".join(
            f"{e.get('type','?')}·"
            f"{e.get('source','?')}·"
            f"{e.get('title','')[:40]}·"
            f"{str(e.get('time',''))[5:16]}·"
            f"{e.get('contribution', 0):+.2f}"
            f"{' eff:'+e['effective_date'] if e.get('effective_date') else ''}"
            for e in (evs or [])
        )
    ) if "news_evidence" in df_signals.columns else pd.Series([""] * len(df_signals))

    pattern_flags_col = df_signals["pattern_flags"].apply(
        lambda f: ",".join(f or [])
    ) if "pattern_flags" in df_signals.columns else pd.Series([""] * len(df_signals))

    df_for_csv = df_signals.drop(
        columns=["news_evidence", "_ohlcv_5d", "pattern_flags"],
        errors="ignore")
    df_csv     = clean_for_export(df_for_csv)
    df_csv["news_evidence"]  = news_evidence_col.values
    df_csv["pattern_flags"]  = pattern_flags_col.values
    save_csv("signals.csv", df_csv)

    # signals_display.csv
    display_cols = [c for c in df_signals.columns
                    if c in INDICATORS_META and c != "_ohlcv_5d"]
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

    # Decision distribution log
    decision_counts = df_signals["decision"].value_counts().to_dict()
    confidence_counts = df_signals["confidence"].value_counts().to_dict()
    log.info(f"Decision distribution: {decision_counts}")
    log.info(f"Confidence distribution: {confidence_counts}")

    log.info(
        f"Exported {len(df_signals)} rows, "
        f"{len(df_signals.columns)} cols total, "
        f"{len(display_cols)} cols in display"
    )
    log.info("=== SCORING DONE ===")
