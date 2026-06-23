"""
step_scoring_v2.py — Scoring engine v2 (Weighted Normalized + Extended Indicators)
====================================================================================
Chạy SONG SONG với step_scoring.py (v3). KHÔNG thay thế v3.

THAY ĐỔI SO VỚI V3:
  1. Normalize từng group về [-1, +1]: score_norm = raw_score / cap
  2. Weighted sum → total_score ∈ [-100, +100]
  3. Weight phản ánh IC thực tế T+30 thị trường VN (technical dominant)
  4. Fundamental/CF/Growth vẫn có score 2 chiều đầy đủ — weight nhỏ hơn
  5. Threshold mới: ≥50 STRONG BUY | ≥25 BUY | ≥-10 NEUTRAL | ≥-25 SELL
  6. Output: v2f_signals.json / v2f_signals.csv
  7. Bỏ news group — weight phân bổ lại

EXTENDED INDICATORS (không có trong V3):
  Trend group:       + RS vs VNINDEX (20d relative strength)
                     + 52W High proximity / breakout
  Momentum group:    + ROC(10) — rate of change 10 ngày
  Volatility group:  + NR7 setup — narrow range breakout setup
  Depth group:       + Bid/Ask aggregate imbalance
  FF group:          + Foreign room utilization
  Fundamental group: + Dividend yield score
  Growth group:      + EPS consistency (N quý liên tiếp tăng)

CHANGELOG:
  2026-06-11 — v2 initial: normalized weighted scoring
  2026-06-11 — v2.1: thêm 9 extended indicators, bỏ news group
  2026-06-14 — v2.2: gắn daily change từ ranking.json (chg_pct_1d, chg_abs_vnd,
                     accumulated_value) vào mỗi signal row cho dashboard
  2026-06-16 — v2.1 STANDALONE: bỏ import từ step_scoring (v3). Inline toàn bộ
                     base scoring (SECTOR rules, news, order_flow, depth,
                     _score_base) để KHÔNG còn phụ thuộc v3 khi chấm điểm.
                     + FIX bug ADX direction-blind (Phase 2.12), áp PRE-CAP:
                       ADX>25 không còn cộng +5 vô điều kiện; gắn hướng EMA200
                       (giá>EMA200 → -5 mean-rev short | giá<EMA200 → +5 long).
                     SCORING_VERSION bump "v2" → "v2.1" để tách performance.
  2026-06-18 — v2.2 HƯỚNG A: thêm 6 chỉ số library vnstock_ta vào scoring.
                     Snapshot fetch zero new API (diag verified 2026-06-17):
                       Trend group   +8 cap: linreg(±3) + aroon(±3) + donchian(±2)
                       Volume group  +5 cap: ad_line vs 20d(±2) + efi(±3)
                       Momentum group+3 cap: willr(±3)
                     GROUP_CAPS bump trend 45→53, momentum 26→29, volume 20→25.
                     Output thêm 6 ext_*_score fields.
                     SCORING_VERSION bump "v2.1" → "v2.2" để tách performance.
  2026-06-21 — v2.3 FIX 4 lỗi điểm (review trước forward-validation):
                     #1 FF: gộp 4 tín hiệu cộng-tuyến → 2; thêm dead-band cường độ
                        0.10 (net/turnover) + magnitude. FF base max ±20 → ±15.
                     #2 Trend: thuần trend-following (Option A) — bỏ phạt
                        overextended EMA200; ADX>25 XÁC NHẬN hướng thay vì mean-rev
                        (sửa lỗi nhóm trend tự triệt tiêu & thưởng điểm downtrend).
                     #3 score_ff_room: guard total_room<=0 / available<0 → 0
                        (hết phạt -7 oan cho mã không có room cap, vd TTA/CIG/RYG).
                     #5 score_dividend_yield: bỏ heuristic <1.0 ×100 (r_div_yield
                        đã là %) → hết lỗi yield 0.8% bị đọc thành 80%.
                     SCORING_VERSION bump "v2.2" → "v2.3" để tách performance.
                     Lưu ý: GROUP_CAPS/WEIGHTS giữ nguyên (KHÔNG re-tune trong lần này).
  2026-06-23 — FIX dashboard: refactor v2.2→v2.3 làm RƠI bước enrichment _of_*.
                     Order flow vẫn fetch + ghi v2f_order_flow.json đầy đủ (log
                     "0 with errors", 40/40 mã có pattern/buy_ratio), nhưng
                     score_symbol_v2() chỉ dùng summary để tính order_flow_score
                     rồi vứt → v2f_signals.json mất _of_pattern/_of_buy_vol/... →
                     block "🔄 LỰC KHỚP LỆNH" trên indexv2.html hiển thị 0cp /
                     không pattern (trông như không có lực khớp, kể cả trong giờ GD).
                     Thêm _attach_order_flow() gọi trong main loop.
                     CHỈ passthrough hiển thị — KHÔNG đụng scoring math/caps/weights/
                     total_score → KHÔNG bump SCORING_VERSION (giữ "v2.3") để
                     forward-validation buckets không bị tách oan.
"""
# FORK V2F: đọc v2f_deep_raw + v2f_order_flow + v2f_ranking + context/news/industry_map (dùng chung) → ghi v2f_signals.{json,csv}.
import math
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

os.environ["VNSTOCK_INTERACTIVE"] = "0"
os.environ["VNSTOCK_LANGUAGE"]    = "en"
os.environ["MPLCONFIGDIR"]        = "/home/runner/.config/matplotlib"

import logging
import pandas as pd

from utils.helpers   import now_ict, today_str
from utils.cache     import load_json, save_json, save_csv
from utils.formatter import clean_for_export

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(levelname)s %(message)s'
)
log = logging.getLogger(__name__)

# =====================================================
# V2 CONFIG
# =====================================================

SCORING_VERSION = "v2.3"   # FIX 4 lỗi điểm: FF dead-band+gộp, trend thuần TF, ff_room guard, div yield

# Cap cho từng group — extended caps cho groups có chỉ số mới
GROUP_CAPS = {
    "trend":        53,   # v2.1=45; v2.2 +8 (linreg ±3 + aroon ±3 + donchian ±2)
    "momentum":     29,   # v2.1=26; v2.2 +3 (willr ±3)
    "volume":       25,   # v2.1=20; v2.2 +5 (ad ±2 + efi ±3)
    "volatility":    8,
    "order_flow":   10,
    "depth":         7,
    "ff":           27,
    "fundamental":  29,
    "cf":           10,
    "growth":       15,
    "context":       9,
    "smart_money":  20,
    # news: bỏ
}

# Weight — bỏ news (4%), phân bổ lại
SCORING_WEIGHTS = {
    "trend":        0.20,   # RS + 52W + EMA
    "momentum":     0.13,   # RSI + MACD + ROC
    "volume":       0.10,
    "order_flow":   0.08,
    "volatility":   0.04,
    "depth":        0.04,
    "ff":           0.11,   # giảm: nhường smart_money
    "context":      0.04,
    "fundamental":  0.08,   # tăng: fair value + div yield
    "cf":           0.05,
    "growth":       0.06,   # EPS consistency
    "smart_money":  0.07,   # NEW: prop trade + insider
    # news: bỏ
}
# Tổng = 1.00
assert abs(sum(SCORING_WEIGHTS.values()) - 1.0) < 1e-9, \
    f"Weights sum = {sum(SCORING_WEIGHTS.values()):.4f} ≠ 1.0"

CONFLUENCE_THRESHOLD_PCT = 0.30
THRESHOLD_STRONG_BUY  =  50
THRESHOLD_BUY         =  25
THRESHOLD_NEUTRAL     = -10
THRESHOLD_SELL        = -25


# ══════════════════════════════════════════════════════════════════════════
# V3 BASE (INLINED) — copy nguyên văn từ step_scoring.py để standalone.
# KHÔNG import step_scoring. Khác v3 DUY NHẤT: ADX fix (Phase 2.12) pre-cap.
# ══════════════════════════════════════════════════════════════════════════

# ─── SECTOR-AWARE RULES ────────────────────────────────────────────────────
SECTOR_CF_SKIP_SIGN = {
    "Ngân hàng",
    "Dịch vụ tài chính",
    "Bảo hiểm",
    "Bất động sản",
}
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


# ─── NEWS SCORING (symmetric -5..+5) ───────────────────────────────────────
def build_news_scores(today_index: dict, symbols_with_industry: list) -> dict:
    NEUTRAL_TOTAL = 0.0
    NEUTRAL_IND   = 0.0
    NEUTRAL_MAC   = 0.0

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

    macro_score_raw = float(macro_data.get("score", 1.0))
    macro_score     = macro_score_raw - 1.0

    result = {}
    for item in symbols_with_industry:
        sym = item["symbol"]
        ind = item.get("icb_name") or item.get("industry") or ""

        ind_data      = by_industry.get(ind, {})
        ind_score_raw = float(ind_data.get("score", 2.0))
        ind_score     = ind_score_raw - 2.0

        sym_data      = symbol_mentions.get(sym, {})
        sym_score_raw = float(sym_data.get("score", 2.0))
        sym_score     = sym_score_raw - 2.0

        total = round(ind_score + sym_score + macro_score, 2)
        total = max(-5.0, min(5.0, total))

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


# ─── ORDER FLOW SCORING ────────────────────────────────────────────────────
ORDER_FLOW_PATTERN_SCORES = {
    "ACCUMULATION":          +5,
    "SPIKE_BUY":             +5,
    "INSTITUTIONAL_ACTIVITY": 0,
    "NORMAL":                 0,
    "FLAT":                   0,
    "CONTENTION":             0,
    "WEAK":                  -3,
    "DISTRIBUTION":          -5,
    "SPIKE_SELL":            -5,
    "ERROR":                  0,
    "INSUFFICIENT_DATA":      0,
}


