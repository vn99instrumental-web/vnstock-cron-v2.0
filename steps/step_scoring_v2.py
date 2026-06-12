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
  6. Output: signals_v2.json / signals_v2.csv
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

WEIGHT RATIONALE (horizon ≤30 ngày, bỏ news):
  trend=22%, momentum=15%, volume=11%, order_flow=9%, volatility=4%,
  depth=4%, ff=13%, context=4%, fundamental=7%, cf=5%, growth=6%
  Tổng = 100%

SCORING_VERSION = "v2"

CHANGELOG:
  2026-06-11 — v2 initial: normalized weighted scoring
  2026-06-11 — v2.1: thêm 9 extended indicators, bỏ news group
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
from utils.cache   import load_json, save_json, save_csv
from utils.formatter import clean_for_export

from steps.step_scoring import (
    SECTOR_CF_SKIP_SIGN,
    SECTOR_SKIP_DE,
    _is_sector_match,
    build_news_scores,
    score_order_flow,
    score_depth,
    score_symbol as _score_symbol_v3,
)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(levelname)s %(message)s'
)
log = logging.getLogger(__name__)

# =====================================================
# V2 CONFIG
# =====================================================

SCORING_VERSION = "v2"

# Cap cho từng group — extended caps cho groups có chỉ số mới
GROUP_CAPS = {
    "trend":       45,   # +15 từ RS(±8) + 52W(±7)
    "momentum":    26,   # +3 từ ROC(±3)
    "volume":      20,
    "volatility":  8,    # +3 từ NR7(±3)
    "order_flow":  10,
    "depth":       7,    # +2 từ bid/ask imbalance(±2)
    "ff":          27,   # +7 từ room utilization(±7)
    "fundamental": 23,   # +3 từ dividend yield(±3)
    "cf":          10,
    "growth":      15,   # +5 từ EPS consistency(±5)
    "context":     5,
    # news: bỏ
}

