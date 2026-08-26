"""
v2f_step_scoring_v4.py — Scoring engine V4 "RCEG" (SHADOW #2)
=============================================================================
Chạy trong v2f_cron_intraday.yml SAU v2f_step_scoring_v3.py (V3).
KHÔNG thay V3/V2.3 — chạy song song, ledger RIÊNG, so head-to-head.

KHÁC V3 DUY NHẤT: lớp "regime gate" (RCEG). Điểm mỗi factor được nhân thêm
GATE[factor][regime] ∈ [0,1] tuỳ chế độ thị trường hiện tại. Mọi hàm chấm
tín hiệu (sc_*), confluence supergroups, ngưỡng decision... DÙNG CHUNG với V3
(import trực tiếp) → khác biệt V4 vs V3 CHỈ là cái gate, không lẫn khác biệt
lặt vặt → so sánh sạch.

GATE hiện tại (utils/v2f_registry.GATE):
  - mean_reversion: UPTREND/SIDEWAYS=0, DOWNTREND/DEEP_DOWN=1  ← ĐÃ ĐO (B1 29/07)
  - còn lại: 1.0 mọi regime ("inherited-pending" — chờ Phase A đo)

CÁCH B (chọn theo DESIGN_V2F_SCORING_V4_RCEG mục 5): gate nhân THẲNG vào
weight, KHÔNG tái chuẩn hoá mẫu số. Hệ quả: khi factor bị tắt (VD MR trong
uptrend), tổng điểm CO LẠI (biên độ hẹp) — hệ thống "nói nhỏ" khi ít tín hiệu
đáng tin, thay vì bơm trọng số sang factor chưa kiểm.

REGIME lấy từ context.json (market_regime, do step3_context tính từ VNINDEX).
Fallback: _ctx_regime trong row → UNKNOWN (khi UNKNOWN, MR gate=0 cho an toàn).

INPUT  (zero API): v2f_signals.json + context.json  (giống hệt V3)
OUTPUT : v2f_signals_v4.json

FAIL-SOFT: lỗi per-symbol → skip; crash toàn cục → exit 0 (không chặn pipeline).

CHANGELOG:
  v4.0 (2026-07-29) — initial RCEG shadow theo DESIGN_V2F_SCORING_V4_RCEG.md.
                      Chỉ MR gated (measured); các factor khác inherited-pending.
"""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

os.environ["VNSTOCK_INTERACTIVE"] = "0"
os.environ["VNSTOCK_LANGUAGE"]    = "en"
os.environ["MPLCONFIGDIR"]        = "/home/runner/.config/matplotlib"

import logging
import traceback
from datetime import datetime
from collections import Counter

from utils.cache import load_json, save_json
from utils.of_buy_pressure import buy_pressure_pts
from utils.regime_v42 import classify_regime_breadth, more_bearish
from utils.v2f_registry import (REGISTRY_VERSION, FACTORS, FACTOR_WEIGHTS,
                                THRESHOLDS, CONFLUENCE_BONUS,
                                CONFLUENCE_MIN_NORM, SIGNALS,
                                validate_registry, active_signals,
                                factor_caps,
                                GATE_VERSION, REGIMES, gate_for)
# Dùng CHUNG bộ hàm chấm + confluence + passthrough của V3 (isolate đúng gate)
from steps.v2f_step_scoring_v3 import (FN_TABLE, SUPERGROUPS,
                                       _is_v23_scoring_field)

logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s %(levelname)s %(message)s')
log = logging.getLogger(__name__)

SCORING_VERSION = "v4.10"  # regime LIVE moi run (Op1: m2=hom qua+hom nay, dau-m2, +RECOVERY) an gate; hysteresis NGAY->RUN; GATE_VERSION 6->7 (cot RECOVERY). Bump -> reset forward bucket. Cu(v4.9):          # GATE fund+growth DOWN 0.8 / DEEP 0.6 (Đường 2, chống value-trap) + shadow NGƯỢC gate=1.0 (score_trade_gate1/decision_gate1) để forward so gated vs cũ | GATE_VERSION 6 | giữ: MR-on, context=0, extras co w_reg, extras-guard, altfund shadow | trước: v4.8
# ── v4.10 (shadow-only, CỐ Ý KHÔNG bump SCORING_VERSION — production score_trade/
#    decision/score_hold KHÔNG đổi 1 ly → bucket forward v4.9 KHÔNG bị reset):
#      + shadow RANK cross-sectional: score_trade_rank / decision_rank / _rank_delta
#        (fundamental=rank_fund_grp, growth=rank_growth_grp; MR/breakout/flow giữ)
#      + PARITY extras-guard cho nomr & altfund (trước chỉ production/gate1 có) →
#        so-quyết-định sạch. Thêm _nomr_delta / _altfund_delta cho đối xứng với
#        _gate1_delta. KHÔNG có thay đổi nào chạm điểm/quyết định PRODUCTION.
SIGNALS_IN      = "v2f_signals.json"
CONTEXT_FILE    = "context.json"
SIGNALS_OUT     = "v2f_signals_v4.json"
REGIME_STATE    = "v2f_v4_regime_state.json"   # state hysteresis (persist qua output/)
HYST_SESSIONS   = 2               # regime mới phải giữ ≥2 PHIÊN mới đổi gate (A4)

_VALID_REGIMES = set(REGIMES)


def _resolve_regime(ctx: dict, row: dict) -> str:
    r = (ctx.get("market_regime") or row.get("_ctx_regime")
         or row.get("market_regime") or "UNKNOWN")
    r = str(r).upper()
    return r if r in _VALID_REGIMES else "UNKNOWN"


def _run_date(ctx: dict, rows: list) -> str:
    st = ctx.get("_snap_time") or (rows[0].get("snap_time") if rows else None)
    return str(st)[:10] if st else datetime.now().strftime("%Y-%m-%d")