def score_order_flow(of_data: dict) -> tuple:
    if not of_data:
        return 0, []

    summary = of_data.get("summary", {}) if isinstance(of_data, dict) else {}
    pattern   = summary.get("pattern", "")
    buy_ratio = summary.get("buy_ratio_today")
    vol_spike = summary.get("vol_spike_pct")

    of_score = 0
    sigs     = []

    pattern_pts = ORDER_FLOW_PATTERN_SCORES.get(pattern, 0)
    if pattern_pts != 0:
        of_score += pattern_pts
        sigs.append(f"OF pattern={pattern} {'+' if pattern_pts > 0 else ''}{pattern_pts}")

    if pattern == "INSTITUTIONAL_ACTIVITY":
        if buy_ratio is not None:
            if buy_ratio > 0.55:
                of_score += 3
                sigs.append("OF institutional buying +3")
            elif buy_ratio < 0.45:
                of_score -= 3
                sigs.append("OF institutional selling -3")

    if vol_spike is not None and vol_spike > 100:
        if buy_ratio is not None:
            if buy_ratio > 0.60:
                of_score += 3
                sigs.append(f"OF vol+{vol_spike:.0f}% buy {buy_ratio:.2f}")
            elif buy_ratio < 0.40:
                of_score -= 3
                sigs.append(f"OF vol+{vol_spike:.0f}% sell {buy_ratio:.2f}")

    of_score = max(-10, min(10, of_score))
    return of_score, sigs


# ─── DEPTH SCORING (Phase 3) ───────────────────────────────────────────────
WALL_MIN_VOL = 5_000


def _ob_valid(v) -> bool:
    if v is None:
        return False
    try:
        f = float(v)
        return not math.isnan(f) and f > 0
    except (TypeError, ValueError):
        return False


def score_depth(row: dict) -> tuple:
    cur_price = row.get("price")
    if not cur_price or float(cur_price) <= 0:
        return 0, []
    cur = float(cur_price)

    bids_all = []
    asks_all = []
    for i in (1, 2, 3):
        bp = row.get(f"bid_price_{i}")
        bv = row.get(f"bid_vol_{i}")
        ap = row.get(f"ask_price_{i}")
        av = row.get(f"ask_vol_{i}")
        if _ob_valid(bp) and _ob_valid(bv):
            bids_all.append((float(bp) / 1000, float(bv)))
        if _ob_valid(ap) and _ob_valid(av):
            asks_all.append((float(ap) / 1000, float(av)))

    if not bids_all and not asks_all:
        return 0, []

    bid_walls = [(p, v) for p, v in bids_all if v >= WALL_MIN_VOL]
    ask_walls = [(p, v) for p, v in asks_all if v >= WALL_MIN_VOL]

    depth_score = 0
    sigs = []

    ask_count = len(ask_walls)
    if ask_count >= 2:
        depth_score -= 3
        sigs.append(f"AskWall x{ask_count} mức ≥5K cp -3")
    elif ask_count == 1:
        p, v = ask_walls[0]
        pct = (p - cur) / cur * 100
        if pct <= 2.0:
            depth_score -= 2
            sigs.append(f"AskWall {p:.2f} ({v/1000:.0f}K cp, +{pct:.1f}%) -2")
        else:
            depth_score -= 1
            sigs.append(f"AskWall {p:.2f} ({v/1000:.0f}K cp, +{pct:.1f}%) -1")
    else:
        depth_score += 1
        sigs.append("AskClear (no wall) +1")

    bid_count = len(bid_walls)
    if bid_count >= 2:
        depth_score += 2
        sigs.append(f"BidWall x{bid_count} mức ≥5K cp +2")
    elif bid_count == 1:
        p, v = bid_walls[0]
        pct = (cur - p) / cur * 100
        depth_score += 1
        sigs.append(f"BidWall {p:.2f} ({v/1000:.0f}K cp, -{pct:.1f}%) +1")
    else:
        depth_score -= 1
        sigs.append("NoBidWall -1")

    depth_score = max(-5, min(5, depth_score))
    return depth_score, sigs


