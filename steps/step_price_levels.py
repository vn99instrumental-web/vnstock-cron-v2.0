"""
step_price_levels.py — Trade levels (entry / stop / target) sau scoring
========================================================================
Chạy trong cron_intraday.yml SAU step_scoring.py.
Đọc signals.json (đã có decision/confidence/scores + đủ TA fields) và
order_flow.json (POC / value area / buy_ratio intraday).

KHÔNG gọi API — chỉ đọc 2 file output có sẵn.

Phạm vi: CHỈ tính cho decision ∈ {BUY, STRONG BUY} (long-only thị trường VN).
  - SELL / STRONG SELL → exit_trigger cho người đang giữ (không short).
  - NEUTRAL → bỏ qua.

Kiểu entry: HYBRID
  - PULLBACK (mặc định, an toàn): entry tại hỗ trợ gần nhất dưới giá.
  - BREAKOUT (chỉ khi xác nhận lực mua mạnh): entry sát giá hiện tại.
  - GUARD: BULL_TRAP_RISK → cấm breakout, ép pullback.

Phương pháp (đã thống nhất):
  Entry   : pullback về cluster hỗ trợ [ema20, ema50, bb_mid, poc_vol, VAL]
            hoặc breakout sát giá nếu momentum+volume xác nhận.
  Stop    : max(struct_stop, atr_stop); risk ≤ MAX_RISK_PCT, else SKIP.
  Target  : TP1 = entry + 1.5×risk (R:R 1.5, chốt 50%)
            TP2 = min(kháng cự gần nhất, entry + 3×risk)
  R:R gate: RR_headroom < 1.5 → flag TIGHT_HEADROOM.
  VN rules: làm tròn tick, cap TP ở giá trần, cảnh báo SL dưới sàn.

Output:
  output/trade_levels.json  — list dict đầy đủ
  output/trade_levels.csv   — bảng gọn để xem

LƯU Ý dữ liệu (đã verify từ signals.json thật):
  - price = last_close phiên trước (price_type="last_close") → EOD, không realtime.
  - bb_upper/bb_lower ĐÔI KHI BỊ ĐẢO trong data (upper<lower). Code dùng
    min()/max() trên cặp bb để tự sửa, KHÔNG tin tên field.
  - atr_pct theo %.
  - order_flow khớp theo symbol; current_price trong order_flow là intraday
    thật hơn → ưu tiên nếu có.

CHANGELOG:
  v1 (2026-05-31) — initial: hybrid entry, tiered TP, VN tick/band rules.
"""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

os.environ["VNSTOCK_INTERACTIVE"] = "0"
os.environ["VNSTOCK_LANGUAGE"]    = "en"
os.environ["MPLCONFIGDIR"]        = "/home/runner/.config/matplotlib"
os.makedirs("/home/runner/.vnstock",           exist_ok=True)
os.makedirs("/home/runner/.config/matplotlib", exist_ok=True)

import logging

from utils.helpers import now_ict
from utils.cache import load_json, save_json, save_csv

import pandas as pd

logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s %(levelname)s %(message)s')
log = logging.getLogger(__name__)

# =====================================================
# Config
# =====================================================

SIGNALS_FILE    = "signals.json"
ORDER_FLOW_FILE = "order_flow.json"
OUT_JSON        = "trade_levels.json"
OUT_CSV         = "trade_levels.csv"

# Chỉ tính levels cho các decision này
BUY_DECISIONS = {"BUY", "STRONG BUY"}

# Risk management
MAX_RISK_PCT     = 7.0    # risk tối đa cho 1-2 ngày (≈ biên HOSE 1 phiên); >7% → SKIP
TARGET_RISK_PCT  = 3.0    # ngưỡng "đẹp"
ATR_STOP_MULT    = 1.5    # atr_stop = entry - 1.5×ATR
STRUCT_BUFFER    = 0.3    # struct_stop = support - 0.3×ATR
TP1_RR           = 1.5    # R:R cho TP1
TP2_RR_CAP       = 3.0    # cap TP2 ở entry + 3×risk nếu kháng cự quá xa
MIN_RR_HEADROOM  = 1.5    # RR tới kháng cự < ngưỡng → flag
TP_MIN_GAP_ATR   = 0.5    # TP2 phải cao hơn TP1 tối thiểu 0.5×ATR (tránh trùng)
TP_MIN_GAP_PCT   = 0.03   # ...hoặc tối thiểu 3% TP1 (lấy max 2 ngưỡng)