def _apply_hysteresis(raw: str, run_date: str | None = None):
    """Regime dùng để gate chỉ đổi khi raw giữ >=HYST_RUNS RUN LIÊN TIẾP
    (đếm theo LẦN CHẠY intraday, KHÔNG theo ngày) — để regime LIVE cập nhật
    ngay trong phiên. run_date giữ trong chữ ký cho tương thích, không dùng.
    Trả (effective_regime, status_str). State lưu ở output/. UNKNOWN không
    bao giờ được chốt thành effective — giữ regime cũ cho an toàn."""
    HYST_RUNS = 2
    st  = load_json(REGIME_STATE) or {}
    eff = st.get("effective_regime")

    if eff is None:                                   # bootstrap lần đầu
        eff0 = raw if raw != "UNKNOWN" else "UNKNOWN"
        save_json(REGIME_STATE, {"effective_regime": eff0,
                                 "candidate": None, "candidate_count": 0})
        return eff0, "bootstrap"

    if raw == "UNKNOWN":                               # không rõ regime -> giữ cũ
        return eff, f"raw=UNKNOWN -> giu {eff}"

    if raw == eff:                                     # xác nhận lại -> huỷ candidate
        if st.get("candidate"):
            st["candidate"] = None
            st["candidate_count"] = 0
            save_json(REGIME_STATE, st)
        return eff, "stable"

    # raw != eff: đếm số RUN LIÊN TIẾP candidate đã giữ
    if st.get("candidate") == raw:
        cnt = int(st.get("candidate_count") or 1) + 1
        if cnt >= HYST_RUNS:                          # đủ run -> chuyển gate
            save_json(REGIME_STATE, {"effective_regime": raw,
                                     "candidate": None, "candidate_count": 0})
            return raw, f"CHUYEN -> {raw} (du {cnt} run)"
        st["candidate"] = raw
        st["candidate_count"] = cnt
        save_json(REGIME_STATE, st)
        return eff, f"pending {raw} {cnt}/{HYST_RUNS} run -> giu {eff}"

    # candidate mới
    st["candidate"] = raw
    st["candidate_count"] = 1
    save_json(REGIME_STATE, st)
    return eff, f"candidate moi {raw} 1/{HYST_RUNS} run -> giu {eff}"


# ══════════════════════════════════════════════════════════════════════
# V4.5 — BREADTH của rổ (để phân loại regime breadth-aware)
# ══════════════════════════════════════════════════════════════════════
MIN_BREADTH_N = 30   # dưới ngưỡng này → không tin breadth, giữ index-regime


def _compute_breadth(rows: list) -> dict:
    """% mã trên EMA50/EMA200 + median %chg 5d/20d của rổ. Fail-soft."""
    import statistics as _st
    n = a50 = a200 = 0
    r20, r5 = [], []
    for r in rows:
        p   = _f(r.get("price"))
        e50 = _f(r.get("ema50"))
        e200 = _f(r.get("ema200"))
        if p and e50:
            n += 1
            if p > e50: a50 += 1
            if e200 and p > e200: a200 += 1
        rr = _f(r.get("return_20d"))
        if rr is not None:
            r20.append(rr)
        o = r.get("_ohlcv_5d")
        if isinstance(o, list) and len(o) >= 2:
            try:
                cn = o[-1].get("close") if isinstance(o[-1], dict) else o[-1][4]
                c0 = o[0].get("close")  if isinstance(o[0], dict)  else o[0][4]
                if c0:
                    r5.append((float(cn) / float(c0) - 1.0) * 100.0)
            except Exception:
                pass
    if n == 0:
        return {"n": 0}
    return {"n": n,
            "share_50":  a50 / n,
            "share_200": a200 / n,
            "med_c20":   _st.median(r20) if r20 else None,
            "med_c5":    _st.median(r5)  if r5  else None}


# ══════════════════════════════════════════════════════════════════════
# V4-EXTRA SIGNALS (v4.4) — CHỈ V4, KHÔNG đụng registry chung (V3 giữ baseline)
# 3 tín hiệu bổ sung, đặt vào factor HOST để thừa hưởng gate ĐÃ ĐO:
#   trend_st   → breakout    (thuận-đà: gate up/side BẬT, down TẮT — đúng bản chất)
#   depth_wall → flow        (vi cấu trúc, gate 1.0; TRADE-only — tường lệnh chỉ
#                             có nghĩa trong phiên)
#   cf_core    → fundamental (dòng tiền thực, gate 1.0, cả 2 khung)
# Cap host tự nới (+span). Weight TRADE chỉnh nhẹ (breakout 0.08→0.12) cho trend
# có tiếng nói khung ngắn; HOLD giữ nguyên. Tổng weight vẫn = 1.0.
# ══════════════════════════════════════════════════════════════════════

def _f(x):
    try:
        return float(x) if x is not None else None
    except (TypeError, ValueError):
        return None


def sc_trend_st(row):
    """Trend-following = Supertrend (hướng) × ADX (độ mạnh). MỘT đại diện sạch —
    KHÔNG add cả cụm ema/macd/roc (cộng-tuyến r=0.87-0.94). span ±4."""
    p, st, adx = _f(row.get("price")), _f(row.get("supertrend")), _f(row.get("adx"))
    if not p or not st:
        return 0
    up = p > st
    s = 2 if up else -2
    if adx is not None:
        if   adx >= 25: s = 4 if up else -4    # trend rõ → full
        elif adx <  18: s = 1 if up else -1    # phẳng → dè dặt
    return max(-4, min(4, s))


# Ngưỡng band tường/avg-trade — bám phân bố thật toàn sàn (p50≈41, p75≈107,
# p90≈227). Sửa DUY NHẤT dòng này để tinh chỉnh band về sau.
# LƯU Ý: đổi band = scoring math thay đổi → PHẢI bump SCORING_VERSION (reset
# bucket forward-validation). Hằng số chỉ giúp sửa gọn, không miễn bump.
_DEPTH_BANDS = (40, 100, 250)   # (ngưỡng band1, band2, band3)


def _wall_band(ratio):
    b1, b2, b3 = _DEPTH_BANDS
    if   ratio >= b3: return 3
    elif ratio >= b2: return 2
    elif ratio >= b1: return 1
    return 0