def _score_base(row: dict, context: dict, news_scores: dict,
                order_flow_map: dict) -> dict:
    """
    Base scoring v3 inlined cho V2 standalone. KHÔNG import từ step_scoring.
    Khác v3 DUY NHẤT: bug ADX direction-blind đã sửa (Phase 2.12), áp PRE-CAP.
    """
    s    = {}
    sigs = []
    market = context.get("market_valuation", "FAIR")
    industry = row.get("industry", "")

    def add(group, pts, reason):
        s[group] = s.get(group, 0) + pts
        sigs.append(f"{reason} {'+' if pts > 0 else ''}{pts}")

    price           = row.get("price") or 1
    atr_pct         = row.get("atr_pct") or 0
    volatility_ok   = atr_pct >= 0.5
    ema_macd_weight = 1.0 if volatility_ok else 0.5

    # ── TREND (max ±30) ──
    ema20      = row.get("ema20")
    ema50      = row.get("ema50")
    ema200     = row.get("ema200")
    adx        = row.get("adx")
    supertrend = row.get("supertrend")

    if ema20 and ema50:
        raw_pts = 15 if ema20 > ema50 else -15
        pts     = round(raw_pts * ema_macd_weight)
        label   = "EMA20>EMA50" if ema20 > ema50 else "EMA20<EMA50"
        if not volatility_ok:
            label += "(flat×0.5)"
        add("trend", pts, label)

    # v2.3 FIX #2: nhóm trend trước đây TRỘN thuận-xu-hướng (EMA cross/Supertrend)
    #   với đảo-chiều (phạt overextended EMA200, ADX mean-rev) → tự triệt tiêu,
    #   mất sức phân biệt, có lúc THƯỞNG điểm cho downtrend. Chuyển sang THUẦN
    #   trend-following (Option A): trên EMA200 = cộng, dưới = trừ; ADX>25 XÁC NHẬN
    #   hướng hiện tại thay vì fade. (Ý "overextended/quá đà" tách thành qualifier
    #   riêng sau, KHÔNG nằm trong nhóm trend.)
    if price and ema200:
        dist_pct = (price - ema200) / ema200 * 100
        if   dist_pct > 5:    add("trend",  5, f"Giá {dist_pct:.0f}%>EMA200 (uptrend dài hạn)")
        elif dist_pct > 0:    add("trend",  3, f"Giá {dist_pct:.0f}%>EMA200 (trên xu hướng)")
        elif dist_pct > -5:   add("trend", -3, f"Giá {dist_pct:.0f}%<EMA200 (dưới xu hướng)")
        else:                 add("trend", -5, f"Giá {dist_pct:.0f}%<EMA200 (downtrend dài hạn)")
    elif price and ema20:
        dist20 = (price - ema20) / ema20 * 100
        if   dist20 > 0:  add("trend",  3, "Giá>EMA20 (no EMA200)")
        elif dist20 < 0:  add("trend", -3, "Giá<EMA20 (no EMA200)")

    # ADX>25 = xu hướng MẠNH → xác nhận hướng theo EMA200 (trend-following)
    if adx and adx > 25:
        if price and ema200:
            if price > ema200:
                add("trend",  5, f"ADX={adx} mạnh + giá>EMA200 (uptrend xác nhận)")
            else:
                add("trend", -5, f"ADX={adx} mạnh + giá<EMA200 (downtrend xác nhận)")
        else:
            sigs.append(f"ADX={adx} strong (no EMA200, skip) +0")

    if supertrend and price:
        if price > supertrend:
            add("trend",  5, f"ST={supertrend} bullish")
        else:
            add("trend", -5, f"ST={supertrend} bearish")

    # ── MOMENTUM (max ±23) ──
    rsi = row.get("rsi")
    if rsi:
        if rsi < 30:          add("momentum",  15, f"RSI={rsi} oversold")
        elif rsi > 70:        add("momentum", -10, f"RSI={rsi} overbought")
        elif 40 <= rsi <= 60: add("momentum",   5, f"RSI={rsi} neutral")

    macd_hist = row.get("macd_hist")
    if macd_hist is not None:
        raw_pts = 10 if macd_hist > 0 else -10
        pts     = round(raw_pts * ema_macd_weight)
        label   = f"MACD hist={macd_hist}>0" if macd_hist > 0 else f"MACD hist={macd_hist}<0"
        if not volatility_ok:
            label += "(flat×0.5)"
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

    # ── VOLUME (max ±20) ──
    cmf = row.get("cmf")
    if cmf is not None:
        if cmf > 0.1:    add("volume", -8, f"CMF={cmf} inflow (overbought)")
        elif cmf < -0.1: add("volume",  8, f"CMF={cmf} outflow (oversold)")

    mfi = row.get("mfi")
    if mfi is not None:
        if mfi > 60:   add("volume",  6, f"MFI={mfi} strong inflow")
        elif mfi < 40: add("volume", -6, f"MFI={mfi} weak")

    obv       = row.get("obv")
    ema_cross = row.get("ema_cross_pct")
    if obv is not None and ema_cross is not None:
        if (obv > 0 and ema_cross > 0) or (obv < 0 and ema_cross < 0):
            add("volume",  4, "OBV confirms trend")
        else:
            add("volume", -4, "OBV divergence")

    vol_ratio = row.get("vol_ma_ratio")
    if vol_ratio is not None:
        if vol_ratio > 2.0:   add("volume",  5, f"Vol={vol_ratio}x avg breakout")
        elif vol_ratio > 1.5: add("volume",  3, f"Vol={vol_ratio}x avg elevated")
        elif vol_ratio < 0.5: add("volume", -3, f"Vol={vol_ratio}x avg weak")

    # ── VOLATILITY (max ±5) ──
    bb_pos = row.get("bb_position")
    if bb_pos is not None:
        if bb_pos < 0.2:   add("volatility",  5, f"BB pos={bb_pos} near lower (oversold)")
        elif bb_pos > 0.8: add("volatility", -5, f"BB pos={bb_pos} near upper (overbought)")

    # ── ORDER FLOW (max ±10) ──
    sym = row["symbol"]
    of_score, of_sigs = score_order_flow(order_flow_map.get(sym, {}))
    s["order_flow"] = of_score
    sigs.extend(of_sigs)

    # ── DEPTH (max ±5) ──
    d_score, d_sigs = score_depth(row)
    s["depth"] = d_score
    sigs.extend(d_sigs)

    # ── FOREIGN FLOW (max ±15 từ base; +room ±3 ở extended) ──
    # v2.3 FIX #1: 4 tín hiệu cũ (net5d/net20d/trend/accel) đều phái sinh từ CÙNG
    #   một chuỗi net → cộng tuyến, chấm THUẦN DẤU, không biên trung tính →
    #   1 biến gốc chi phối ±20 và dễ flip dấu do nhiễu phiên.
    #   Sửa: gộp 4 → 2 tín hiệu, thêm DEAD-BAND theo cường độ, có MAGNITUDE.
    #     (a) Lập trường ròng (±10/±5/0): intensity = net_5d / (buy_5d+sell_5d).
    #         |intensity| < 0.10 → trung tính (0). |intensity| ≥ 0.30 VÀ 5d/20d
    #         cùng chiều → mạnh (±10); còn lại có hướng → vừa (±5).
    #     (b) Động lượng dòng tiền (±5): trend & accel CÙNG dấu mới tính.
    ff_net_5d  = row.get("ff_net_val_5d")
    ff_net_20d = row.get("ff_net_val_20d")
    ff_buy_5d  = row.get("ff_buy_val_5d")
    ff_sell_5d = row.get("ff_sell_val_5d")
    ff_trend   = row.get("ff_trend")
    ff_accel   = row.get("ff_acceleration")

    FF_DEADBAND = 0.10   # |net|/turnover dưới mức này coi như nhiễu → 0
    FF_STRONG   = 0.30   # cường độ mạnh

    if ff_net_5d is not None:
        turnover  = abs(ff_buy_5d or 0) + abs(ff_sell_5d or 0)
        intensity = (ff_net_5d / turnover) if turnover > 0 else 0.0
        # (a) lập trường ròng — dead-band + magnitude
        if abs(intensity) < FF_DEADBAND:
            sigs.append(f"FF net trung tính (intensity={intensity:+.2f}) +0")
        else:
            aligned_20d = (ff_net_20d is not None
                           and (ff_net_20d > 0) == (ff_net_5d > 0))
            sign = 1 if ff_net_5d > 0 else -1
            mag  = 10 if (abs(intensity) >= FF_STRONG and aligned_20d) else 5
            dir_txt = "buy" if sign > 0 else "sell"
            extra   = " (5d/20d aligned)" if aligned_20d else ""
            add("ff", sign * mag,
                f"FF net {dir_txt} intensity={intensity:+.2f}{extra}")
        # (b) động lượng dòng tiền — chỉ tính khi trend & accel CÙNG dấu
        if ff_trend is not None and ff_accel is not None:
            if   ff_trend > 0 and ff_accel > 0:
                add("ff",  5, "FF flow tăng tốc (trend+accel cùng dương)")
            elif ff_trend < 0 and ff_accel < 0:
                add("ff", -5, "FF flow giảm tốc (trend+accel cùng âm)")

    # ── FUNDAMENTAL (max ±20) ──
    r_pe = row.get("r_pe")
    r_pb = row.get("r_pb")
    roe  = row.get("r_roe")
    de   = row.get("bs_debt_to_equity")

    if r_pe is not None and r_pe > 0:
        if r_pe < 10:    add("fundamental",  10, f"PE={r_pe} very cheap")
        elif r_pe < 15:  add("fundamental",   7, f"PE={r_pe} cheap")
        elif r_pe <= 25: add("fundamental",   3, f"PE={r_pe} fair")
        else:            add("fundamental",  -5, f"PE={r_pe} expensive")
    elif r_pe is not None and r_pe < 0:
        add("fundamental", -5, f"PE={r_pe} negative (loss)")

    if r_pb is not None and r_pb > 0:
        if r_pb < 1:     add("fundamental",  5, f"PB={r_pb} below book")
        elif r_pb <= 2:  add("fundamental",  3, f"PB={r_pb} fair")
        elif r_pb <= 3:  add("fundamental",  0, f"PB={r_pb} neutral")
        else:            add("fundamental", -3, f"PB={r_pb} expensive")
    elif r_pb is not None and r_pb < 0:
        add("fundamental", -5, f"PB={r_pb} negative equity")

    if roe:
        if roe > 20:     add("fundamental",  5, f"ROE={roe}% excellent")
        elif roe > 15:   add("fundamental",  3, f"ROE={roe}% good")
        elif roe > 10:   add("fundamental",  0, f"ROE={roe}% neutral")
        elif roe < 5:    add("fundamental", -3, f"ROE={roe}% weak")

    if de is not None and not _is_sector_match(industry, SECTOR_SKIP_DE):
        if de < 0.3:    add("fundamental",  3, f"D/E={de} very low")
        elif de < 1.0:  add("fundamental",  1, f"D/E={de} healthy")
        elif de < 2.0:  add("fundamental",  0, f"D/E={de} moderate")
        elif de < 3.0:  add("fundamental", -2, f"D/E={de} high")
        else:           add("fundamental", -3, f"D/E={de} very high")

    # ── CASH FLOW (max ±10) — sector-aware ──
    cfo     = row.get("cf_operating")
    cf_qual = row.get("cf_quality_ratio")
    skip_cf_sign = _is_sector_match(industry, SECTOR_CF_SKIP_SIGN)
    if cfo is not None:
        if skip_cf_sign:
            add("cf", 0, f"CFO={cfo:.0f} (sector-skip)")
        else:
            if cfo > 0:
                add("cf",   5, "CFO>0 real cash")
            else:
                add("cf", -10, "CFO<0 cash burn")
    if cf_qual is not None and not skip_cf_sign:
        if cf_qual > 1:     add("cf",  5, f"CF quality={cf_qual} high")
        elif cf_qual < 0.5: add("cf", -5, f"CF quality={cf_qual} low")

    # ── GROWTH (max ±10) — prefer YoY ──
    rev_g_yoy  = row.get("is_rev_growth_yoy")
    rev_g_qoq  = row.get("is_rev_growth")
    np_g_yoy   = row.get("is_profit_growth_yoy")
    np_g_qoq   = row.get("is_profit_growth")
    rev_g_yoy  = rev_g_yoy if pd.notna(rev_g_yoy) else None
    rev_g_qoq  = rev_g_qoq if pd.notna(rev_g_qoq) else None
    np_g_yoy   = np_g_yoy  if pd.notna(np_g_yoy)  else None
    np_g_qoq   = np_g_qoq  if pd.notna(np_g_qoq)  else None
    rev_g     = rev_g_yoy if rev_g_yoy is not None else rev_g_qoq
    rev_label = "RevG-YoY" if rev_g_yoy is not None else "RevG-QoQ"
    np_g      = np_g_yoy if np_g_yoy is not None else np_g_qoq
    np_label  = "ProfitG-YoY" if np_g_yoy is not None else "ProfitG-QoQ"
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

    # ── MARKET CONTEXT (max ±5) — regime-aware ──
    regime = context.get("market_regime", "UNKNOWN")
    CONTEXT_MATRIX = {
        "CHEAP":     {"UPTREND": 5,  "SIDEWAYS": 3,  "DOWNTREND":  0, "DEEP_DOWN": -2},
        "FAIR":      {"UPTREND": 2,  "SIDEWAYS": 0,  "DOWNTREND": -2, "DEEP_DOWN": -4},
        "EXPENSIVE": {"UPTREND": -2, "SIDEWAYS": -3, "DOWNTREND": -4, "DEEP_DOWN": -5},
    }
    if regime == "UNKNOWN":
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

    # ── NEWS (max ±5) — symmetric ──
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
        if top_article.get("news_type") == "delayed" and top_article.get("effective_date"):
            eff_hint = f" eff:{top_article['effective_date']}"
        art_hint = (f"[{top_article['title'][:40]}..."
                    f" · {top_article['source']}"
                    f" · {top_article['time'][11:16]}"
                    f"{eff_hint}]")
    else:
        art_hint = "[no news]"
    sigs.append(f"{news_label} {'+' if news_score > 0 else ''}{news_score} {art_hint}")

    # ── Apply caps ──
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

    # ── CONFLUENCE (max ±10) ──
    group_scores = {
        "trend": trend_score, "momentum": momentum_score,
        "volume": volume_score, "volatility": volatility_score,
        "order_flow": order_flow_score, "depth": depth_score, "ff": ff_score,
        "fundamental": fundamental_score, "cf": cf_score,
        "growth": growth_score, "news": news_score_final,
    }
    SIGNAL_THRESHOLD_PCT = 0.30
    _BASE_CAPS = {
        "trend": 30, "momentum": 23, "volume": 20, "volatility": 5,
        "order_flow": 10, "depth": 5, "ff": 20, "fundamental": 20,
        "cf": 10, "growth": 10, "news": 5,
    }
    positive_groups = 0
    negative_groups = 0
    for g, score in group_scores.items():
        cap = _BASE_CAPS[g]
        if score >= cap * SIGNAL_THRESHOLD_PCT:
            positive_groups += 1
        elif score <= -cap * SIGNAL_THRESHOLD_PCT:
            negative_groups += 1
    confluence_bonus = 0
    confluence_label = ""
    if positive_groups >= 7:
        confluence_bonus = 10;  confluence_label = f"CONFLUENCE strong bull ({positive_groups}/11 groups)"
    elif positive_groups >= 5:
        confluence_bonus = 5;   confluence_label = f"CONFLUENCE bull ({positive_groups}/11 groups)"
    elif negative_groups >= 7:
        confluence_bonus = -10; confluence_label = f"CONFLUENCE strong bear ({negative_groups}/11 groups)"
    elif negative_groups >= 5:
        confluence_bonus = -5;  confluence_label = f"CONFLUENCE bear ({negative_groups}/11 groups)"
    if confluence_bonus != 0:
        sigs.append(f"{confluence_label} {'+' if confluence_bonus > 0 else ''}{confluence_bonus}")

    # ── Totals (V2 sẽ overwrite total/decision/confidence/pattern_flags) ──
    total = (trend_score + momentum_score + volume_score + volatility_score
             + order_flow_score + depth_score + ff_score + fundamental_score
             + cf_score + growth_score + context_score + news_score_final
             + confluence_bonus)
    tech_score = (trend_score + momentum_score + volume_score
                  + volatility_score + order_flow_score)
    fund_score = fundamental_score + cf_score + growth_score

    if   total >= 80:  decision = "STRONG BUY"
    elif total >= 40:  decision = "BUY"
    elif total >= -15: decision = "NEUTRAL"
    elif total >= -40: decision = "SELL"
    else:              decision = "STRONG SELL"

    pattern_flags = []
    confidence    = "MEDIUM"
    if   tech_score >= 40 and fund_score <= -15:
        pattern_flags.append("BULL_TRAP_RISK");   confidence = "LOW"
    elif tech_score <= -30 and fund_score >= 15:
        pattern_flags.append("VALUE_OPPORTUNITY")
    elif tech_score >= 30 and fund_score >= 15:
        pattern_flags.append("CONSENSUS_BULL");   confidence = "HIGH"
    elif tech_score <= -30 and fund_score <= -15:
        pattern_flags.append("CONSENSUS_BEAR");   confidence = "HIGH"
    elif abs(tech_score) < 20 and abs(fund_score) < 10:
        pattern_flags.append("MIXED");            confidence = "LOW"

    out = dict(row)
    out.update({
        "market_valuation"    : market,
        "atr_pct"             : row.get("atr_pct"),
        "trend_score"         : trend_score,
        "momentum_score"      : momentum_score,
        "volume_score"        : volume_score,
        "volatility_score"    : volatility_score,
        "order_flow_score"    : order_flow_score,
        "depth_score"         : depth_score,
        "ff_score"            : ff_score,
        "fundamental_score"   : fundamental_score,
        "cf_score"            : cf_score,
        "growth_score"        : growth_score,
        "context_score"       : context_score,
        "news_score"          : news_score_final,
        "confluence_bonus"    : confluence_bonus,
        "tech_score"          : tech_score,
        "fund_score"          : fund_score,
        "news_industry"       : ns.get("industry", 0.0),
        "news_mention"        : ns.get("mention",  0.0),
        "news_macro"          : ns.get("macro",    0.0),
        "news_evidence"       : evidence,
        "total_score"         : total,
        "decision"            : decision,
        "confidence"          : confidence,
        "pattern_flags"       : pattern_flags,
        "signals"             : " | ".join(sigs),
    })
    return out


