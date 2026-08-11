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

SCORING_VERSION = "v4.4"          # +3 tín hiệu V4-only: trend_st(±4)+depth_wall(±3)+cf_core(±3), weight trade chỉnh nhẹ | trước: v4.3 OF buy-pressure
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


def _apply_hysteresis(raw: str, run_date: str):
    """Regime dùng để gate chỉ đổi khi regime THÔ giữ ≥HYST_SESSIONS phiên
    (đếm theo NGÀY, không theo lần chạy intraday). Chống whipsaw (A4: 50% run
    ≤2 phiên). Trả (effective_regime, status_str). State lưu ở output/.
    UNKNOWN không bao giờ được "chốt" thành effective — giữ regime cũ cho an toàn."""
    st = load_json(REGIME_STATE) or {}
    eff = st.get("effective_regime")

    if eff is None:                                   # bootstrap lần đầu
        eff0 = raw if raw != "UNKNOWN" else "UNKNOWN"
        save_json(REGIME_STATE, {"effective_regime": eff0,
                                 "candidate": None, "candidate_dates": []})
        return eff0, "bootstrap"

    if raw == "UNKNOWN":                               # không rõ regime → giữ cũ
        return eff, f"raw=UNKNOWN → giữ {eff}"

    if raw == eff:                                     # xác nhận lại → huỷ candidate
        if st.get("candidate"):
            st["candidate"] = None
            st["candidate_dates"] = []
            save_json(REGIME_STATE, st)
        return eff, "stable"

    # raw != eff: đếm số PHIÊN (ngày) candidate đã giữ
    if st.get("candidate") == raw:
        dates = sorted(set(st.get("candidate_dates", [])) | {run_date})
        if len(dates) >= HYST_SESSIONS:               # đủ phiên → chuyển gate
            save_json(REGIME_STATE, {"effective_regime": raw,
                                     "candidate": None, "candidate_dates": []})
            return raw, f"CHUYỂN → {raw} (đủ {len(dates)} phiên)"
        st["candidate_dates"] = dates
        save_json(REGIME_STATE, st)
        return eff, f"pending {raw} {len(dates)}/{HYST_SESSIONS} → giữ {eff}"

    # candidate mới
    st["candidate"] = raw
    st["candidate_dates"] = [run_date]
    save_json(REGIME_STATE, st)
    return eff, f"candidate mới {raw} 1/{HYST_SESSIONS} → giữ {eff}"


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

# Weight TRADE V4-only (breakout ↑ cho trend hiện diện; tổng = 1.0). HOLD = registry.
_W_TRADE_V4 = {"mean_reversion": 0.27, "breakout": 0.12, "flow": 0.25,
               "fundamental": 0.20, "growth": 0.10, "context": 0.06}
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

def score_symbol_v4(row: dict, ctx: dict, caps: dict, actives: dict,
                    regime: str, regime_raw: str = None,
                    regime_v42: str = "UNKNOWN") -> dict:
    # passthrough data thô (bỏ field scoring của v2.3) — giống V3
    out = {k: v for k, v in row.items() if not _is_v23_scoring_field(k)}
    out.update({
        "scoring_version":  SCORING_VERSION,
        "registry_version": REGISTRY_VERSION,
        "gate_version":     GATE_VERSION,
        "_regime":          regime,                    # regime HIỆU LỰC (sau hysteresis)
        "_regime_raw":      regime_raw or regime,       # regime THÔ (trước hysteresis)
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
            bonus = CONFLUENCE_BONUS * sgn if aligned >= 2 else 0
            total = max(-100.0, min(100.0, pre_total + bonus))
            # ── FF-intraday "NN gom mạnh" (V4 ONLY, PRE-REGISTER 8%/10 tỷ, cap ±3) ──
            #    Chỉ tác động TRADE (tín hiệu trong phiên, không dính HOLD).
            #    ff_intra_flag_pts do snapshot gắn (±3/0). Đọc từ row để chắc không bị
            #    lớp lọc field loại bỏ. V2.3/V3 KHÔNG cộng — chỉ V4.
            ffi_pts = row.get("ff_intra_flag_pts") or 0
            if ffi_pts:
                total = max(-100.0, min(100.0, total + ffi_pts))
                sig_labels.append(f"🌐 NN gom mạnh {ffi_pts:+d}")
            out["ff_intra_flag_pts"]     = ffi_pts
            # ── OF buy-pressure (khớp lệnh: buy_ratio SỐ LỆNH + cổng KL/tần suất) ──
            #    Cap nhỏ ±4, TRADE-only. PRE-REGISTER / INDICATIVE (fit 1 cung macro).
            #    Đọc _of_* từ row (V2.3 đã gắn). KL & tần suất chỉ làm CỔNG, không cộng.
            bp_pts = buy_pressure_pts(row.get("_of_buy_count"), row.get("_of_sell_count"),
                                      row.get("_of_total_trades"), row.get("vol_ma_ratio"))
            if bp_pts:
                total = max(-100.0, min(100.0, total + bp_pts))
                sig_labels.append(f"💧 Áp lực mua khớp {bp_pts:+d}")
            out["of_bp_pts"]             = bp_pts
            out["confluence_bonus"]      = bonus
            out["n_supergroups_aligned"] = aligned
            out["score_trade"]           = round(total, 2)
            out["total_score"]           = out["score_trade"]   # recorder compat
            for cut, name in THRESHOLDS:
                if cut is None or total >= cut:
                    out["decision"] = name
                    break
            out["confidence"] = ("HIGH" if aligned >= 2 and abs(total) >= 40
                                 else "MEDIUM" if abs(total) >= 25 else "LOW")
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
            out["confidence"] = "MEDIUM"

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
    raw_regime = _resolve_regime(ctx, rows[0] if rows else {})
    run_date   = _run_date(ctx, rows)
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

    out_rows, n_err = [], 0
    for row in rows:
        try:
            out_rows.append(score_symbol_v4(row, ctx, caps, actives,
                                            regime, raw_regime, regime_v42))
        except Exception:
            n_err += 1
            log.warning(f"  skip {row.get('symbol')}:\n{traceback.format_exc()}")

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