# Breakout entry conditions (HYBRID)
BREAKOUT_MOM_MIN     = 14     # momentum_score ≥ 14 (~60% cap 23)
BREAKOUT_BUY_RATIO   = 0.55   # buy_ratio_today >
BREAKOUT_VOL_RATIO   = 1.5    # vol_ma_ratio > (nếu không có vol_spike_pct>0)

# VN price band theo sàn (so với reference price)
PRICE_BAND = {"HSX": 0.07, "HOSE": 0.07, "HNX": 0.10, "UPCOM": 0.15}


# =====================================================
# VN tick size + rounding
# =====================================================

def _tick_size(price: float, exchange: str) -> float:
    """Bước giá HOSE. HNX/UPCOM dùng 100đ (0.1 nghìn) đơn giản hóa."""
    ex = (exchange or "").upper()
    if ex in ("HSX", "HOSE"):
        if price < 10:    return 0.01    # <10k → 10đ (đơn vị nghìn)
        elif price < 50:  return 0.05    # 10–50k → 50đ
        else:             return 0.10    # ≥50k → 100đ
    # HNX / UPCOM: 100đ = 0.1 nghìn (đơn giản)
    return 0.10


def _round_tick(price: float, exchange: str, mode: str = "nearest") -> float:
    """Làm tròn về bước giá hợp lệ. mode: nearest | down | up."""
    if price is None or price <= 0:
        return price
    tick = _tick_size(price, exchange)
    n = price / tick
    if mode == "down":
        n = int(n)
    elif mode == "up":
        n = int(n) + (0 if n == int(n) else 1)
    else:
        n = round(n)
    return round(n * tick, 2)


# =====================================================
# Helpers
# =====================================================

def _f(v):
    """Safe float, NaN/None → None."""
    if v is None:
        return None
    try:
        f = float(v)
        if f != f:   # NaN
            return None
        return f
    except (TypeError, ValueError):
        return None


def _bb_bounds(sig: dict) -> tuple[float | None, float | None]:
    """
    Trả (bb_low, bb_high) ĐÚNG dù field bị đảo.
    signals.json đôi khi có bb_upper < bb_lower (bug có sẵn) → dùng min/max.
    """
    a = _f(sig.get("bb_upper"))
    b = _f(sig.get("bb_lower"))
    vals = [x for x in (a, b) if x is not None]
    if not vals:
        return None, None
    return min(vals), max(vals)


def _swing(of_data: dict, key: str):
    """min low / max high của history_5d hoặc _ohlcv_5d."""
    rows = None
    if of_data:
        rows = of_data.get("history_5d")
    return rows


# =====================================================
# Core: compute levels for one BUY symbol
# =====================================================