def sc_depth_wall(row):
    """Tường bid/ask so với KL TB mỗi lệnh khớp (_of_avg_size): đỡ dưới dày → +,
    chặn trên dày → −. Chuẩn hoá theo avg trade → tự thích ứng từng mã. Chỉ xét
    mức giá trong ±2% quanh giá hiện tại. span ±3, TRADE-only.
    (bid_price/ask_price đơn vị VND → chia 1000 để so với price nghìn-đồng.)"""
    avg = _f(row.get("_of_avg_size"))
    p   = _f(row.get("price"))
    if not avg or avg <= 0 or not p:
        return 0
    lo, hi = p * 0.98, p * 1.02
    bid_w = ask_w = 0.0
    for i in (1, 2, 3):
        bp, bv = _f(row.get(f"bid_price_{i}")), _f(row.get(f"bid_vol_{i}"))
        if bp and bv and lo <= bp / 1000 <= hi:
            bid_w = max(bid_w, bv)
        ap, av = _f(row.get(f"ask_price_{i}")), _f(row.get(f"ask_vol_{i}"))
        if ap and av and lo <= ap / 1000 <= hi:
            ask_w = max(ask_w, av)
    s = _wall_band(bid_w / avg) - _wall_band(ask_w / avg)
    return max(-3, min(3, s))


def sc_cf_core(row):
    """Dòng tiền HĐKD (cf_score v2.3, sector-aware, max ±10) renorm ±3. Bổ khuyết
    cho PE/PB/ROE — tiền thực vs lợi nhuận kế toán."""
    cf = _f(row.get("cf_score"))
    if cf is None:
        return 0
    cf = max(-10.0, min(10.0, cf))
    return int(round(cf / 10.0 * 3))


# (sid, factor, fn, span, horizons) — KHÔNG vào SIGNALS chung
V4_EXTRA = [
    ("trend_st",   "breakout",    "sc_trend_st",   4, ("trade", "hold")),
    ("depth_wall", "flow",        "sc_depth_wall", 3, ("trade",)),
    ("cf_core",    "fundamental", "sc_cf_core",    3, ("trade", "hold")),
]
_V4_FN = {"sc_trend_st": sc_trend_st, "sc_depth_wall": sc_depth_wall,
          "sc_cf_core": sc_cf_core}
_V4_LABEL = {"trend_st": "📈 Trend(ST)", "depth_wall": "🧱 Tường bid/ask",
             "cf_core": "💵 Dòng tiền"}

# Weight TRADE V4-only. HOLD = registry.
# ── v4.8 ──────────────────────────────────────────────────────────────────
#   MR BẬT LẠI (quyết định vận hành 2026-08-16): weight 0.27 (tỷ trọng gốc v4.6)
#   + GATE mean_reversion=1.0 mọi regime → MR đóng góp vào score_trade thật để
#   kiểm thủ công. Factor sống co pro-rata giữ tổng=1. context vẫn = 0 (Ư1).
#   ⚠ Đi ngược forward IC −0.167 đã ghi trong file → giữ 1 shadow ĐỐI CHỨNG
#     "MR-off" (score_trade_nomr) để forward so, quyết giữ/tắt sau ≥30 phiên.
_W_TRADE_V4 = {"mean_reversion": 0.27,   "breakout": 0.1307, "flow": 0.2724,
               "fundamental":    0.2179, "growth":   0.1090, "context": 0.0}
assert abs(sum(_W_TRADE_V4.values()) - 1.0) < 1e-9


def _weight(hz, f):
    return _W_TRADE_V4[f] if hz == "trade" else FACTOR_WEIGHTS[hz][f]


def _augment_caps(caps):
    """Nới cap host factor theo span V4-extra (để norm không bão hoà quá sớm)."""
    for _sid, factor, _fn, span, horizons in V4_EXTRA:
        for hz in horizons:
            caps[hz][factor] = caps[hz].get(factor, 0) + span
    return caps


# ══════════════════════════════════════════════════════════════════════
# CORE — chấm 1 symbol, 2 khung, CÓ gate theo regime
# ══════════════════════════════════════════════════════════════════════

# ── CONFIDENCE ĐỘC LẬP (v4.6c) — đo ĐỘ TIN của kết luận, KHÔNG dính độ mạnh alpha ──
#    Trả (pct 0-100, nhãn). Hai trụ, cả hai độc lập với hướng/độ lớn score_trade:
#      1) ĐỘ PHỦ DATA : data_missing (core/phụ), regime mù/phân kỳ, data cũ, lực khớp mỏng
#      2) ĐỘ NHẤT QUÁN: các factor-norm cùng hướng hay giằng co (|Σ|/Σ|·|) — KHÔNG dùng
#                       dấu/độ lớn của TỔNG điểm → không phải alpha nói lại lần hai.
#    Thay công thức cũ (aligned & |total|) vốn chỉ phản chiếu độ mạnh alpha.
CONF_HI, CONF_MD          = 80, 60   # ngưỡng nhãn — chọn từ phân bố rổ VN100+HNX30
CONF_DISAGREE_MIN_GROSS   = 0.45     # dưới mức này = quá ít tín hiệu (đã tính sau gate) → không phạt
CONF_DISAGREE_MAXPEN      = 35       # trừ tối đa khi các nhóm triệt tiêu nhau hoàn toàn

def confidence_data_v4(row: dict) -> tuple:
    s = 100.0
    # 1) độ phủ data -----------------------------------------------------------
    for m in (row.get("data_missing") or []):
        if "Giá" in m and "(" not in m:  s -= 40     # mất giá gốc → gần vô giá trị
        elif "(" in m:                   s -= 5      # phụ: fallback / cache / 52T-3M
        else:                            s -= 18     # core: EMA/RSI/MACD/PE/EPS/FF5d/OHLCV5d/LựcKhớp
    if row.get("_regime") == "UNKNOWN":  s -= 25     # thị trường không đọc được
    if row.get("_regime_divergence"):    s -= 6      # index↔breadth phân kỳ (trừ NHẸ)
    st = row.get("_ta_stale_days") or 0
    if st > 0:                           s -= min(4 * st, 12)          # data cũ
    if row.get("_of_distribution") == "INSUFFICIENT_DATA": s -= 5     # lực khớp mỏng
    # 2) độ nhất quán giữa các nhóm CÒN SỐNG (nhân gate theo regime — khớp cách
    #    confluence tính; factor đã tắt/nửa liều KHÔNG bị tính cãi nhau oan) ---------
    gates = row.get("_gates") or {}
    # context bị loại khỏi trụ nhất quán: nó là HẰNG SỐ cross-sectional (-1.0 mọi mã)
    # và weight trade đã = 0 → không được tính là "cãi nhau" làm tụt Conf oan.
    norms = [(gates.get(f, 1) or 0) * (row.get(f"trade_{f}_norm") or 0)
             for f in FACTORS if f != "context"]
    gross = sum(abs(x) for x in norms)
    if gross >= CONF_DISAGREE_MIN_GROSS:
        agree = abs(sum(norms)) / gross              # 1=đồng thuận, 0=triệt tiêu
        s -= (1 - agree) * CONF_DISAGREE_MAXPEN
    pct = int(max(0.0, min(100.0, round(s))))
    label = "HIGH" if pct >= CONF_HI else "MEDIUM" if pct >= CONF_MD else "LOW"
    return pct, label