# ══════════════════════════════════════════════════════════════════════════
# EXTENDED INDICATORS — tính thêm, không có trong V3
# ══════════════════════════════════════════════════════════════════════════

def _to_float(v, default=None):
    try:
        x = float(v)
        return x if x == x else default  # NaN check
    except (TypeError, ValueError):
        return default


def score_market_breadth(row: dict, context: dict) -> tuple:
    """Market breadth: % symbols trên EMA20 trong universe (context group)."""
    breadth = _to_float(context.get("market_breadth_pct"))
    if breadth is None:
        return 0, ""

    if   breadth >= 70: score = +2
    elif breadth >= 50: score =  0
    elif breadth >= 30: score = -1
    else:               score = -2

    label = f"Breadth={breadth:.0f}% {score:+d}"
    return score, label


def score_rs_vnindex(row: dict, context: dict) -> tuple:
    """Relative Strength vs VNINDEX 20 ngày."""
    stock_ret = _to_float(row.get("return_20d"))
    if stock_ret is None:
        stock_ret = _to_float(row.get("price_vs_ema20_pct"))
    if stock_ret is None:
        return 0, ""

    vnindex_ret  = _to_float(row.get("vnindex_return_20d"))
    vnindex_real = vnindex_ret is not None

    if not vnindex_real:
        vnindex_ret = _to_float(
            context.get("vnindex_return_20d") or
            context.get("market_return_20d")
        )
        if vnindex_ret is not None:
            vnindex_real = True

    if not vnindex_real:
        vnindex_ret = None

    if math.isnan(stock_ret):
        return 0, ""

    if not vnindex_real or vnindex_ret is None:
        if   stock_ret >  15: score = +8
        elif stock_ret >   5: score = +4
        elif stock_ret >  -5: score =  0
        elif stock_ret > -15: score = -4
        else:                 score = -8
        return score, f"RS_abs={stock_ret:+.1f}%(no_VN) {score:+d}"

    rs = (1 + stock_ret / 100) / (1 + vnindex_ret / 100)

    score = 0
    if   rs > 1.30: score = +8
    elif rs > 1.10: score = +4
    elif rs > 0.90: score =  0
    elif rs > 0.70: score = -4
    else:           score = -8

    label = f"RS={rs:.2f}({'▲' if score>0 else '▼' if score<0 else '─'}) {score:+d}"
    return score, label


def score_52w_high(row: dict) -> tuple:
    """52-Week High proximity / breakout.

    2026-06-17: bail khi _ta_window=3M (fallback). Lý do non-determinism:
      Mã có 12M ok → 52W lấy từ 12M (đúng)
      Mã fallback 3M → 52W từ cửa sổ 3 tháng → giá trị thấp hơn nhiều → score lệch.
    Không dùng giá trị 3M giả tạo: trả 0 + đánh dấu để row có thể vào data_missing.
    """
    if row.get("_ta_window") == "3M":
        return 0, "52W skip (TA window 3M, không đủ tin cậy)"

    price    = _to_float(row.get("price"))
    high_52w = _to_float(row.get("high_52w"))
    low_52w  = _to_float(row.get("low_52w"))

    if price is None or price <= 0 or high_52w is None or high_52w <= 0:
        return 0, ""

    pct_from_high = (price - high_52w) / high_52w * 100

    score = 0
    if   pct_from_high > 0:      score = +7
    elif pct_from_high > -5:     score = +3
    elif pct_from_high > -20:    score =  0
    elif pct_from_high > -50:    score = -3
    else:                        score = -5

    label = f"52W_hi={pct_from_high:+.1f}% {score:+d}"
    return score, label


def score_roc10(row: dict) -> tuple:
    """Rate of Change 10 ngày."""
    roc = _to_float(row.get("roc_10"))
    if roc is None:
        return 0, ""

    if   roc >  5: score = +3
    elif roc >  2: score = +1
    elif roc > -2: score =  0
    elif roc > -5: score = -1
    else:          score = -3
    return score, f"ROC10={roc:+.1f}% {score:+d}"


def score_nr7(row: dict) -> tuple:
    """NR7/NR4 narrow-range breakout setup (proxy bằng _ohlcv_5d)."""
    ohlcv = row.get("_ohlcv_5d") or []
    if not isinstance(ohlcv, list) or len(ohlcv) < 4:
        return 0, ""

    ranges = []
    for d in ohlcv:
        if not isinstance(d, dict):
            continue
        h = _to_float(d.get("high"))
        l = _to_float(d.get("low"))
        if h and l and h > l:
            ranges.append(h - l)

    if len(ranges) < 3:
        return 0, ""

    today_range = ranges[-1]
    prev_ranges = ranges[:-1]

    if today_range <= 0:
        return 0, ""

    is_nr = today_range <= min(prev_ranges)
    avg_prev = sum(prev_ranges) / len(prev_ranges)
    compression = today_range / avg_prev if avg_prev > 0 else 1.0

    score = 0
    if is_nr and compression < 0.6:
        score = +3
    elif is_nr and compression < 0.8:
        score = +2
    elif compression < 0.7:
        score = +1

    label = f"NR={'Y' if is_nr else 'N'} compress={compression:.2f} {score:+d}"
    return score, label


# ══════════════════════════════════════════════════════════════════════════
# V2.2 NEW (Hướng A): 6 library indicators from vnstock_ta
# ══════════════════════════════════════════════════════════════════════════

def score_linreg_slope(row: dict) -> tuple:
    """Linear Regression slope (5-bar % change) — objective trend angle.

    Bổ sung EMA cross: EMA bị lag, linreg-slope bắt trend đảo chiều sớm hơn.
    Multi-collinear risk thấp với EMA: linreg đo TỐC ĐỘ, EMA đo POSITION.
    """
    slope = _to_float(row.get("linreg_slope_pct"))
    if slope is None:
        return 0, ""

    if   slope >  3.0: score = +3   # strong uptrend
    elif slope >  1.0: score = +1
    elif slope > -1.0: score =  0
    elif slope > -3.0: score = -1
    else:              score = -3   # strong downtrend

    return score, f"LinReg_slope={slope:+.1f}%/5d {score:+d}"


def score_aroon(row: dict) -> tuple:
    """Aroon Oscillator: trend strength independent of price scale.

    Khác ADX: ADX = strength không hướng. Aroon Osc = strength + hướng.
    Range -100..+100. >+30 uptrend, <-30 downtrend.
    """
    osc = _to_float(row.get("aroon_osc"))
    if osc is None:
        return 0, ""

    if   osc >  60: score = +3
    elif osc >  30: score = +2
    elif osc > -30: score =  0
    elif osc > -60: score = -2
    else:           score = -3

    arrow = '▲' if score > 0 else '▼' if score < 0 else '─'
    return score, f"Aroon={osc:+.0f}({arrow}) {score:+d}"


def score_donchian(row: dict) -> tuple:
    """Donchian Channel breakout: price vs prev 20d high/low.

    Lưu ý: dùng PREV day's DCU/DCL (donchian_upper_prev / lower_prev) — đó là
    max(high[t-21:t-1]) → 20-day high TRƯỚC bar hôm nay. close > prev DCU =
    breakout thực sự (vượt mức cao 20 phiên trước).
    """
    price    = _to_float(row.get("price"))
    dcu_prev = _to_float(row.get("donchian_upper_prev"))
    dcl_prev = _to_float(row.get("donchian_lower_prev"))

    if price is None or price <= 0:
        return 0, ""

    if dcu_prev and price > dcu_prev:
        return +2, f"Donch_BO↑(>{dcu_prev:.2f}) +2"
    if dcl_prev and price < dcl_prev:
        return -2, f"Donch_BD↓(<{dcl_prev:.2f}) -2"

    return 0, ""