# Weight — bỏ news (4%), phân bổ lại
SCORING_WEIGHTS = {
    "trend":       0.22,   # tăng từ 0.20: RS + 52W quan trọng
    "momentum":    0.15,   # tăng từ 0.14: thêm ROC
    "volume":      0.11,   # tăng từ 0.10
    "order_flow":  0.09,   # tăng từ 0.08
    "volatility":  0.04,
    "depth":       0.04,
    "ff":          0.13,   # giảm từ 0.18: nhường context + fundamental
    "context":     0.04,
    "fundamental": 0.07,   # tăng từ 0.06: fair value + dividend
    "cf":          0.05,   # tăng từ 0.04
    "growth":      0.06,   # tăng từ 0.04: EPS consistency
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


# =====================================================
# EXTENDED INDICATORS — tính thêm, không có trong V3
# =====================================================

def _to_float(v, default=None):
    try:
        x = float(v)
        return x if x == x else default  # NaN check
    except (TypeError, ValueError):
        return default


def score_rs_vnindex(row: dict, context: dict) -> tuple[int, str]:
    """
    Relative Strength vs VNINDEX 20 ngày.
    RS = (1 + return_stock_20d%) / (1 + return_vnindex_20d%)
    Ưu tiên return_20d thực từ OHLCV; vnindex từ row hoặc context.
    """
    stock_ret = _to_float(row.get("return_20d"))
    if stock_ret is None:
        stock_ret = _to_float(row.get("price_vs_ema20_pct"))
    if stock_ret is None:
        return 0, ""

    # VNINDEX return: chỉ dùng relative mode khi có data thực từ row/context
    # Nếu chỉ có regime fallback → dùng absolute mode (tránh RS ≈ 1.0 cho mọi symbol)
    vnindex_ret  = _to_float(row.get("vnindex_return_20d"))
    vnindex_real = vnindex_ret is not None  # True = có data thực, False = phải fallback

    if not vnindex_real:
        vnindex_ret = _to_float(
            context.get("vnindex_return_20d") or
            context.get("market_return_20d")
        )
        if vnindex_ret is not None:
            vnindex_real = True  # context có data

    if not vnindex_real:
        # Không có VNINDEX data thực → absolute mode
        vnindex_ret = None

    # RS = stock / market (tránh chia 0)
    import math
    if math.isnan(stock_ret): return 0, ""

    # Không có VNINDEX data thực → absolute mode
    if not vnindex_real or vnindex_ret is None:
        # Absolute mode: score dựa trên return tuyệt đối của cổ phiếu
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


def score_52w_high(row: dict) -> tuple[int, str]:
    """
    52-Week High proximity / breakout.
    Dùng high_52w thực từ OHLCV 12M (tính trong get_ta của step_snapshot_v2).
    Không dùng proxy ema200+atr — không chính xác với cổ phiếu biến động cao.
    """
    price    = _to_float(row.get("price"))
    high_52w = _to_float(row.get("high_52w"))
    low_52w  = _to_float(row.get("low_52w"))

    if price is None or price <= 0 or high_52w is None or high_52w <= 0:
        return 0, ""

    pct_from_high = (price - high_52w) / high_52w * 100

    score = 0
    if   pct_from_high > 0:      score = +7   # Phá đỉnh 52W
    elif pct_from_high > -5:     score = +3   # Trong 5% dưới đỉnh
    elif pct_from_high > -20:    score =  0   # Neutral
    elif pct_from_high > -50:    score = -3   # Xa đỉnh
    else:                        score = -5   # Gần đáy 52W

    label = f"52W_hi={pct_from_high:+.1f}% {score:+d}"
    return score, label


def score_roc10(row: dict) -> tuple[int, str]:
    """
    Rate of Change 10 ngày — tính thực từ OHLCV trong step_snapshot_v2.
    roc_10 = (close_today / close_10d_ago - 1) × 100
    """
    roc = _to_float(row.get("roc_10"))
    if roc is None:
        return 0, ""

    if   roc >  5: score = +3
    elif roc >  2: score = +1
    elif roc > -2: score =  0
    elif roc > -5: score = -1
    else:          score = -3
    return score, f"ROC10={roc:+.1f}% {score:+d}"


def score_nr7(row: dict) -> tuple[int, str]:
    """
    NR7: Today range < range of every day in last 7 days.
    Dùng _ohlcv_5d (5 ngày) làm proxy cho NR7 check.
    NR4 nếu range hôm nay nhỏ nhất trong 5 ngày.
    """
    ohlcv = row.get("_ohlcv_5d") or []
    if not isinstance(ohlcv, list) or len(ohlcv) < 4:
        return 0, ""

    # Tính range từng ngày
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

    # NR setup: today range là nhỏ nhất
    is_nr = today_range <= min(prev_ranges)
    # Compression ratio: today / avg prev
    avg_prev = sum(prev_ranges) / len(prev_ranges)
    compression = today_range / avg_prev if avg_prev > 0 else 1.0

    score = 0
    if is_nr and compression < 0.6:
        score = +3   # Squeeze mạnh — sắp breakout
    elif is_nr and compression < 0.8:
        score = +2   # Squeeze vừa
    elif compression < 0.7:
        score = +1   # Range co lại
    # Không có điểm âm — NR chỉ là neutral-to-bullish setup

    label = f"NR={'Y' if is_nr else 'N'} compress={compression:.2f} {score:+d}"
    return score, label


def score_bid_ask_imbalance(row: dict) -> tuple[int, str]:
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

    # Parse bid/ask 3 levels
    # KBS order_book() trả bid/ask price bằng VND thực (vd: 15050)
    # trong khi price từ VCI intraday là nghìn VND (vd: 15.0)
    # → Normalize: nếu bid/ask price >> price thì chia 1000
    bids, asks = [], []
    for i in (1, 2, 3):
        bp = _to_float(row.get(f"bid_price_{i}"))
        bv = _to_float(row.get(f"bid_vol_{i}"), 0) or 0
        ap = _to_float(row.get(f"ask_price_{i}"))
        av = _to_float(row.get(f"ask_vol_{i}"), 0) or 0
        # Normalize đơn vị price: KBS trả VND thực, price là nghìn VND
        # vd: bid_price=5170 VND, price=5.17 nghìn VND → chia 1000
        import math
        if bp and not math.isnan(bp) and bp > price * 10:
            bp = bp / 1000
        if ap and not math.isnan(ap) and ap > price * 10:
            ap = ap / 1000
        # NaN guard + vol threshold
        if bp and not math.isnan(bp) and bp > 0 and bv >= WALL_MIN_VOL:
            bids.append((bp, bv))
        if ap and not math.isnan(ap) and ap > 0 and av >= WALL_MIN_VOL:
            asks.append((ap, av))

    if not bids and not asks:
        return 0, ""

    score = 0
    parts = []

    # ── ASK side: tường bán phía trên → rào cản tăng ──
    ask_near = [(p, v) for p, v in asks
                if 0 < (p - price) / price <= NEAR_PCT]
    ask_mid  = [(p, v) for p, v in asks
                if NEAR_PCT < (p - price) / price <= MID_PCT]

    if ask_near:
        # Wall sát giá: khó vượt ngay, TP bị chặn → penalty nặng
        best = max(ask_near, key=lambda x: x[1])
        pct  = (best[0] - price) / price * 100
        wall_score = -2
        score += wall_score
        parts.append(f"AskWall≤2%@{best[0]:.1f}({best[1]/1000:.0f}K) {wall_score:+d}")
    elif ask_mid:
        # Wall xa hơn: giá còn dư địa nhỏ
        best = max(ask_mid, key=lambda x: x[1])
        pct  = (best[0] - price) / price * 100
        wall_score = -1
        score += wall_score
        parts.append(f"AskWall2-5%@{best[0]:.1f}({best[1]/1000:.0f}K) {wall_score:+d}")
    else:
        # Không có ask wall đáng kể → đường lên thông thoáng
        score += 1
        parts.append("AskClear +1")

    # ── BID side: tường mua phía dưới → sàn đỡ ──
    # Bid AT price (pct=0) = tường mua ngay tại giá → sàn đỡ mạnh nhất
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


def score_ff_room(row: dict) -> tuple[int, str]:
    """
    Foreign room utilization.
    ff_room = % room còn lại (0–100).
    Room < 5% = ngoại không thể mua thêm → áp lực cung.
    """
    room = _to_float(row.get("ff_room"))
    if room is None:
        return 0, ""

    # ff_room = fr_available_percentage × 100 từ VCI (% room ngoại còn có thể mua)
    # PNJ ~1%, KBC ~41%, GVR ~12%, LDG ~50%
    # room âm hoặc = 0: mã không có room ngoại (total_room=0%)
    # VD: SGT=-5.48%, HRC=-0.56% → ngoại không được mua → -7
    if room > 100:
        return 0, f"FFroom={room:.1f}(invalid>100) +0"
    if   room > 30: score = +3
    elif room > 10: score =  0
    elif room >  5: score = -3
    else:           score = -7   # bao gồm âm và 0-5%

    label = f"FFroom={room:.1f}% {score:+d}"
    return score, label


def score_dividend_yield(row: dict) -> tuple[int, str]:
    """
    Dividend yield score.
    r_div_yield từ finance cache — % yield theo năm.
    """
    yield_pct = _to_float(row.get("r_div_yield"))
    if yield_pct is None or yield_pct <= 0:
        return 0, ""

    # KBS trả về decimal: 0.02 = 2%, 0.05 = 5%
    # Normalize về percent
    if yield_pct < 1.0:
        yield_pct_pct = yield_pct * 100
    else:
        yield_pct_pct = yield_pct  # đã là percent
    yield_pct = yield_pct_pct

    # Threshold phù hợp thị trường VN (yield thường 1-8%)
    if   yield_pct > 6: score = +3
    elif yield_pct > 4: score = +2
    elif yield_pct > 2: score = +1
    else:               score =  0   # Không có cổ tức ≠ xấu

    label = f"DivYield={yield_pct:.1f}% {score:+d}"
    return score, label


def score_eps_consistency(row: dict) -> tuple[int, str]:
    """
    EPS consistency: số quý liên tiếp EPS tăng YoY.
    Cần: is_eps_q1..q4 fields hoặc tính từ is_profit_growth_yoy consistency.
    Hiện tại dùng is_profit_growth_yoy (latest) + EPS growth pattern.
    """
    # Nếu có eps_consistency field (sau khi thêm vào step_finance_scan)
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

    # Fallback: dùng profit_growth_yoy hiện tại
    profit_yoy = _to_float(row.get("is_profit_growth_yoy"))
    profit_qoq = _to_float(row.get("is_profit_growth"))  # QoQ

    # Guard: None hoặc NaN → skip
    if profit_yoy is None:
        return 0, ""

    import math
    if math.isnan(profit_yoy):
        return 0, ""

    score = 0
    pct = profit_yoy * 100  # convert sang %

    if pct > 30:
        # QoQ phải có và dương để confirm momentum — nếu không có QoQ data thì chỉ +2
        if profit_qoq is not None and not math.isnan(profit_qoq) and profit_qoq > 0:
            score = +3
        else:
            score = +2   # YoY tốt nhưng không confirm QoQ
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


def score_insider(row: dict) -> tuple[int, str]:
    """
    Insider buy/sell activity.
    insider_count + insider_latest từ deep_raw (Trading.insider_deal).
    """
    # Ưu tiên buy_count/sell_count (phân tách 90 ngày, limit=20)
    buy_cnt  = int(_to_float(row.get("insider_buy_count"),  0) or 0)
    sell_cnt = int(_to_float(row.get("insider_sell_count"), 0) or 0)
    total    = buy_cnt + sell_cnt

    # Fallback: dùng latest action nếu chưa có count phân tách
    if total == 0:
        latest = str(row.get("insider_latest") or "").lower()
        if not latest:
            return 0, ""
        is_buy  = any(k in latest for k in ["mua", "buy", "purchase", "acqui"])
        is_sell = any(k in latest for k in ["bán", "sell", "dispos"])
        if   is_buy:  return +3, f"Insider=BUY(latest) +3"
        elif is_sell: return -3, f"Insider=SELL(latest) -3"
        return 0, ""

    # Scoring dựa trên số lượng giao dịch 90 ngày
    net = buy_cnt - sell_cnt
    if   net >= 3:  score = +5   # Nhiều giao dịch mua
    elif net >= 1:  score = +3
    elif net == 0:  score =  0   # Cân bằng
    elif net >= -2: score = -3
    else:           score = -5   # Nhiều giao dịch bán

    label = f"Insider=B{buy_cnt}/S{sell_cnt}(90d) net={net:+d} {score:+d}"
    return score, label


# =====================================================
# NORMALIZE + WEIGHT
# =====================================================

def _normalize_and_weight(raw_scores: dict) -> tuple[float, dict]:
    norm = {}
    for g, cap in GROUP_CAPS.items():
        raw = raw_scores.get(g, 0) or 0
        norm[g] = max(-1.0, min(1.0, raw / cap))

    weighted_sum = sum(
        SCORING_WEIGHTS.get(g, 0) * norm[g]
        for g in SCORING_WEIGHTS
    )
    return round(weighted_sum * 100, 2), norm


def _confluence_bonus(norm_scores: dict) -> tuple[int, str]:
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
    1. Lấy raw group scores từ V3 scorer
    2. Tính thêm 9 extended indicators
    3. Merge vào group scores tương ứng
    4. Normalize → weighted sum → confluence → final score
    """
    sym = row.get("symbol", "?")

    # ── Base: gọi V3 scorer ──
    v3 = _score_symbol_v3(row, context, news_scores, order_flow_map)

    # ── Raw group scores từ V3 ──
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

    ext_sigs = []  # extended indicator signals log

    # ── Extended: Trend group ──
    rs_score,   rs_label   = score_rs_vnindex(row, context)
    w52_score,  w52_label  = score_52w_high(row)
    raw["trend"] += rs_score + w52_score
    if rs_label:  ext_sigs.append(rs_label)
    if w52_label: ext_sigs.append(w52_label)

    # ── Extended: Momentum group ──
    roc_score, roc_label = score_roc10(row)
    raw["momentum"] += roc_score
    if roc_label: ext_sigs.append(roc_label)

    # ── Extended: Volatility group ──
    nr7_score, nr7_label = score_nr7(row)
    raw["volatility"] += nr7_score
    if nr7_label: ext_sigs.append(nr7_label)

    # ── Extended: Depth group ──
    ba_score, ba_label = score_bid_ask_imbalance(row)
    raw["depth"] += ba_score
    if ba_label: ext_sigs.append(ba_label)

    # ── Extended: FF group ──
    room_score, room_label = score_ff_room(row)
    raw["ff"] += room_score
    if room_label: ext_sigs.append(room_label)

    # ── Extended: Fundamental group ──
    div_score, div_label = score_dividend_yield(row)
    raw["fundamental"] += div_score
    if div_label: ext_sigs.append(div_label)

    # ── Extended: Growth group ──
    eps_score,     eps_label     = score_eps_consistency(row)
    insider_score, insider_label = score_insider(row)
    raw["growth"] += eps_score
    # Insider → cộng vào fundamental (smart money signal)
    raw["fundamental"] += insider_score
    if eps_label:     ext_sigs.append(eps_label)
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
        # Extended raw scores
        "ext_rs_score"     : rs_score,
        "ext_52w_score"    : w52_score,
        "ext_roc_score"    : roc_score,
        "ext_nr7_score"    : nr7_score,
        "ext_ba_score"     : ba_score,
        "ext_room_score"   : room_score,
        "ext_div_score"    : div_score,
        "ext_eps_score"    : eps_score,
        "ext_insider_score": insider_score,
        "ext_signals"      : " | ".join(ext_sigs) if ext_sigs else "",
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
# MAIN
# =====================================================

def run():
    log.info(f"=== SCORING V2 START ({now_ict():%Y-%m-%d %H:%M:%S} ICT) ===")
    log.info(f"Scoring version: {SCORING_VERSION}")
    log.info(f"Thresholds: SB≥{THRESHOLD_STRONG_BUY} | BUY≥{THRESHOLD_BUY} | "
             f"NEU≥{THRESHOLD_NEUTRAL} | SELL≥{THRESHOLD_SELL}")
    log.info(f"Extended: RS, 52W, ROC10, NR7, BidAsk, FFroom, DivYield, EPScons, Insider")

    deep_raw     = load_json("deep_raw_v2.json")
    context_list = load_json("market/context.json") or load_json("context.json")
    today_index  = load_json("news/today_index.json") or load_json("news_today_index.json")
    order_flow   = load_json("order_flow_v2.json")

    if not deep_raw:
        log.error("deep_raw_v2.json not found — chạy step_snapshot_v2.py trước")
        return

    ctx = context_list[0] if context_list else {}

    if not order_flow:
        log.warning("order_flow_v2.json not found — order_flow_score = 0")
        order_flow = []

    order_flow_map = {
        r["symbol"]: r
        for r in (order_flow or [])
        if isinstance(r, dict) and r.get("symbol")
    }

    symbols_with_industry = [
        {"symbol": r["symbol"], "icb_name": r.get("industry", "")}
        for r in deep_raw
    ]
    news_scores = build_news_scores(today_index or {}, symbols_with_industry)

    log.info(f"Scoring {len(deep_raw)} symbols...")

    scored_rows = []
    for row in deep_raw:
        result = score_symbol_v2(row, ctx, news_scores, order_flow_map)
        scored_rows.append(result)

        flags_str = ",".join(result.get("pattern_flags") or []) or "-"
        ext       = result.get("ext_signals", "")
        log.info(
            f"  [{result['symbol']:6s}] "
            f"v2={result['total_score']:6.1f} "
            f"(base={result['base_score_v2']:6.1f} conf={result['confluence_bonus']:+d}) "
            f"→ {result['decision']:12s} [{result['confidence']}]"
            + (f"\n    ext: {ext}" if ext else "")
        )

    df = pd.DataFrame(scored_rows)
    save_json("signals_v2.json", df.to_dict(orient="records"))

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
    save_csv("signals_v2.csv", df_csv)

    # Summary log
    decision_counts = df["decision"].value_counts().to_dict()
    log.info(f"Decision distribution: {decision_counts}")

    # Extended indicator coverage
    for field in ["ext_rs_score","ext_52w_score","ext_roc_score","ext_nr7_score",
                  "ext_ba_score","ext_room_score","ext_div_score","ext_eps_score","ext_insider_score"]:
        nonzero = (df[field] != 0).sum() if field in df.columns else 0
        log.info(f"  {field}: {nonzero}/{len(df)} symbols có signal")

    # V3 comparison
    v3_signals = load_json("signals.json")
    if v3_signals:
        v3_df  = pd.DataFrame(v3_signals)[["symbol","decision","total_score"]]
        v2_df  = df[["symbol","decision","total_score"]].copy()
        v3_df.columns = ["symbol","dec3","sc3"]
        v2_df.columns = ["symbol","dec2","sc2"]
        cmp   = pd.merge(v3_df, v2_df, on="symbol", how="inner")
        agree = (cmp["dec3"] == cmp["dec2"]).sum()
        log.info(f"V3 vs V2 agreement: {agree}/{len(cmp)} = {agree/len(cmp)*100:.1f}%")
        diff = cmp[cmp["dec3"] != cmp["dec2"]]
        for _, r in diff.iterrows():
            log.info(f"  DIFF {r.symbol}: v3={r.dec3}({r.sc3:.0f}) → v2={r.dec2}({r.sc2:.1f})")

    log.info(f"Exported signals_v2.json + signals_v2.csv ({len(df)} rows)")
    log.info("=== SCORING V2 DONE ===")


if __name__ == "__main__":
    run()