def score_symbol_v4(row: dict, ctx: dict, caps: dict, actives: dict,
                    regime: str, regime_raw: str = None,
                    regime_v42: str = "UNKNOWN",
                    regime_divergence: bool = False) -> dict:
    # passthrough data thô (bỏ field scoring của v2.3) — giống V3
    out = {k: v for k, v in row.items() if not _is_v23_scoring_field(k)}
    out.update({
        "scoring_version":  SCORING_VERSION,
        "registry_version": REGISTRY_VERSION,
        "gate_version":     GATE_VERSION,
        "_regime":          regime,                    # regime HIỆU LỰC (sau hysteresis)
        "_regime_raw":      regime_raw or regime,       # regime THÔ (trước hysteresis)
        "_regime_divergence": regime_divergence,        # V4.6 FIX: set TRƯỚC khi tính confidence
    })

    sig_labels = []
    sig_scores = {}
    for sid, factor, fn, span, horizons, status, source, _, _ in SIGNALS:
        if status != "active":
            continue
        try:
            s, label = FN_TABLE[fn](row, ctx)
        except Exception as e:
            log.warning(f"  {row.get('symbol')}: signal {sid} lỗi — {e}")
            s, label = 0, ""
        if abs(s) > span:                    # ép đối xứng (giống V3)
            s = max(-span, min(span, s))
        sig_scores[sid] = s
        out[f"s_{sid}"] = s
        if label:
            sig_labels.append(label)

    # ── V4-EXTRA (v4.4): tín hiệu chỉ-V4, tính 1 lần, tiêm vào factor host ──
    for xsid, _xfac, xfn, xspan, _xhz in V4_EXTRA:
        try:
            xs = _V4_FN[xfn](row)
        except Exception as e:
            log.warning(f"  {row.get('symbol')}: V4-extra {xsid} lỗi — {e}")
            xs = 0
        xs = max(-xspan, min(xspan, xs))
        sig_scores[xsid] = xs
        out[f"s_{xsid}"] = xs
        if xs:
            sig_labels.append(f"{_V4_LABEL.get(xsid, xsid)} {xs:+d}")

    # gate theo regime cho từng factor (cùng regime cho mọi factor trong run)
    gates = {f: gate_for(f, regime) for f in FACTORS}
    out["_gates"] = dict(gates)

    for hz in ("trade", "hold"):
        f_raw = {f: 0 for f in FACTORS}
        for sid, factor, fn, span, horizons, status, source, _, _ in actives[hz]:
            f_raw[factor] += sig_scores.get(sid, 0)
        for xsid, xfac, _xfn, _xspan, xhz in V4_EXTRA:   # V4-extra vào host factor
            if hz in xhz:
                f_raw[xfac] += sig_scores.get(xsid, 0)

        f_norm, weighted = {}, 0.0
        for f in FACTORS:
            cap = caps[hz][f]
            n = max(-1.0, min(1.0, f_raw[f] / cap)) if cap > 0 else 0.0
            f_norm[f] = n
            # CÁCH B: gate × weight × norm, KHÔNG renorm mẫu số → điểm co lại
            weighted += _weight(hz, f) * gates[f] * n
            out[f"{hz}_{f}_raw"]  = f_raw[f]
            out[f"{hz}_{f}_norm"] = round(n, 4)
        pre_total = weighted * 100

        if hz == "trade":
            sgn = 1 if pre_total >= 0 else -1
            aligned = 0
            for name, fs in SUPERGROUPS.items():
                # confluence dùng weight ĐÃ gate → không đếm factor đã tắt
                wsum = sum(_weight(hz, f) * gates[f] for f in fs)
                sn = (sum(_weight(hz, f) * gates[f] * f_norm[f]
                          for f in fs) / wsum) if wsum else 0
                if sn * sgn >= CONFLUENCE_MIN_NORM:
                    aligned += 1
            # ── W_reg = Σ(weight × gate) khung trade = tổng trọng số CÒN SỐNG.
            #    Tính SỚM (trước extras) vì v4.7 dùng nó để co cả extras lẫn ngưỡng.
            w_reg = sum(_weight("trade", f) * gates[f] for f in FACTORS)
            w_reg = w_reg if w_reg > 1e-9 else 1.0      # phòng chia 0
            out["_w_regime"] = round(w_reg, 4)

            bonus = CONFLUENCE_BONUS * sgn if aligned >= 2 else 0
            # ── FF-intraday "NN gom mạnh" (V4 ONLY, cap ±3) — snapshot gắn (±3/0). ──
            ffi_pts = row.get("ff_intra_flag_pts") or 0
            # ── OF buy-pressure (buy_ratio SỐ LỆNH + cổng KL/tần suất), cap ±4. ──
            #    INDICATIVE (fit 1 cung macro). KL & tần suất chỉ làm CỔNG.
            bp_pts = buy_pressure_pts(row.get("_of_buy_count"), row.get("_of_sell_count"),
                                      row.get("_of_total_trades"), row.get("vol_ma_ratio"))
            # ── v4.7 (Ư3): extras CO THEO w_reg ────────────────────────────────
            #    Trước: extras cộng TUYỆT ĐỐI → trong regime mỏng (w_reg nhỏ) một
            #    cờ ±4 "đấm" mạnh bất thường so với trần điểm đã co, tự đẩy mã qua
            #    ngưỡng BUY. Nay nhân w_reg → "1 điểm thưởng = mức nghiêng bullish
            #    cố định" ở MỌI regime, khớp đúng cách ngưỡng cũng ×w_reg.
            extras = (bonus + ffi_pts + bp_pts) * w_reg
            total = max(-100.0, min(100.0, pre_total + extras))
            if ffi_pts:
                sig_labels.append(f"🌐 NN gom mạnh {ffi_pts:+d}")
            if bp_pts:
                sig_labels.append(f"💧 Áp lực mua khớp {bp_pts:+d}")
            out["ff_intra_flag_pts"]     = ffi_pts
            out["of_bp_pts"]             = bp_pts
            out["confluence_bonus"]      = bonus
            out["n_supergroups_aligned"] = aligned
            out["score_trade"]           = round(total, 2)
            out["total_score"]           = out["score_trade"]   # recorder compat
            # ── ngưỡng decision CO THEO REGIME (Option A) — score_trade thô GIỮ NGUYÊN,
            #    chỉ dời cột mốc quyết định theo w_reg. (v4.7: extras đã co cùng nhịp.)
            for cut, name in THRESHOLDS:
                cut_s = None if cut is None else cut * w_reg
                if cut_s is None or total >= cut_s:
                    out["decision"] = name
                    break
            # ── v4.7 EXTRAS-GUARD (chỉ CHIỀU MUA) ──────────────────────────────
            #    extras (confluence/ffi/of_bp) là "gia vị", KHÔNG được tự tạo lệnh
            #    BUY. Muốn BUY: điểm LÕI (pre_total, chưa cộng extras) phải TỰ đạt
            #    ngưỡng (K=1.0); extras chỉ được NÂNG HẠNG (BUY→SB). Sinh ra sau khi
            #    thấy DEEP_DOWN có ~34 mã BUY chỉ nhờ extras (of_bp mới INDICATIVE).
            #    K=1.0 chặn đúng 50 mã extras-only toàn ledger (sim). KHÔNG đụng bán.
            EXTRAS_GUARD_K = 1.0
            if out["decision"] == "STRONG BUY" and pre_total < EXTRAS_GUARD_K * 50 * w_reg:
                out["decision"] = "BUY"
                out["_extras_guard"] = "SB→BUY"
            if out["decision"] == "BUY" and pre_total < EXTRAS_GUARD_K * 25 * w_reg:
                out["decision"] = "NEUTRAL"
                out["_extras_guard"] = "BUY→NEUTRAL"
            # ── CONFIDENCE ĐỘC LẬP (Cách 1 — ghi đè công thức cũ aligned&|total|) ──
            #    Tính SAU khi score_trade/decision đã chốt → KHÔNG đổi điểm/quyết định,
            #    KHÔNG cần bump SCORING_VERSION, KHÔNG reset ledger. Xem confidence_data_v4().
            cpct, clabel = confidence_data_v4(out)
            out["confidence_pct"]    = cpct
            out["confidence"]        = clabel
            out["confidence_method"] = "data+consistency_v4.6c"
            # ── Ư5 SHADOW (v4.7) — fundamental SO-TRONG-NGÀNH (rank_fund_grp) ──
            #    Tính điểm fundamental THAY THẾ dùng rank_fund_grp (percentile 0..1
            #    trong ngành) thay cho fund_core (PE tuyệt đối), GIỮ nguyên cf_core.
            #    KHÔNG đổi score_trade/decision production — chỉ ghi field shadow để
            #    forward-validate (join ledger, so IC vs bản production). Chuyển thật
            #    CHỈ khi shadow thắng đủ dày (≥30 phiên) — kỷ luật forward-thắng.
            rk = _f(row.get("rank_fund_grp"))
            if rk is not None:
                alt_pts  = max(-8, min(8, round((rk - 0.5) * 16)))   # 0..1 → ±8 (span fund_core)
                cap_fund = caps["trade"].get("fundamental", 11) or 11
                alt_raw  = alt_pts + sig_scores.get("cf_core", 0)     # thay fund_core, GIỮ cf_core
                norm_alt = max(-1.0, min(1.0, alt_raw / cap_fund))
                delta    = (_weight("trade", "fundamental") * gates["fundamental"]
                            * (norm_alt - f_norm["fundamental"]) * 100)
                pre_alt  = pre_total + delta                          # lõi shadow (chưa extras) — cho guard
                sa = max(-100.0, min(100.0, pre_alt + extras))
                out["_alt_fund_pts"]      = alt_pts
                out["score_trade_altfund"] = round(sa, 2)
                out["_altfund_delta"]      = round(sa - out["score_trade"], 2)
                dec_alt = "STRONG SELL"
                for cut, name in THRESHOLDS:
                    if cut is None or sa >= cut * w_reg:
                        dec_alt = name
                        break
                # v4.10 PARITY: mirror extras-guard (như production/gate1). Trước đây
                #   altfund KHÔNG có guard → decision_altfund lệch production vì lý do
                #   không liên quan fundamental (extras-only BUY) → so-quyết-định bẩn.
                #   Nay dùng CHUNG guard trên pre_alt → chỉ còn khác biệt do fundamental.
                if dec_alt == "STRONG BUY" and pre_alt < EXTRAS_GUARD_K * 50 * w_reg:
                    dec_alt = "BUY"
                if dec_alt == "BUY" and pre_alt < EXTRAS_GUARD_K * 25 * w_reg:
                    dec_alt = "NEUTRAL"
                out["decision_altfund"] = dec_alt
            else:
                out["_alt_fund_pts"]       = None
                out["score_trade_altfund"] = None
                out["decision_altfund"]    = None
                out["_altfund_delta"]      = None
            # ── SHADOW ĐỐI CHỨNG MR-OFF (v4.8) — production giờ BẬT MR, shadow này
            #    TẮT MR (gate=0) để forward so: production(MR-on) vs control(MR-off).
            #    Dùng bộ weight KHÔNG-MR (0.33 chia sang factor sống), MR gate 0.
            _WNOMR = {"mean_reversion": 0.0,    "breakout": 0.1791, "flow": 0.3731,
                      "fundamental":    0.2985, "growth":   0.1493, "context": 0.0}
            g_off = dict(gates); g_off["mean_reversion"] = 0.0
            pre_off = sum(_WNOMR[f] * g_off[f] * f_norm[f] for f in FACTORS) * 100
            w_off   = sum(_WNOMR[f] * g_off[f] for f in FACTORS) or 1.0
            ex_off  = (bonus + ffi_pts + bp_pts) * w_off
            sa_off  = max(-100.0, min(100.0, pre_off + ex_off))
            out["score_trade_nomr"] = round(sa_off, 2)
            out["_nomr_delta"]      = round(sa_off - out["score_trade"], 2)
            dec_off = "STRONG SELL"
            for cut, name in THRESHOLDS:
                if cut is None or sa_off >= cut * w_off:
                    dec_off = name
                    break
            # v4.10 PARITY: mirror extras-guard trên lõi nomr (pre_off, chưa extras).
            if dec_off == "STRONG BUY" and pre_off < EXTRAS_GUARD_K * 50 * w_off:
                dec_off = "BUY"
            if dec_off == "BUY" and pre_off < EXTRAS_GUARD_K * 25 * w_off:
                dec_off = "NEUTRAL"
            out["decision_nomr"] = dec_off
            # ── SHADOW RANK CROSS-SECTIONAL (v4.10) — CHẤM slow-factor theo HẠNG
            #    TRONG NGÀNH (rank_*_grp) thay vì ngưỡng TUYỆT ĐỐI. Đổi 2 factor chậm:
            #      fundamental → rank_fund_grp (lõi = altfund, GIỮ cf_core)
            #      growth      → rank_growth_grp
            #    MR / breakout / flow / context GIỮ NGUYÊN như production (chỉ swap
            #    NORM của fund+growth, KHÔNG đụng gate). Mục đích: kiểm giả thuyết
            #    khung-chuẩn — chấm tương đối miễn nhiễm cú DỊCH MẶT BẰNG CHUNG (VD
            #    refresh Q2 làm fund_norm cả rổ +0.49 → BUY giả, chính là bệnh phải
            #    vá bằng gate6). Rank luôn ~nửa rổ trên trung vị → không tự đẻ BUY
            #    hàng loạt → về lý thuyết bỏ được gate tay fund/growth. KHÔNG đụng
            #    production; forward ≥30 phiên mới xử. Decomposition:
            #      _rank_delta                       = rank(fund+growth) vs production
            #      _rank_delta − _altfund_delta      ≈ phần GROWTH-rank đóng góp riêng
            rkf = _f(row.get("rank_fund_grp"))
            rkg = _f(row.get("rank_growth_grp"))
            d_fund = d_grow = 0.0
            if rkf is not None:
                _capf   = caps["trade"].get("fundamental", 11) or 11
                _rawf   = max(-8, min(8, round((rkf - 0.5) * 16))) + sig_scores.get("cf_core", 0)
                _nf     = max(-1.0, min(1.0, _rawf / _capf))
                d_fund  = (_weight("trade", "fundamental") * gates["fundamental"]
                           * (_nf - f_norm["fundamental"]) * 100)
            if rkg is not None:
                _ng     = max(-1.0, min(1.0, (rkg - 0.5) * 2))       # rank 0..1 → norm ±1
                d_grow  = (_weight("trade", "growth") * gates["growth"]
                           * (_ng - f_norm["growth"]) * 100)
            pre_rk = pre_total + d_fund + d_grow                     # lõi rank (chưa extras)
            sa_rk  = max(-100.0, min(100.0, pre_rk + extras))
            out["score_trade_rank"] = round(sa_rk, 2)
            out["_rank_delta"]      = round(sa_rk - out["score_trade"], 2)
            dec_rk = "STRONG SELL"
            for cut, name in THRESHOLDS:                              # w_reg: gate GIỮ như production
                if cut is None or sa_rk >= cut * w_reg:
                    dec_rk = name
                    break
            if dec_rk == "STRONG BUY" and pre_rk < EXTRAS_GUARD_K * 50 * w_reg:
                dec_rk = "BUY"
            if dec_rk == "BUY" and pre_rk < EXTRAS_GUARD_K * 25 * w_reg:
                dec_rk = "NEUTRAL"
            out["decision_rank"] = dec_rk
            # ── SHADOW NGƯỢC GATE-1 (v4.9) — dựng lại HÀNH VI CŨ: fundamental &
            #    growth gate=1.0 mọi regime (như trước v4.9). Production giờ GATE
            #    chúng ở DOWN/DEEP → shadow này để forward so gated (production) vs
            #    control (gate=1.0). Chỉ khác production đúng ở 2 gate đó; trong
            #    UP/SIDE hai bản TRÙNG nhau (_gate1_delta≈0). Mirror đủ ngưỡng ×w
            #    và extras-guard để tái tạo ĐÚNG quyết định cũ.
            g_one = dict(gates)
            g_one["fundamental"] = 1.0
            g_one["growth"]      = 1.0
            w_g1   = sum(_weight("trade", f) * g_one[f] for f in FACTORS) or 1.0
            pre_g1 = sum(_weight("trade", f) * g_one[f] * f_norm[f] for f in FACTORS) * 100
            ex_g1  = (bonus + ffi_pts + bp_pts) * w_g1
            sa_g1  = max(-100.0, min(100.0, pre_g1 + ex_g1))
            out["score_trade_gate1"] = round(sa_g1, 2)
            out["_gate1_delta"]      = round(sa_g1 - out["score_trade"], 2)  # chênh do gate fund/growth
            dec_g1 = "STRONG SELL"
            for cut, name in THRESHOLDS:
                if cut is None or sa_g1 >= cut * w_g1:
                    dec_g1 = name
                    break
            if dec_g1 == "STRONG BUY" and pre_g1 < EXTRAS_GUARD_K * 50 * w_g1:
                dec_g1 = "BUY"
            if dec_g1 == "BUY" and pre_g1 < EXTRAS_GUARD_K * 25 * w_g1:
                dec_g1 = "NEUTRAL"
            out["decision_gate1"] = dec_g1
        else:
            out["score_hold"] = round(max(-100.0, min(100.0, pre_total)), 2)

    # ── LỚP CỜ RECOVERY (v4.2) — chạy SAU khi decision/điểm đã chốt ──
    #    KHÔNG đổi score_trade/score_hold/decision. Chỉ:
    #      • dán cờ recovery_warn + thông điệp
    #      • hạ confidence: cap ở MEDIUM (BUY trong RECOVERY không bao giờ HIGH)
    #    → "update của v4": thấy điểm ngoặt nhưng chỉ cảnh báo, chưa đổi điểm.
    out["regime_v42"]    = regime_v42
    out["recovery_warn"] = False
    out["warn_msg"]      = ""
    if regime_v42 == "RECOVERY" and out.get("decision") in ("BUY", "STRONG BUY"):
        out["recovery_warn"] = True
        out["warn_msg"]      = "sóng hồi chưa xác nhận đảo chiều"
        if out.get("confidence") == "HIGH":
            out["confidence"]     = "MEDIUM"
            out["confidence_pct"] = min(out.get("confidence_pct", CONF_HI), CONF_HI - 1)

    out["signals"] = " | ".join(sig_labels)
    return out