def score_ad_line(row: dict) -> tuple:
    """A/D Line 20-day slope %.

    A/D Line = cumulative money flow (close vs range × volume).
    Slope dương = accumulation, âm = distribution. Khác OBV: OBV chỉ
    dùng dấu close vs prev close; A/D dùng VỊ TRÍ close trong bar range
    → granular hơn, ít noise ở phiên doji.
    """
    slope = _to_float(row.get("ad_slope_20d_pct"))
    if slope is None:
        return 0, ""

    if   slope >  5.0: score = +2
    elif slope >  1.0: score = +1
    elif slope > -1.0: score =  0
    elif slope > -5.0: score = -1
    else:              score = -2

    return score, f"AD_slope20d={slope:+.1f}% {score:+d}"


def score_efi(row: dict) -> tuple:
    """Elder Force Index (13) — volume × momentum signed.

    EFI = (close - prev_close) × volume, smoothed EMA(13).
    Sign rõ → áp lực ngắn hạn. Magnitude normalize qua vol_today để
    so sánh được giữa các mã khác nhau (HPG vs VCB khác volume scale).
    """
    efi = _to_float(row.get("efi_13"))
    if efi is None:
        return 0, ""

    vol_today = _to_float(row.get("vol_today"))

    # Normalize: |EFI| / vol_today ≈ avg price move per share weighted by signal
    if vol_today and vol_today > 0:
        strength = abs(efi) / vol_today
        if   efi > 0 and strength > 2.0: score = +3
        elif efi > 0 and strength > 0.5: score = +2
        elif efi > 0:                    score = +1
        elif efi < 0 and strength > 2.0: score = -3
        elif efi < 0 and strength > 0.5: score = -2
        elif efi < 0:                    score = -1
        else:                            score =  0
    else:
        # Fallback: dấu thuần
        if   efi > 0: score = +1
        elif efi < 0: score = -1
        else:         score =  0

    return score, f"EFI={efi:+,.0f} {score:+d}"


def score_willr(row: dict) -> tuple:
    """Williams %R (14) — oversold/overbought, range -100..0.

    Tương tự Stoch nhưng dùng range high-low của lookback (Stoch dùng close).
    Reverse-coded: < -80 = oversold = BULLISH cho mean-reversion.
    """
    wr = _to_float(row.get("willr_14"))
    if wr is None:
        return 0, ""

    if   wr <= -80: score = +3   # oversold
    elif wr <= -60: score = +1
    elif wr >= -20: score = -3   # overbought
    elif wr >= -40: score = -1
    else:           score =  0   # mid-range

    return score, f"Williams%R={wr:.1f} {score:+d}"


def score_bid_ask_imbalance(row: dict) -> tuple:
    """
    Depth scoring dựa trên wall position + volume.

    Logic:
    - ASK wall (lệnh chờ BÁN) gần giá → rào cản tăng lên →
      giá khó vượt TP, rủi ro xả hàng → điểm âm
    - BID wall (lệnh chờ MUA) gần giá → sàn đỡ vững →
      stop loss được bảo vệ → điểm dương

    Baseline vol: 5000 cp — dưới ngưỡng này không tính là wall.
    Proximity: ≤2% từ giá hiện tại = "gần" (tác động trực tiếp)
               2–5% = "vừa" (tác động gián tiếp)

    Scale: -2 → +2, cap vào GROUP_CAPS["depth"] = ±7
    """
    WALL_MIN_VOL = 5_000   # cp tối thiểu để tính là wall
    NEAR_PCT     = 0.01   # ≤1% từ giá — block ngay
    MID_PCT      = 0.03   # 1–3% — có kháng cự nhưng có thể vượt

    price = _to_float(row.get("price"))
    if price is None or price <= 0:
        return 0, ""

    bids, asks = [], []
    for i in (1, 2, 3):
        bp = _to_float(row.get(f"bid_price_{i}"))
        bv = _to_float(row.get(f"bid_vol_{i}"), 0) or 0
        ap = _to_float(row.get(f"ask_price_{i}"))
        av = _to_float(row.get(f"ask_vol_{i}"), 0) or 0
        # Normalize đơn vị: KBS order_book trả VND thực, price là nghìn VND
        if bp and not math.isnan(bp) and bp > price * 10:
            bp = bp / 1000
        if ap and not math.isnan(ap) and ap > price * 10:
            ap = ap / 1000
        if bp and not math.isnan(bp) and bp > 0 and bv >= WALL_MIN_VOL:
            bids.append((bp, bv))
        if ap and not math.isnan(ap) and ap > 0 and av >= WALL_MIN_VOL:
            asks.append((ap, av))

    if not bids and not asks:
        return 0, ""

    score = 0
    parts = []

    # ── ASK side ──
    ask_near = [(p, v) for p, v in asks
                if 0 < (p - price) / price <= NEAR_PCT]
    ask_mid  = [(p, v) for p, v in asks
                if NEAR_PCT < (p - price) / price <= MID_PCT]

    if ask_near:
        best = max(ask_near, key=lambda x: x[1])
        wall_score = -2
        score += wall_score
        parts.append(f"AskWall≤2%@{best[0]:.1f}({best[1]/1000:.0f}K) {wall_score:+d}")
    elif ask_mid:
        best = max(ask_mid, key=lambda x: x[1])
        wall_score = -1
        score += wall_score
        parts.append(f"AskWall2-5%@{best[0]:.1f}({best[1]/1000:.0f}K) {wall_score:+d}")
    else:
        score += 1
        parts.append("AskClear +1")

    # ── BID side ──
    bid_near = [(p, v) for p, v in bids
                if 0 <= (price - p) / price <= NEAR_PCT]
    bid_mid  = [(p, v) for p, v in bids
                if NEAR_PCT < (price - p) / price <= MID_PCT]

    if bid_near:
        best = max(bid_near, key=lambda x: x[1])
        score += 2
        parts.append(f"BidWall≤2%@{best[0]:.1f}({best[1]/1000:.0f}K) +2")
    elif bid_mid:
        best = max(bid_mid, key=lambda x: x[1])
        score += 1
        parts.append(f"BidWall2-5%@{best[0]:.1f}({best[1]/1000:.0f}K) +1")
    else:
        score -= 1
        parts.append("NoBidWall -1")

    score = max(-3, min(3, score))   # cap ±3 per function; GROUP_CAPS["depth"]=7 handles total
    label = " | ".join(parts) + f" → {score:+d}"
    return score, label


def score_ff_room(row: dict) -> tuple:
    """Foreign room utilization. ff_room = % room còn lại (0–100)."""
    room  = _to_float(row.get("ff_room"))
    total = _to_float(row.get("ff_room_max_pct"))
    if room is None:
        return 0, ""

    # v2.3 FIX #3: mã KHÔNG có room cap (total_room=0) hoặc available âm do
    #   artifact → KHÔNG phạt. Trước đây rơi vào else → -7 oan (vd TTA/CIG/RYG
    #   room 0% bị -7, trong khi mã room trống 99% lại +3).
    if (total is not None and total <= 0) or room < 0:
        return 0, f"FFroom={room:.1f}%(no cap) +0"

    if room > 100:
        return 0, f"FFroom={room:.1f}(invalid>100) +0"
    if   room > 30: score = +3
    elif room > 10: score =  0
    elif room >  5: score = -3
    else:           score = -7   # 0-5% room (đã loại ca no-cap/âm ở trên)

    label = f"FFroom={room:.1f}% {score:+d}"
    return score, label


def score_fair_value(row: dict, context: dict) -> tuple:
    """Fair value: so giá với PE ngành × EPS (fallback PE thị trường / 13x)."""
    price = _to_float(row.get("price"))
    eps   = _to_float(row.get("r_eps"))
    pe    = _to_float(row.get("r_pe"))
    if not price or not eps or price <= 0 or eps <= 0:
        return 0, ""

    icb = row.get("icb_code", "")
    sector_pe = _to_float(context.get(f"sector_pe_{icb}"))
    if sector_pe is None:
        sector_pe = _to_float(context.get("_ctx_pe"))
    if sector_pe is None or sector_pe <= 0:
        sector_pe = 13.0

    price_vnd = price * 1000
    fair_value = eps * sector_pe
    if fair_value <= 0:
        return 0, ""

    discount_pct = (fair_value - price_vnd) / fair_value * 100

    if   discount_pct > 30:  score = +6
    elif discount_pct > 10:  score = +3
    elif discount_pct > -10: score =  0
    elif discount_pct > -30: score = -3
    else:                    score = -6

    label = f"FairVal={discount_pct:+.0f}%(PE×EPS={fair_value:.0f}) {score:+d}"
    return score, label


def score_dividend_yield(row: dict) -> tuple:
    """Dividend yield score. r_div_yield từ finance cache (đơn vị %)."""
    yield_pct = _to_float(row.get("r_div_yield"))
    if yield_pct is None or yield_pct <= 0:
        return 0, ""

    # v2.3 FIX #5: bỏ heuristic `if yield<1.0: ×100`. r_div_yield ĐÃ ở dạng %
    #   (KBS trả %, vd 3.0=3%; đường VCI cũng đã _vci_pct về %). Heuristic cũ
    #   biến yield thật 0.8% (=0.8) thành 80% → +3 oan. Mã yield <1% rất phổ biến.
    if yield_pct > 100:          # chặn artifact bất thường
        return 0, f"DivYield={yield_pct:.1f}(invalid) +0"

    if   yield_pct > 6: score = +3
    elif yield_pct > 4: score = +2
    elif yield_pct > 2: score = +1
    else:               score =  0

    label = f"DivYield={yield_pct:.1f}% {score:+d}"
    return score, label