def compute_levels(sig: dict, of_summary: dict, of_full: dict) -> dict:
    sym       = sig.get("symbol")
    exchange  = sig.get("exchange", "HSX")
    decision  = sig.get("decision", "")
    conf      = sig.get("confidence", "MEDIUM")
    flags     = sig.get("pattern_flags", []) or []

    # ── Giá hiện tại: ưu tiên order_flow current_price (intraday) ──
    price = _f(of_summary.get("current_price")) or _f(sig.get("price"))
    if not price or price <= 0:
        return {"symbol": sym, "skip": "no_price"}

    atr      = _f(sig.get("atr")) or (price * 0.02)   # fallback 2%
    bb_low, bb_high = _bb_bounds(sig)
    ema20    = _f(sig.get("ema20"))
    ema50    = _f(sig.get("ema50"))
    supertr  = _f(sig.get("supertrend"))
    poc_vol  = _f(of_summary.get("poc_by_volume"))
    val      = _f(of_summary.get("value_area_low"))
    vah      = _f(of_summary.get("value_area_high"))

    # 5d high/low từ _ohlcv_5d (signals) hoặc history_5d (order_flow)
    ohlcv = sig.get("_ohlcv_5d") or (of_full.get("history_5d") if of_full else None)
    low_5d = high_5d = None
    if ohlcv:
        lows  = [_f(r.get("low"))  for r in ohlcv if _f(r.get("low"))  is not None]
        highs = [_f(r.get("high")) for r in ohlcv if _f(r.get("high")) is not None]
        low_5d  = min(lows)  if lows  else None
        high_5d = max(highs) if highs else None

    # ── Cluster hỗ trợ (< price) và kháng cự (> price) ──
    support_candidates = [v for v in (ema20, ema50, bb_low, poc_vol, val, low_5d)
                          if v is not None and v < price]
    resist_candidates  = [v for v in (bb_high, vah, high_5d)
                          if v is not None and v > price]

    nearest_support = max(support_candidates) if support_candidates else None
    nearest_resist  = min(resist_candidates)  if resist_candidates  else None

    # ════════════════════════════════════════════════
    # HYBRID entry selection
    # ════════════════════════════════════════════════
    momentum   = _f(sig.get("momentum_score")) or 0
    buy_ratio  = _f(of_summary.get("buy_ratio_today"))
    vol_spike  = _f(of_summary.get("vol_spike_pct"))
    vol_ratio  = _f(sig.get("vol_ma_ratio"))
    bull_trap  = "BULL_TRAP_RISK" in flags

    breakout_ok = (
        momentum >= BREAKOUT_MOM_MIN
        and (buy_ratio is not None and buy_ratio > BREAKOUT_BUY_RATIO)
        and ((vol_spike is not None and vol_spike > 0)
             or (vol_ratio is not None and vol_ratio > BREAKOUT_VOL_RATIO))
        and not bull_trap
    )

    if breakout_ok:
        entry_style = "BREAKOUT"
        entry       = price                      # vào sát giá
        entry_low   = _round_tick(price * 0.998, exchange, "down")
        entry_high  = _round_tick(price, exchange, "up")
    else:
        entry_style = "PULLBACK"
        if nearest_support is not None and (price - nearest_support) <= 1.5 * atr:
            entry = nearest_support              # chờ về hỗ trợ gần
        else:
            entry = price - 0.5 * atr            # hỗ trợ quá xa → đặt sát giá để khớp
        entry_low  = _round_tick(min(entry, price), exchange, "down")
        entry_high = _round_tick(price, exchange, "nearest")
        entry      = _round_tick(entry, exchange, "nearest")

    # ════════════════════════════════════════════════
    # STOP LOSS
    # Ưu tiên cấu trúc (supertrend/VAL/low_5d) — mã biến động cao (atr_pct
    # lớn) nếu cứng atr×1.5 sẽ luôn cho risk >5% và bị SKIP oan. Cấu trúc
    # cho stop hợp lý hơn. atr_stop chỉ dùng khi không có cấu trúc dưới entry.
    # ════════════════════════════════════════════════
    struct_levels = [v for v in (supertr, val, low_5d) if v is not None and v < entry]
    struct_stop = (max(struct_levels) - STRUCT_BUFFER * atr) if struct_levels else None
    atr_stop    = entry - ATR_STOP_MULT * atr

    if struct_stop is not None:
        # Có cấu trúc: dùng struct_stop, nhưng không để quá sát (nhiễu) —
        # nếu struct_stop gần entry hơn 0.5×ATR thì nới ra để tránh stop nhiễu.
        min_dist = 0.5 * atr
        if (entry - struct_stop) < min_dist:
            stop_loss = entry - min_dist
        else:
            stop_loss = struct_stop
    else:
        stop_loss = atr_stop
    stop_loss = _round_tick(stop_loss, exchange, "down")

    risk_per_share = entry - stop_loss
    risk_pct = round(risk_per_share / entry * 100, 2) if entry else None

    flags_out = list(flags)
    skip = None
    if risk_pct is None or risk_per_share <= 0:
        skip = "invalid_stop"
    elif risk_pct > MAX_RISK_PCT:
        flags_out.append("SKIP_WIDE_STOP")
        skip = "wide_stop"

    # ════════════════════════════════════════════════
    # TAKE PROFIT (tiered)
    # ════════════════════════════════════════════════
    tp1 = tp2 = rr_headroom = None
    if not skip:
        band     = PRICE_BAND.get((exchange or "HSX").upper(), 0.07)
        ceiling  = price * (1 + band)            # giá trần phiên
        min_gap  = max(TP_MIN_GAP_ATR * atr, 0)  # khoảng cách tối thiểu TP1↔TP2

        # ── TP1: R-multiple, cap ở trần ──
        tp1 = entry + TP1_RR * risk_per_share
        tp1_capped = False
        if tp1 > ceiling:
            tp1 = ceiling
            tp1_capped = True

        # ── TP2: kháng cự gần nhất (cap entry+3R), cap ở trần ──
        if nearest_resist is not None:
            tp2_raw = min(nearest_resist, entry + TP2_RR_CAP * risk_per_share)
            rr_headroom = round((nearest_resist - entry) / risk_per_share, 2)
        else:
            tp2_raw = entry + TP2_RR_CAP * risk_per_share
        tp2 = min(tp2_raw, ceiling)

        # ── Đảm bảo TP2 tách biệt TP1 (FIX: tránh tp1 == tp2) ──
        # Khoảng cách tối thiểu: max(0.5×ATR, 3% TP1)
        gap_needed = max(min_gap, tp1 * TP_MIN_GAP_PCT)
        if tp2 < tp1 + gap_needed:
            # TP2 không đủ cao hơn TP1
            room_to_ceiling = ceiling - tp1
            if room_to_ceiling >= gap_needed and not tp1_capped:
                # Còn chỗ tới trần → đẩy TP2 lên sát trần
                tp2 = min(tp1 + gap_needed, ceiling)
                flags_out.append("TP2_FORCED_GAP")
            elif tp1_capped:
                # TP1 đã đụng trần → không thể có TP2 cao hơn trong phiên.
                # Lùi TP1 xuống để TP2 = trần, tạo 2 mức phân biệt.
                tp2 = ceiling
                tp1 = tp2 - gap_needed
                flags_out.append("TP1_PULLED_BACK")
                flags_out.append("TP_NEAR_CEILING")
            else:
                # Room quá hẹp, không tách được → chỉ 1 mục tiêu
                tp2 = None
                flags_out.append("SINGLE_TP_ONLY")

        tp1 = _round_tick(tp1, exchange, "down")
        if tp2 is not None:
            tp2 = _round_tick(tp2, exchange, "down")
            # round có thể kéo tp2 về == tp1 với mã giá thấp (tick lớn) → ép lệch 1 tick
            if tp2 <= tp1:
                tp2 = _round_tick(tp1 + max(gap_needed, _tick_size(tp1, exchange)),
                                  exchange, "up")
                if tp2 > _round_tick(ceiling, exchange, "down"):
                    tp2 = None
                    if "SINGLE_TP_ONLY" not in flags_out:
                        flags_out.append("SINGLE_TP_ONLY")

        if tp1 >= _round_tick(ceiling, exchange, "down") and "TP_NEAR_CEILING" not in flags_out:
            flags_out.append("TP1_AT_CEILING")

        if rr_headroom is not None and rr_headroom < MIN_RR_HEADROOM:
            flags_out.append("TIGHT_HEADROOM")

        # SL dưới giá sàn → cảnh báo gap risk
        floor = price * (1 - band)
        if stop_loss < floor:
            flags_out.append("STOP_BELOW_FLOOR")

    # ── Sizing hint theo confidence ──
    if bull_trap or conf == "LOW":
        size_hint = "NO_TRADE"
    elif conf == "HIGH":
        size_hint = "FULL"
    else:
        size_hint = "HALF"
    if skip:
        size_hint = "NO_TRADE"

    rr_tp1 = round((tp1 - entry) / risk_per_share, 2) if (tp1 and not skip) else None

    levels_used = []
    for name, v in (("ema20", ema20), ("ema50", ema50), ("bb", bb_low),
                    ("poc_vol", poc_vol), ("value_area_low", val),
                    ("supertrend", supertr), ("low_5d", low_5d), ("atr", atr)):
        if v is not None:
            levels_used.append(name)

    return {
        "symbol"        : sym,
        "exchange"      : exchange,
        "decision"      : decision,
        "confidence"    : conf,
        "entry_style"   : entry_style,
        "price"         : round(price, 2),
        "entry"         : entry if not skip else None,
        "entry_low"     : entry_low if not skip else None,
        "entry_high"    : entry_high if not skip else None,
        "stop_loss"     : stop_loss if not skip else None,
        "risk_pct"      : risk_pct,
        "tp1"           : tp1,
        "tp2"           : tp2,
        "rr_tp1"        : rr_tp1,
        "rr_headroom"   : rr_headroom,
        "size_hint"     : size_hint,
        "nearest_support": round(nearest_support, 2) if nearest_support else None,
        "nearest_resist" : round(nearest_resist, 2)  if nearest_resist  else None,
        "levels_used"   : ",".join(levels_used),
        "flags"         : ",".join(flags_out) if flags_out else "",
        "skip"          : skip or "",
    }