# ══════════════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════════════

def run():
    log.info("=== SCORING V4 (RCEG SHADOW#2, registry v%s, gate v%s) START ===",
             REGISTRY_VERSION, GATE_VERSION)
    validate_registry()
    caps    = {hz: factor_caps(hz) for hz in ("trade", "hold")}
    actives = {hz: active_signals(hz) for hz in ("trade", "hold")}
    caps = _augment_caps(caps)   # V4.4: nới cap host factor cho 3 tín hiệu mới

    rows = load_json(SIGNALS_IN)
    if not rows:
        log.warning(f"{SIGNALS_IN} rỗng/không tồn tại — skip (shadow fail-soft)")
        return

    raw_ctx = load_json(CONTEXT_FILE)
    if isinstance(raw_ctx, dict):
        ctx = dict(raw_ctx)
    elif isinstance(raw_ctx, list) and raw_ctx and isinstance(raw_ctx[0], dict):
        ctx = dict(raw_ctx[0])
    else:
        ctx = {}
    if rows and isinstance(rows[0], dict) and rows[0].get("snap_time"):
        ctx["_snap_time"] = rows[0]["snap_time"]

    # regime là thuộc tính THỊ TRƯỜNG → resolve MỘT LẦN cho cả run
    # regime index: ƯU TIÊN market_regime_live (Op1 live mỗi run, ghi bởi
    # snapshot vào vnindex_live.json) → thay market_regime đóng băng 1 lần/ngày.
    # Fallback về _resolve_regime(ctx) nếu chưa có live (bootstrap / lỗi fetch).
    _vlive = load_json("vnindex_live.json") or {}
    _lreg  = str(_vlive.get("market_regime_live") or "").upper()
    index_raw  = _lreg if _lreg in _VALID_REGIMES else _resolve_regime(ctx, rows[0] if rows else {})
    run_date   = _run_date(ctx, rows)
    # ── V4.5: regime BREADTH-AWARE (chống méo index cap-weighted) ──
    _brd = _compute_breadth(rows)
    if _brd.get("n", 0) >= MIN_BREADTH_N:
        breadth_raw = classify_regime_breadth(
            _brd["share_50"], _brd["share_200"],
            _brd["med_c5"], _brd["med_c20"])["regime_raw"]
    else:
        breadth_raw = "UNKNOWN"
    raw_regime = more_bearish(index_raw, breadth_raw)   # lấy bên BI QUAN hơn
    regime, hyst_status = _apply_hysteresis(raw_regime, run_date)   # regime hiệu lực

    # regime v4.2 (RECOVERY-aware) — CHỈ dùng để DÁN CỜ CẢNH BÁO lên BUY,
    # KHÔNG đổi gate/điểm/decision. Detection do step3_context/step_context_refresh
    # ghi sẵn vào context.json (market_regime_v42). Đây là "update của v4":
    # v4 nhìn thấy điểm ngoặt của v4.2 nhưng chỉ cảnh báo, chưa cho đổi điểm.
    regime_v42 = (ctx.get("market_regime_v42")
                  or ctx.get("market_regime") or "UNKNOWN")

    gates = {f: gate_for(f, regime) for f in FACTORS}
    off   = [f for f in FACTORS if gates[f] == 0.0]
    half  = [f for f in FACTORS if 0.0 < gates[f] < 1.0]
    log.info(f"[V4] regime thô={raw_regime} → hiệu lực={regime} "
             f"(hysteresis: {hyst_status}) | date={run_date}")
    log.info(f"[V4] gates={gates}")
    if regime_v42 == "RECOVERY":
        log.info("[V4] regime_v42=RECOVERY → dán cờ cảnh báo lên BUY "
                 "(KHÔNG đổi điểm/decision)")
    if off:
        log.info(f"[V4] factor TẮT: {off} (Cách B → điểm co lại)")
    if half:
        log.info(f"[V4] factor NỬA LIỀU: " +
                 ", ".join(f"{f}={gates[f]}" for f in half))

    # V4.6 FIX: divergence phải tính TRƯỚC vòng chấm để confidence_data_v4 dùng được.
    #           (Trước đây gán sau vòng lặp → tại lúc tính confidence field chưa tồn
    #            tại → nhánh "if row.get('_regime_divergence'): s -= 6" không bao giờ
    #            chạy. Nay tính sớm + truyền vào score_symbol_v4.)
    _div = breadth_raw not in (index_raw, "UNKNOWN")

    out_rows, n_err = [], 0
    for row in rows:
        try:
            out_rows.append(score_symbol_v4(row, ctx, caps, actives,
                                            regime, raw_regime, regime_v42,
                                            regime_divergence=_div))
        except Exception:
            n_err += 1
            log.warning(f"  skip {row.get('symbol')}:\n{traceback.format_exc()}")

    # V4.5: gắn thông tin breadth-regime (market-wide) lên mọi row.
    # (_div đã tính TRƯỚC vòng lặp & truyền vào score_symbol_v4 để confidence dùng
    #  được; _regime_divergence đã set trong score_symbol_v4 — KHÔNG set lại ở đây.)
    for _r in out_rows:
        _r["_regime_index"]      = index_raw
        _r["_regime_breadth"]    = breadth_raw
        _r["_regime_blended"]    = raw_regime
        _r["_breadth_pct_50"]    = round(_brd["share_50"] * 100, 1) if _brd.get("n") else None
        _r["_breadth_pct_200"]   = round(_brd["share_200"] * 100, 1) if _brd.get("n") else None
    log.info(f"[V4.5] regime index={index_raw} | breadth={breadth_raw}"
             f" (>EMA50 {_brd.get('share_50', 0)*100:.0f}%, med20d="
             f"{_brd.get('med_c20')}) → blended={raw_regime}"
             + ("  ⚠ PHÂN KỲ" if _div else ""))

    save_json(SIGNALS_OUT, out_rows)

    dec = Counter(r.get("decision") for r in out_rows)
    log.info(f"Đã chấm {len(out_rows)}/{len(rows)} mã (lỗi {n_err}) → {SIGNALS_OUT}")
    log.info(f"Decisions (trade, regime hiệu lực={regime}): {dict(dec)}")
    if out_rows:
        top_h = sorted(out_rows, key=lambda r: r.get("score_hold") or -999,
                       reverse=True)[:5]
        log.info("Top-5 score_hold: " + ", ".join(
            f"{r['symbol']}={r.get('score_hold')}" for r in top_h))

    # Báo cáo dry-run IN THẲNG LOG (debug.yml không commit output/) — bọc
    # try để không bao giờ chặn run chính.
    try:
        _log_compare_and_whatif(out_rows, ctx, caps, actives, regime)
    except Exception:
        log.warning("dry-run report lỗi (bỏ qua):\n" + traceback.format_exc())

    log.info("=== SCORING V4 (RCEG SHADOW#2) DONE ===")