def score_prop_trade(row: dict) -> tuple:
    """Tự doanh CTCK (Proprietary Trading) — Smart Money signal."""
    net_5d  = _to_float(row.get("pt_net_val_5d"))
    net_20d = _to_float(row.get("pt_net_val_20d"))
    trend   = _to_float(row.get("pt_trend"))

    if net_5d is None or (isinstance(net_5d, float) and math.isnan(net_5d)):
        return 0, ""
    if net_20d is None or (isinstance(net_20d, float) and math.isnan(net_20d)):
        net_20d = 0.0

    n5  = (net_5d  or 0) / 1e9
    n20 = (net_20d or 0) / 1e9

    score = 0
    if n5 > 5 and n20 > 0 and (trend or 0) > 0:
        score = +10
    elif n5 > 2:
        score = +5
    elif n5 > 0.5:
        score = +2
    elif n5 > -0.5:
        score = 0
    elif n5 > -2:
        score = -2
    elif n5 > -5:
        score = -5
    else:
        score = -10

    label = f"PropTrade={n5:+.1f}tỷ(5d) {score:+d}"
    return score, label


def score_eps_consistency(row: dict) -> tuple:
    """EPS consistency: số quý liên tiếp EPS tăng YoY (fallback profit_growth_yoy)."""
    eps_cons = _to_float(row.get("eps_consistency"))
    if eps_cons is not None:
        n = int(eps_cons)
        if   n >= 4: score = +5
        elif n >= 2: score = +2
        elif n == 1: score =  0
        elif n == -2: score = -3
        elif n <= -4: score = -5
        else:         score = -1
        return score, f"EPScons={n}qtrs {score:+d}"

    profit_yoy = _to_float(row.get("is_profit_growth_yoy"))
    profit_qoq = _to_float(row.get("is_profit_growth"))

    if profit_yoy is None:
        return 0, ""
    if math.isnan(profit_yoy):
        return 0, ""

    score = 0
    pct = profit_yoy * 100

    if pct > 30:
        if profit_qoq is not None and not math.isnan(profit_qoq) and profit_qoq > 0:
            score = +3
        else:
            score = +2
    elif pct > 15:
        score = +2
    elif pct > 0:
        score = +1
    elif pct > -10:
        score = -1
    elif pct > -30:
        score = -3
    else:
        score = -5

    label = f"EPSyoy={pct:+.0f}% {score:+d}"
    return score, label


def score_insider(row: dict) -> tuple:
    """Insider buy/sell activity."""
    buy_cnt  = int(_to_float(row.get("insider_buy_count"),  0) or 0)
    sell_cnt = int(_to_float(row.get("insider_sell_count"), 0) or 0)
    total    = buy_cnt + sell_cnt

    if total == 0:
        latest = str(row.get("insider_latest") or "").lower()
        if not latest:
            return 0, ""
        is_buy  = any(k in latest for k in ["mua", "buy", "purchase", "acqui"])
        is_sell = any(k in latest for k in ["bán", "sell", "dispos"])
        if   is_buy:  return +3, "Insider=BUY(latest) +3"
        elif is_sell: return -3, "Insider=SELL(latest) -3"
        return 0, ""

    net = buy_cnt - sell_cnt
    if   net >= 3:  score = +5
    elif net >= 1:  score = +3
    elif net == 0:  score =  0
    elif net >= -2: score = -3
    else:           score = -5

    label = f"Insider=B{buy_cnt}/S{sell_cnt}(90d) net={net:+d} {score:+d}"
    return score, label


# =====================================================
# NORMALIZE + WEIGHT
# =====================================================

def _normalize_and_weight(raw_scores: dict) -> tuple:
    norm = {}
    for g, cap in GROUP_CAPS.items():
        raw = raw_scores.get(g, 0) or 0
        norm[g] = max(-1.0, min(1.0, raw / cap))

    weighted_sum = sum(
        SCORING_WEIGHTS.get(g, 0) * norm[g]
        for g in SCORING_WEIGHTS
    )
    return round(weighted_sum * 100, 2), norm


def _confluence_bonus(norm_scores: dict) -> tuple:
    check_groups = {k: v for k, v in norm_scores.items() if k != "context"}

    positive = sum(1 for n in check_groups.values() if n >=  CONFLUENCE_THRESHOLD_PCT)
    negative = sum(1 for n in check_groups.values() if n <= -CONFLUENCE_THRESHOLD_PCT)
    n_groups = len(check_groups)

    bonus, label = 0, ""
    if   positive >= 7: bonus, label = +10, f"CONFLUENCE strong bull ({positive}/{n_groups})"
    elif positive >= 5: bonus, label =  +5, f"CONFLUENCE bull ({positive}/{n_groups})"
    elif negative >= 7: bonus, label = -10, f"CONFLUENCE strong bear ({negative}/{n_groups})"
    elif negative >= 5: bonus, label =  -5, f"CONFLUENCE bear ({negative}/{n_groups})"
    return bonus, label


def _decision(total: float) -> str:
    if   total >= THRESHOLD_STRONG_BUY: return "STRONG BUY"
    elif total >= THRESHOLD_BUY:        return "BUY"
    elif total >= THRESHOLD_NEUTRAL:    return "NEUTRAL"
    elif total >= THRESHOLD_SELL:       return "SELL"
    else:                               return "STRONG SELL"


# =====================================================
# SCORE SYMBOL V2 — main scoring function
# =====================================================