# =====================================================
# SELL side — exit trigger cho người đang giữ
# =====================================================

def compute_exit(sig: dict, of_summary: dict) -> dict:
    sym      = sig.get("symbol")
    exchange = sig.get("exchange", "HSX")
    decision = sig.get("decision", "")
    price = _f(of_summary.get("current_price")) or _f(sig.get("price")) or 0

    supertr = _f(sig.get("supertrend"))
    val     = _f(of_summary.get("value_area_low"))
    ema20   = _f(sig.get("ema20"))
    triggers = [v for v in (supertr, val, ema20) if v is not None and v < price]
    exit_trigger = max(triggers) if triggers else None

    return {
        "symbol"      : sym,
        "exchange"    : exchange,
        "decision"    : decision,
        "confidence"  : sig.get("confidence", ""),
        "entry_style" : "EXIT",
        "price"       : round(price, 2) if price else None,
        "exit_trigger": _round_tick(exit_trigger, exchange, "nearest") if exit_trigger else None,
        "note"        : ("Thoát ngay (market)" if decision == "STRONG SELL"
                         else "Thoát khi giá thủng exit_trigger"),
    }


# =====================================================
# Main
# =====================================================

def run() -> list:
    log.info("=== step_price_levels: START ===")

    signals = load_json(SIGNALS_FILE)
    if not signals:
        log.error(f"{SIGNALS_FILE} not found — chạy step_scoring trước")
        return []

    of_list = load_json(ORDER_FLOW_FILE) or []
    of_by_sym = {}
    for item in of_list:
        s = item.get("symbol")
        if s:
            of_by_sym[s] = item

    if isinstance(signals, dict):
        signals = list(signals.values())

    buy_results  = []
    exit_results = []

    for sig in signals:
        decision = sig.get("decision", "")
        sym      = sig.get("symbol")
        of_full  = of_by_sym.get(sym, {})
        of_sum   = of_full.get("summary", {}) if of_full else {}

        if decision in BUY_DECISIONS:
            res = compute_levels(sig, of_sum, of_full)
            buy_results.append(res)
            if res.get("skip"):
                log.info(f"  {sym} [{decision}] {res['entry_style']} "
                         f"→ SKIP ({res['skip']})")
            else:
                log.info(f"  {sym} [{decision}/{res['confidence']}] "
                         f"{res['entry_style']} entry={res['entry']} "
                         f"SL={res['stop_loss']} ({res['risk_pct']}%) "
                         f"TP1={res['tp1']} TP2={res['tp2']} "
                         f"RR={res['rr_tp1']} size={res['size_hint']}")
        elif decision in ("SELL", "STRONG SELL"):
            exit_results.append(compute_exit(sig, of_sum))

    # ── Save JSON ──
    out = {
        "generated_at": now_ict().isoformat(),
        "buy_count"   : len(buy_results),
        "exit_count"  : len(exit_results),
        "buy_levels"  : buy_results,
        "exit_levels" : exit_results,
    }
    save_json(OUT_JSON, out)

    # ── Save CSV (buy levels — phần chính) ──
    if buy_results:
        df = pd.DataFrame(buy_results)
        col_order = ["symbol", "exchange", "decision", "confidence",
                     "entry_style", "price", "entry_low", "entry", "entry_high",
                     "stop_loss", "risk_pct", "tp1", "tp2", "rr_tp1",
                     "rr_headroom", "size_hint", "nearest_support",
                     "nearest_resist", "levels_used", "flags", "skip"]
        cols = [c for c in col_order if c in df.columns]
        save_csv(OUT_CSV, df[cols])

    log.info(f"Done: {len(buy_results)} BUY levels, "
             f"{len(exit_results)} exit triggers")
    log.info("=== step_price_levels: DONE ===")
    return buy_results


if __name__ == "__main__":
    run()