# ══════════════════════════════════════════════════════════════════════
# DRY-RUN REPORT — in vào log để đối chiếu (không cần file / không sửa yaml)
# ══════════════════════════════════════════════════════════════════════

_MR_SIG_KEYS = ("s_willr_mr", "s_bb_mr", "s_overext_ema", "s_rs_reversal")


def _mr_contrib(row: dict) -> int:
    return sum(int(row.get(k) or 0) for k in _MR_SIG_KEYS)


def _log_compare_and_whatif(out_rows, ctx, caps, actives, regime):
    by_sym = {r.get("symbol"): r for r in out_rows}

    # (1) V4 vs V3 — nếu v2f_signals_v3.json có sẵn (do intraday commit)
    v3 = load_json("v2f_signals_v3.json")
    if v3:
        v3map = {r.get("symbol"): r for r in v3}
        diffs = []
        for sym, r4 in by_sym.items():
            r3 = v3map.get(sym)
            if not r3:
                continue
            s3 = r3.get("score_trade")
            s4 = r4.get("score_trade")
            if s3 is None or s4 is None:
                continue
            diffs.append((sym, s3, s4, s4 - s3,
                          r3.get("decision"), r4.get("decision")))
        n_changed_dec = sum(1 for d in diffs if d[4] != d[5])
        log.info(f"\n{'─'*76}\n  V4 vs V3 (regime={regime}) — {len(diffs)} mã khớp, "
                 f"{n_changed_dec} mã ĐỔI decision")
        log.info(f"{'sym':<8}{'V3':>8}{'V4':>8}{'Δ':>8}  {'dec V3 → V4'}")
        log.info("─" * 76)
        for sym, s3, s4, d, d3, d4 in sorted(
                diffs, key=lambda x: abs(x[3]), reverse=True)[:12]:
            mark = "  ← đổi" if d3 != d4 else ""
            log.info(f"{sym:<8}{s3:>+8.2f}{s4:>+8.2f}{d:>+8.2f}  "
                     f"{str(d3):<11}→ {d4}{mark}")
        if regime in ("DOWNTREND", "DEEP_DOWN"):
            log.info("  (regime GIẢM: MR bật ở CẢ V3 lẫn V4; V4 khác V3 do TẮT "
                     "breakout — A1 đo breakout anti-predictive trong down (t≤-2), "
                     "nên V4 bỏ lực cản giảm giá sai này. Δ dương là ĐÚNG kỳ vọng.)")
        elif regime in ("UPTREND", "SIDEWAYS"):
            log.info("  (regime này: MR TẮT + breakout nửa liều → V4 khác V3 ở CẢ "
                     "MR lẫn breakout. Δ phản ánh 2 thay đổi cộng lại.)")
    else:
        log.info("  (chưa có v2f_signals_v3.json để so — bỏ qua phần V4 vs V3)")

    # (2) WHAT-IF: tính lại điểm dưới CẢ 4 regime cho ~8 mã có MR mạnh nhất
    #     → thấy trực tiếp gate làm điểm đổi bao nhiêu khi MR tắt/bật.
    picks = sorted(out_rows, key=lambda r: abs(_mr_contrib(r)),
                   reverse=True)[:8]
    rmap = {r.get("symbol"): r for r in load_json(SIGNALS_IN) or []}
    scan = ["UPTREND", "SIDEWAYS", "DOWNTREND", "DEEP_DOWN"]
    log.info(f"\n{'─'*76}\n  WHAT-IF score_trade theo regime (8 mã MR mạnh nhất)\n"
             f"  → cột UP/SIDE = MR TẮT ; DOWN/DEEP = MR BẬT\n{'─'*76}")
    log.info(f"{'sym':<8}{'MRcontrib':>10}" + "".join(f"{r[:8]:>11}" for r in scan))
    log.info("─" * 76)
    for r4 in picks:
        sym = r4.get("symbol")
        raw = rmap.get(sym)
        if not raw:
            continue
        cells = ""
        for rg in scan:
            sc = score_symbol_v4(raw, ctx, caps, actives, rg).get("score_trade")
            cells += f"{sc:>+11.2f}" if sc is not None else f"{'n/a':>11}"
        log.info(f"{sym:<8}{_mr_contrib(r4):>+10d}{cells}")
    log.info("  (chênh giữa UP và DOWN chính là phần MR đóng góp — bị gate cắt "
             "khi uptrend)")


if __name__ == "__main__":
    try:
        run()
    except Exception:
        log.error("V4 shadow crash (không chặn pipeline):\n"
                  + traceback.format_exc())
        sys.exit(0)      # fail-soft tuyệt đối