def score_symbol_v2(row: dict, context: dict, news_scores: dict,
                    order_flow_map: dict) -> dict:
    """
    1. Lấy raw group scores từ base scorer (inlined, không phụ thuộc v3)
    2. Tính thêm các extended indicators
    3. Merge vào group scores tương ứng
    4. Normalize → weighted sum → confluence → final score
    """
    sym = row.get("symbol", "?")

    # ── Base: gọi base scorer inlined (KHÔNG còn import v3) ──
    v3 = _score_base(row, context, news_scores, order_flow_map)

    # ── Raw group scores từ base ──
    raw = {
        "trend":       v3.get("trend_score",       0) or 0,
        "momentum":    v3.get("momentum_score",    0) or 0,
        "volume":      v3.get("volume_score",      0) or 0,
        "volatility":  v3.get("volatility_score",  0) or 0,
        "order_flow":  v3.get("order_flow_score",  0) or 0,
        "depth":       v3.get("depth_score",       0) or 0,
        "ff":          v3.get("ff_score",          0) or 0,
        "fundamental": v3.get("fundamental_score", 0) or 0,
        "cf":          v3.get("cf_score",          0) or 0,
        "growth":      v3.get("growth_score",      0) or 0,
        "context":     v3.get("context_score",     0) or 0,
        # news: bỏ
    }

    # ── TA STATE (v2.6, 2026-06-17): phân biệt 3 trạng thái ──
    #   1. OK              → tính bình thường
    #   2. CACHED (stale)  → tin tưởng full nếu ≤2 phiên, hạ confidence nếu >2
    #   3. MISSING         → ép NEUTRAL+LOW (Lớp A fail-safe khi cache cũng fail)
    _ta_err = row.get("ta_error")
    ta_missing = bool(_ta_err) and not (isinstance(_ta_err, float) and _ta_err != _ta_err)
    ta_from_cache = bool(row.get("_ta_from_cache"))
    ta_stale_days = int(row.get("_ta_stale_days") or 0)

    # MISSING — không có cache lẫn fetch → zero-hóa 4 group TA (như cũ)
    if ta_missing:
        for _g in ("trend", "momentum", "volume", "volatility"):
            raw[_g] = 0

    ext_sigs = []  # extended indicator signals log

    # ── Extended: Trend group ──
    rs_score,   rs_label   = score_rs_vnindex(row, context)
    w52_score,  w52_label  = score_52w_high(row)
    raw["trend"] += rs_score + w52_score
    if rs_label:  ext_sigs.append(rs_label)
    if w52_label: ext_sigs.append(w52_label)

    # ── v2.2 Extended: Trend group library indicators ──
    linreg_score,   linreg_label   = score_linreg_slope(row)
    aroon_score,    aroon_label    = score_aroon(row)
    donchian_score, donchian_label = score_donchian(row)
    raw["trend"] += linreg_score + aroon_score + donchian_score
    if linreg_label:   ext_sigs.append(linreg_label)
    if aroon_label:    ext_sigs.append(aroon_label)
    if donchian_label: ext_sigs.append(donchian_label)

    # ── Extended: Context group — market breadth ──
    breadth_score, breadth_label = score_market_breadth(row, context)
    raw["context"] += breadth_score
    if breadth_label: ext_sigs.append(breadth_label)

    # ── Extended: Momentum group ──
    roc_score, roc_label = score_roc10(row)
    raw["momentum"] += roc_score
    if roc_label: ext_sigs.append(roc_label)

    # ── v2.2 Extended: Momentum group library indicator ──
    willr_score, willr_label = score_willr(row)
    raw["momentum"] += willr_score
    if willr_label: ext_sigs.append(willr_label)

    # ── Extended: Volatility group ──
    nr7_score, nr7_label = score_nr7(row)
    raw["volatility"] += nr7_score
    if nr7_label: ext_sigs.append(nr7_label)

    # ── v2.2 Extended: Volume group library indicators ──
    ad_score,  ad_label  = score_ad_line(row)
    efi_score, efi_label = score_efi(row)
    raw["volume"] += ad_score + efi_score
    if ad_label:  ext_sigs.append(ad_label)
    if efi_label: ext_sigs.append(efi_label)

    # ── Extended: Depth group ──
    ba_score, ba_label = score_bid_ask_imbalance(row)
    raw["depth"] += ba_score
    if ba_label: ext_sigs.append(ba_label)

    # ── Extended: FF group ──
    room_score, room_label = score_ff_room(row)
    raw["ff"] += room_score
    if room_label: ext_sigs.append(room_label)

    # ── Extended: Fundamental group — fair value + dividend ──
    fv_score,  fv_label  = score_fair_value(row, context)
    div_score, div_label = score_dividend_yield(row)
    raw["fundamental"] += fv_score + div_score
    if fv_label:  ext_sigs.append(fv_label)
    if div_label: ext_sigs.append(div_label)

    # ── Extended: Growth group ──
    eps_score, eps_label = score_eps_consistency(row)
    raw["growth"] += eps_score
    if eps_label: ext_sigs.append(eps_label)

    # ── Smart Money group: prop trade + insider ──
    prop_score,    prop_label    = score_prop_trade(row)
    insider_score, insider_label = score_insider(row)
    raw["smart_money"] = prop_score + insider_score
    if prop_label:    ext_sigs.append(prop_label)
    if insider_label: ext_sigs.append(insider_label)

    # ── Normalize + weighted sum ──
    base_score, norm = _normalize_and_weight(raw)

    # ── Confluence ──
    conf_bonus, conf_label = _confluence_bonus(norm)
    if conf_bonus != 0:
        sigs = v3.get("signals", "")
        extra = f"{conf_label} {'+' if conf_bonus > 0 else ''}{conf_bonus}"
        v3["signals"] = (sigs + " | " + extra) if sigs else extra

    total_score = round(base_score + conf_bonus, 2)
    decision    = _decision(total_score)

    # ── Tech/Fund scores ──
    tech_score = (raw["trend"] + raw["momentum"] + raw["volume"] +
                  raw["volatility"] + raw["order_flow"])
    fund_score = raw["fundamental"] + raw["cf"] + raw["growth"]

    # ── Pattern flags ──
    pattern_flags = []
    confidence    = "MEDIUM"
    if   tech_score >= 40 and fund_score <= -15:
        pattern_flags.append("BULL_TRAP_RISK");   confidence = "LOW"
    elif tech_score <= -30 and fund_score >= 15:
        pattern_flags.append("VALUE_OPPORTUNITY")
    elif tech_score >= 30 and fund_score >= 15:
        pattern_flags.append("CONSENSUS_BULL");   confidence = "HIGH"
    elif tech_score <= -30 and fund_score <= -15:
        pattern_flags.append("CONSENSUS_BEAR");   confidence = "HIGH"
    elif abs(tech_score) < 20 and abs(fund_score) < 10:
        pattern_flags.append("UNCLEAR");          confidence = "LOW"

    # TA_MISSING (Lớp A fail-safe, 2026-06-17): cache cũng fail → KHÔNG TIN
    # total_score vì 4 group TA bị zero hóa lệch hướng → ép NEUTRAL+LOW để
    # tránh flip decision do data missing. Đây là quyết định "an toàn hơn
    # đúng" — khi không có data, không kêu BUY/SELL.
    if ta_missing:
        if "TA_MISSING" not in pattern_flags:
            pattern_flags.insert(0, "TA_MISSING")
        decision   = "NEUTRAL"   # ép NEUTRAL bất kể total_score
        confidence = "LOW"

    # TA_CACHED (B, 2026-06-17): dùng cache phiên trước → tin tưởng nhưng đánh dấu
    if ta_from_cache:
        if ta_stale_days <= 2:
            # 1-2 phiên cũ: data hầu như không đổi → giữ nguyên decision+confidence
            pass
        else:
            # 3-5 phiên cũ: hạ confidence vì có thể đã dịch nhiều
            if confidence == "HIGH":   confidence = "MEDIUM"
            elif confidence == "MEDIUM": confidence = "LOW"

    # ── DATA COMPLETENESS (2026-06-17) — minh bạch field thiếu, KHÔNG đổi điểm ──
    # Mục tiêu: phơi bày khi điểm được tính trên data KHÔNG đầy đủ (do fetch fail),
    # để người đọc biết score có thể không ổn định. Theo chính sách: giữ điểm,
    # chỉ đánh dấu — không ép NEUTRAL, không zero thêm.
    CORE_FIELDS = {
        "price"         : "Giá",
        "ema200"        : "EMA200",
        "rsi"           : "RSI",
        "macd_hist"     : "MACD",
        "high_52w"      : "Đỉnh52T",
        "r_pe"          : "P/E",
        "r_eps"         : "EPS",
        "ff_net_val_5d" : "FF5d",
    }
    data_missing = []
    for _f, _label in CORE_FIELDS.items():
        _v = row.get(_f)
        if _v is None or (isinstance(_v, float) and _v != _v):
            data_missing.append(_label)
    if not row.get("_ohlcv_5d"):
        data_missing.append("OHLCV5d")
    if row.get("_ta_window") == "3M":
        data_missing.append("Đỉnh52T(3M)")     # 52W từ cửa sổ ngắn → kém tin cậy
    if row.get("_price_fallback"):
        data_missing.append("Giá(fallback)")    # price lấy từ ta last_close
    if ta_from_cache:
        data_missing.append(f"TA-cache-{ta_stale_days}d")   # B: cache phiên

    # Order flow: phân biệt "fetch fail" với "phiên trầm" (cả hai cùng score 0).
    # Ngoài giờ GD, EOD data CỐ ĐỊNH — nếu thiếu là do fetch fail, không phải
    # do thị trường. Đánh dấu để biết order_flow_score=0 này không đáng tin.
    _of = order_flow_map.get(sym, {})
    _of_sum = _of.get("summary", {}) if isinstance(_of, dict) else {}
    if _of_sum.get("fetch_failed") or _of_sum.get("pattern") == "ERROR":
        data_missing.append("LựcKhớp")

    n_core = len(CORE_FIELDS) + 1               # +1 cho OHLCV5d
    data_completeness = round(max(0.0, 1 - len([m for m in data_missing
                            if "(" not in m]) / n_core), 3)

    # Flag minh bạch — chỉ bật khi gap THỰC SỰ ảnh hưởng (price/ta core mất, hoặc ≥3 field)
    _material = (
        "Giá" in data_missing or ta_missing or
        sum(1 for m in data_missing if "(" not in m) >= 3
    )
    if data_missing and _material and "DATA_INCOMPLETE" not in pattern_flags:
        pattern_flags.append("DATA_INCOMPLETE")
        if confidence == "MEDIUM":
            confidence = "LOW"                   # hạ confidence, KHÔNG đổi total_score

    # ── Build output ──
    out = dict(v3)
    out.update({
        "total_score"      : total_score,
        "base_score_v2"    : base_score,
        "confluence_bonus" : conf_bonus,
        "decision"         : decision,
        "confidence"       : confidence,
        "pattern_flags"    : pattern_flags,
        "scoring_version"  : SCORING_VERSION,
        "tech_score"       : tech_score,
        "fund_score"       : fund_score,
        "data_missing"     : data_missing,
        "data_completeness": data_completeness,
        # Extended raw scores
        "ext_rs_score"      : rs_score,
        "ext_52w_score"     : w52_score,
        "ext_roc_score"     : roc_score,
        "ext_nr7_score"     : nr7_score,
        "ext_ba_score"      : ba_score,
        "ext_room_score"    : room_score,
        "ext_fv_score"      : fv_score,
        "ext_div_score"     : div_score,
        "ext_eps_score"     : eps_score,
        "ext_prop_score"    : prop_score,
        "ext_insider_score" : insider_score,
        "ext_breadth_score" : breadth_score,
        # v2.2 NEW (Hướng A) — library indicators
        "ext_linreg_score"  : linreg_score,
        "ext_aroon_score"   : aroon_score,
        "ext_donchian_score": donchian_score,
        "ext_ad_score"      : ad_score,
        "ext_efi_score"     : efi_score,
        "ext_willr_score"   : willr_score,
        "ext_signals"       : " | ".join(ext_sigs) if ext_sigs else "",
        # Smart money group
        "smart_money_score" : raw.get("smart_money", 0),
        "norm_smart_money"  : round(min(1.0, max(-1.0,
            raw.get("smart_money", 0) / GROUP_CAPS.get("smart_money", 20))), 4),
        # Normalized scores
        "norm_trend"       : round(norm.get("trend",       0), 4),
        "norm_momentum"    : round(norm.get("momentum",    0), 4),
        "norm_volume"      : round(norm.get("volume",      0), 4),
        "norm_volatility"  : round(norm.get("volatility",  0), 4),
        "norm_order_flow"  : round(norm.get("order_flow",  0), 4),
        "norm_depth"       : round(norm.get("depth",       0), 4),
        "norm_ff"          : round(norm.get("ff",          0), 4),
        "norm_fundamental" : round(norm.get("fundamental", 0), 4),
        "norm_cf"          : round(norm.get("cf",          0), 4),
        "norm_growth"      : round(norm.get("growth",      0), 4),
        "norm_context"     : round(norm.get("context",     0), 4),
        # Weight snapshot
        "w_trend"          : SCORING_WEIGHTS["trend"],
        "w_momentum"       : SCORING_WEIGHTS["momentum"],
        "w_volume"         : SCORING_WEIGHTS["volume"],
        "w_order_flow"     : SCORING_WEIGHTS["order_flow"],
        "w_ff"             : SCORING_WEIGHTS["ff"],
        "w_fundamental"    : SCORING_WEIGHTS["fundamental"],
        "w_cf"             : SCORING_WEIGHTS["cf"],
        "w_growth"         : SCORING_WEIGHTS["growth"],
    })
    return out


# =====================================================
# DAILY CHANGE — gắn từ ranking.json (v2.2)
# =====================================================

def _attach_daily_change(result: dict, ranking_map: dict) -> None:
    """
    Gắn % và giá trị tuyệt đối thay đổi trong ngày vào signal row.
    Nguồn: v2f_ranking.json (VN100 → gainer/loser trong rổ, utils/universe_v2).
    """
    rk = ranking_map.get(result.get("symbol"))
    if not rk:
        result["chg_pct_1d"]        = None
        result["chg_abs_vnd"]       = None
        result["accumulated_value"] = None
        return

    pct = _to_float(rk.get("price_change_percent_1d"))
    chg = _to_float(rk.get("price_change_1d"))
    result["chg_pct_1d"]        = round(pct, 2) if pct is not None else None
    result["chg_abs_vnd"]       = round(chg * 1000) if chg is not None else None
    result["accumulated_value"] = _to_float(rk.get("accumulated_value"))


def _attach_order_flow(result: dict, order_flow_map: dict) -> None:
    """
    v2.5: gắn các field _of_* vào signal row cho dashboard (indexv2.html
    block "🔄 LỰC KHỚP LỆNH" đọc các field này).

    BUG được fix: refactor v2.2→v2.3 đã làm rơi bước enrichment này. Order flow
    vẫn fetch + ghi v2f_order_flow.json đầy đủ, nhưng score_symbol_v2() chỉ dùng
    summary để tính order_flow_score rồi vứt đi → v2f_signals.json không còn
    _of_pattern/_of_buy_vol/... → dashboard hiển thị "0cp / không pattern"
    (trông như không có lực khớp lệnh, kể cả trong giờ giao dịch).

    Nguồn số liệu:
      - summary{}      : pattern, distribution_type, buy_ratio_today,
                         sell_ratio_today, vol_spike_pct, avg_trade_size,
                         total_trades, trader_type
      - volume_profile : cộng dồn buy/sell count + buy/sell volume
        (key đặt trong step_order_flow_v2.build_volume_profile:
         buy_count, sell_count, buy_volume, sell_volume)
    """
    of_full = order_flow_map.get(result.get("symbol")) or {}
    if not isinstance(of_full, dict):
        of_full = {}
    s  = of_full.get("summary", {}) if isinstance(of_full.get("summary"), dict) else {}
    vp = of_full.get("volume_profile") or []

    buy_cnt = sell_cnt = 0
    buy_vol = sell_vol = 0
    for r in vp:
        if not isinstance(r, dict):
            continue
        buy_cnt  += int(_to_float(r.get("buy_count"),   0) or 0)
        sell_cnt += int(_to_float(r.get("sell_count"),  0) or 0)
        buy_vol  += int(_to_float(r.get("buy_volume"),  0) or 0)
        sell_vol += int(_to_float(r.get("sell_volume"), 0) or 0)

    result.update({
        "_of_pattern"      : s.get("pattern"),
        "_of_distribution" : s.get("distribution_type"),
        "_of_buy_ratio"    : s.get("buy_ratio_today"),
        "_of_sell_ratio"   : s.get("sell_ratio_today"),
        "_of_vol_spike"    : s.get("vol_spike_pct"),
        "_of_avg_size"     : s.get("avg_trade_size"),
        "_of_total_trades" : s.get("total_trades"),
        "_of_trader_type"  : s.get("trader_type"),
        "_of_buy_count"    : buy_cnt  or None,
        "_of_sell_count"   : sell_cnt or None,
        "_of_buy_vol"      : buy_vol  or None,
        "_of_sell_vol"     : sell_vol or None,
    })


def _ctx_passthrough(ctx: dict) -> dict:
    """v2.4: map context.json → các field _ctx_* để dashboard tự đủ."""
    if not ctx:
        return {}
    g = ctx.get
    return {
        "_ctx_close":     g("vnindex_close"),
        "_ctx_ema50":     g("vnindex_ema50"),
        "_ctx_ema200":    g("vnindex_ema200"),
        "_ctx_chg_1d":    g("vnindex_chg_1d"),
        "_ctx_chg_5d":    g("vnindex_chg_5d"),
        "_ctx_chg_20d":   g("vnindex_chg_20d"),
        "_ctx_regime":    g("market_regime"),
        "_ctx_pe":        g("vnindex_pe"),
        "_ctx_pb":        g("vnindex_pb"),
        "_ctx_pe_pct":    g("pe_percentile_5y"),
        "_ctx_pb_pct":    g("pb_percentile_5y"),
        "_ctx_valuation": g("market_valuation"),
    }


# =====================================================
# MAIN
# =====================================================

def run():
    log.info(f"=== SCORING V2 START ({now_ict():%Y-%m-%d %H:%M:%S} ICT) ===")
    log.info(f"Scoring version: {SCORING_VERSION}")
    log.info(f"Thresholds: SB≥{THRESHOLD_STRONG_BUY} | BUY≥{THRESHOLD_BUY} | "
             f"NEU≥{THRESHOLD_NEUTRAL} | SELL≥{THRESHOLD_SELL}")
    log.info(f"Extended: RS, 52W, ROC10, NR7, BidAsk, FFroom, DivYield, EPScons, Insider")

    deep_raw     = load_json("v2f_deep_raw.json")
    context_list = load_json("market/context.json") or load_json("context.json")
    today_index  = load_json("news/today_index.json") or load_json("news_today_index.json")
    order_flow   = load_json("v2f_order_flow.json")

    if not deep_raw:
        log.error("v2f_deep_raw.json not found — chạy step_snapshot_v2.py trước")
        return

    ctx = context_list[0] if context_list else {}

    if not order_flow:
        log.warning("v2f_order_flow.json not found — order_flow_score = 0")
        order_flow = []

    order_flow_map = {
        r["symbol"]: r
        for r in (order_flow or [])
        if isinstance(r, dict) and r.get("symbol")
    }

    # ── Daily change từ v2f_ranking.json (VN100 universe) ──
    # 2026-06-21: V2 universe ghi v2f_ranking.json (VN100 → gainer/loser trong rổ).
    # Ưu tiên file V2; fallback ranking.json (V3) nếu chạy lệch thứ tự.
    ranking = load_json("v2f_ranking.json") or load_json("ranking.json") \
              or load_json("market/ranking.json") or []
    ranking_map = {
        r["symbol"]: r
        for r in ranking
        if isinstance(r, dict) and r.get("symbol")
    }
    if ranking_map:
        log.info(f"Ranking loaded: {len(ranking_map)} symbols (daily change → chg_pct_1d/chg_abs_vnd)")
    else:
        log.warning("v2f_ranking.json/ranking.json not found — chg_pct_1d/chg_abs_vnd sẽ = None")

    symbols_with_industry = [
        {"symbol": r["symbol"], "icb_name": r.get("industry", "")}
        for r in deep_raw
    ]
    news_scores = build_news_scores(today_index or {}, symbols_with_industry)

    log.info(f"Scoring {len(deep_raw)} symbols...")

    ctx_fields = _ctx_passthrough(ctx)   # v2.4: _ctx_* cho dashboard
    if ctx_fields.get("_ctx_close") is not None:
        log.info(f"Context passthrough: VNINDEX {ctx_fields['_ctx_close']} "
                 f"regime={ctx_fields.get('_ctx_regime')} PE={ctx_fields.get('_ctx_pe')}")
    else:
        log.warning("Context rỗng — _ctx_* sẽ = None (market strip dashboard sẽ trống)")

    scored_rows = []
    for row in deep_raw:
        result = score_symbol_v2(row, ctx, news_scores, order_flow_map)
        _attach_daily_change(result, ranking_map)   # v2.2: gắn chg ngày
        _attach_order_flow(result, order_flow_map)  # v2.5: gắn _of_* cho dashboard
        if ctx_fields:
            result.update(ctx_fields)               # v2.4: gắn _ctx_*
        scored_rows.append(result)

        flags_str = ",".join(result.get("pattern_flags") or []) or "-"
        ext       = result.get("ext_signals", "")
        chg_pct   = result.get("chg_pct_1d")
        chg_str   = f" chg={chg_pct:+.2f}%" if chg_pct is not None else ""
        log.info(
            f"  [{result['symbol']:6s}] "
            f"v2={result['total_score']:6.1f} "
            f"(base={result['base_score_v2']:6.1f} conf={result['confluence_bonus']:+d}) "
            f"→ {result['decision']:12s} [{result['confidence']}]{chg_str}"
            + (f"\n    ext: {ext}" if ext else "")
        )

    df = pd.DataFrame(scored_rows)
    save_json("v2f_signals.json", df.to_dict(orient="records"))

    # CSV export
    pattern_flags_col = df["pattern_flags"].apply(
        lambda f: ",".join(f or [])
    ) if "pattern_flags" in df.columns else pd.Series([""] * len(df))

    news_evidence_col = df["news_evidence"].apply(
        lambda evs: " | ".join(
            f"{e.get('type','?')}·{e.get('source','?')}·"
            f"{e.get('title','')[:40]}·{str(e.get('time',''))[5:16]}"
            for e in (evs or [])
        )
    ) if "news_evidence" in df.columns else pd.Series([""] * len(df))

    df_csv = df.drop(columns=["news_evidence", "_ohlcv_5d", "pattern_flags"], errors="ignore")
    df_csv = clean_for_export(df_csv)
    df_csv["news_evidence"] = news_evidence_col.values
    df_csv["pattern_flags"] = pattern_flags_col.values
    save_csv("v2f_signals.csv", df_csv)

    # Summary log
    decision_counts = df["decision"].value_counts().to_dict()
    log.info(f"Decision distribution: {decision_counts}")

    # Daily-change coverage (v2.2)
    if "chg_pct_1d" in df.columns:
        chg_cov = df["chg_pct_1d"].notna().sum()
        log.info(f"  daily change: {chg_cov}/{len(df)} symbols có chg_pct_1d từ ranking")

    # Extended indicator coverage
    for field in ["ext_rs_score", "ext_52w_score", "ext_roc_score", "ext_nr7_score",
                  "ext_ba_score", "ext_room_score", "ext_div_score", "ext_eps_score", "ext_insider_score"]:
        nonzero = (df[field] != 0).sum() if field in df.columns else 0
        log.info(f"  {field}: {nonzero}/{len(df)} symbols có signal")

    # V3 comparison
    v3_signals = load_json("signals.json")
    if v3_signals:
        v3_df  = pd.DataFrame(v3_signals)[["symbol", "decision", "total_score"]]
        v2_df  = df[["symbol", "decision", "total_score"]].copy()
        v3_df.columns = ["symbol", "dec3", "sc3"]
        v2_df.columns = ["symbol", "dec2", "sc2"]
        cmp   = pd.merge(v3_df, v2_df, on="symbol", how="inner")
        agree = (cmp["dec3"] == cmp["dec2"]).sum()
        log.info(f"V3 vs V2 agreement: {agree}/{len(cmp)} = {agree/len(cmp)*100:.1f}%")
        diff = cmp[cmp["dec3"] != cmp["dec2"]]
        for _, r in diff.iterrows():
            log.info(f"  DIFF {r.symbol}: v3={r.dec3}({r.sc3:.0f}) → v2={r.dec2}({r.sc2:.1f})")

    log.info(f"Exported v2f_signals.json + v2f_signals.csv ({len(df)} rows)")
    log.info("=== SCORING V2 DONE ===")


if __name__ == "__main__":
    run()
