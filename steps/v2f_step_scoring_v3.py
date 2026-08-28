"""
v2f_step_scoring_v3.py — Scoring engine v3 "Signal Registry" (SHADOW)
=======================================================================
Chạy trong v2f_cron_intraday.yml SAU v2f_step_scoring.py (v2.3).
KHÔNG thay thế v2.3 — hai bản chạy song song, so head-to-head qua ledger
riêng (xem DESIGN_V2F_SCORING_V3.md mục 6).

INPUT (zero API call — dùng lại data đã fetch trong run):
  output/v2f_signals.json  ← rows v2.3 = dict(deep_raw row) + điểm số
                              → chứa CẢ raw indicators (willr_14, bb_position,
                              price_vs_ema200_pct, high_52w, return_20d,
                              vol_ma_ratio, cmf, stoch_k, _of_vol_spike...)
                              LẪN điểm inherited (ff_score, ext_*, fundamental_score)
  output/context.json      ← vnindex_return_20d fallback cho RS

OUTPUT:
  output/v2f_signals_v3.json — mỗi row: score_trade + score_hold + decision
                               + factor norms 2 khung + per-signal scores

KIẾN TRÚC (khác v2.3 thế nào):
  1. Tín hiệu khai báo trong utils/v2f_registry.py — engine KHÔNG hard-code
  2. Cap tự tính từ registry → không bao giờ lệch max thật (hết lỗi thang ảo)
  3. Mọi hàm chấm bị ÉP đối xứng: |score| > span → clamp + warning (hết bias long)
  4. 6 factor trực giao thay 12 group chồng chéo
  5. Confluence ±5 đếm trên 3 siêu-nhóm độc lập, NẰM TRONG clamp ±100
  6. HAI bảng điểm: score_trade (1-5d, phát decision) + score_hold (~1 tháng,
     chỉ điểm + rank — tham khảo khi muốn giữ mã lâu)
  7. Order flow dùng vol_spike ĐÃ SỬA PHASE: chia lại theo expected-fraction
     curve đo thực tế từ log 04/07 (09:55≈18% volume ngày, 14:55≈100%)
  8. Tín hiệu gate:down (cmf, stoch) SKIP chờ regime gate Phase 2

FAIL-SOFT: mọi lỗi per-symbol → skip symbol đó, không chặn pipeline
(workflow đặt continue-on-error, nhưng script cũng tự exit 0).

CHANGELOG:
  v3.0 (2026-07-04) — initial Phase 1 theo DESIGN_V2F_SCORING_V3.md +
                      evidence signal_ic_20260704.
"""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

os.environ["VNSTOCK_INTERACTIVE"] = "0"
os.environ["VNSTOCK_LANGUAGE"]    = "en"
os.environ["MPLCONFIGDIR"]        = "/home/runner/.config/matplotlib"

import json
import logging
import traceback

from utils.cache import load_json, save_json
from utils.v2f_registry import (REGISTRY_VERSION, FACTORS, FACTOR_WEIGHTS,
                                THRESHOLDS, CONFLUENCE_BONUS,
                                CONFLUENCE_MIN_NORM, SIGNALS,
                                validate_registry, active_signals,
                                factor_caps)

logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s %(levelname)s %(message)s')
log = logging.getLogger(__name__)

SCORING_VERSION = "v3.0"
SIGNALS_IN      = "v2f_signals.json"
CONTEXT_FILE    = "context.json"
SIGNALS_OUT     = "v2f_signals_v3.json"

# Siêu-nhóm cho confluence (3 nguồn thông tin ĐỘC LẬP thật sự)
SUPERGROUPS = {
    "price": ("mean_reversion", "breakout"),
    "flow":  ("flow",),
    "fund":  ("fundamental", "growth"),
}


def _f(v, default=None):
    try:
        x = float(v)
        return x if x == x else default
    except (TypeError, ValueError):
        return default


# ══════════════════════════════════════════════════════════════════════
# EXPECTED INTRADAY VOLUME FRACTION — đo từ log 04/07 (DESIGN mục 5)
# ══════════════════════════════════════════════════════════════════════
# Anchor: (phút trong ngày ICT, tỷ lệ volume tích lũy so với cả phiên)
_FRACTION_ANCHORS = [
    (9 * 60 + 30, 0.08), (9 * 60 + 55, 0.18), (10 * 60 + 55, 0.38),
    (11 * 60 + 30, 0.46), (13 * 60 + 0, 0.46),   # nghỉ trưa: đóng băng
    (13 * 60 + 25, 0.66), (13 * 60 + 55, 0.74),
    (14 * 60 + 30, 0.92), (14 * 60 + 55, 1.00),
]


def expected_fraction(snap_time: str):
    """'HH:MM' → tỷ lệ volume kỳ vọng đã tích lũy. None nếu ngoài phiên sáng
    sớm (trước 09:30, chưa đủ data để tin) — signal OF sẽ trả 0."""
    try:
        hh, mm = snap_time.split(":")
        m = int(hh) * 60 + int(mm)
    except (ValueError, AttributeError):
        return None
    if m < 9 * 60 + 30:
        return None
    if m >= 14 * 60 + 55:
        return 1.0
    for (m1, f1), (m2, f2) in zip(_FRACTION_ANCHORS, _FRACTION_ANCHORS[1:]):
        if m1 <= m <= m2:
            if m2 == m1:
                return f1
            return f1 + (f2 - f1) * (m - m1) / (m2 - m1)
    return None


# ══════════════════════════════════════════════════════════════════════
# SCORE FUNCTIONS — MỌI hàm phải trả int trong [-span, +span] (đối xứng)
# row = 1 dòng v2f_signals.json (chứa cả raw lẫn inherited)
# ══════════════════════════════════════════════════════════════════════

def sc_willr(row, ctx):
    wr = _f(row.get("willr_14"))
    if wr is None:
        return 0, ""
    if   wr <= -90: s = +6
    elif wr <= -80: s = +4
    elif wr <= -60: s = +2
    elif wr >= -10: s = -6
    elif wr >= -20: s = -4
    elif wr >= -40: s = -2
    else:           s = 0
    return s, f"WillR={wr:.0f}{s:+d}"


def sc_bb(row, ctx):
    bb = _f(row.get("bb_position"))
    if bb is None:
        return 0, ""
    if   bb < 0.10: s = +5
    elif bb < 0.20: s = +3
    elif bb > 0.90: s = -5
    elif bb > 0.80: s = -3
    else:           s = 0
    return s, f"BB={bb:.2f}{s:+d}"


def sc_overext(row, ctx):
    """price_vs_ema200 ĐẢO DẤU: căng lên → trừ (fade), căng xuống → cộng."""
    d = _f(row.get("price_vs_ema200_pct"))
    if d is None:
        p, e = _f(row.get("price")), _f(row.get("ema200"))
        if p and e:
            d = (p - e) / e * 100
    if d is None:
        return 0, ""
    if   d >  15: s = -3
    elif d >   8: s = -2
    elif d >   3: s = -1
    elif d < -15: s = +3
    elif d <  -8: s = +2
    elif d <  -3: s = +1
    else:         s = 0
    return s, f"OverextEMA200={d:+.0f}%{s:+d}"


def sc_rs_rev(row, ctx):
    """RS 20d ĐẢO DẤU: outperform mạnh → trừ (fade), underperform → cộng."""
    sr = _f(row.get("return_20d"))
    if sr is None:
        return 0, ""
    vr = _f(row.get("vnindex_return_20d"))
    if vr is None:
        vr = _f(ctx.get("vnindex_return_20d") or ctx.get("market_return_20d")
                or ctx.get("vnindex_chg_20d") or ctx.get("chg_20d"))
    if vr is not None:
        rs = (1 + sr / 100) / (1 + vr / 100)
        if   rs > 1.30: s = -4
        elif rs > 1.10: s = -2
        elif rs < 0.70: s = +4
        elif rs < 0.90: s = +2
        else:           s = 0
        return s, f"RSrev={rs:.2f}{s:+d}"
    # fallback không có VNINDEX: dùng return tuyệt đối, vẫn đảo
    if   sr >  15: s = -4
    elif sr >   5: s = -2
    elif sr < -15: s = +4
    elif sr <  -5: s = +2
    else:          s = 0
    return s, f"RSrev_abs={sr:+.0f}%{s:+d}"


def sc_cmf(row, ctx):        # gate:down — Phase 2
    c = _f(row.get("cmf"))
    if c is None:
        return 0, ""
    s = -3 if c > 0.1 else (+3 if c < -0.1 else 0)
    return s, f"CMFrev={c:.2f}{s:+d}"


def sc_stoch(row, ctx):      # gate:down — Phase 2
    k = _f(row.get("stoch_k"))
    if k is None:
        return 0, ""
    s = +3 if k < 20 else (-3 if k > 80 else 0)
    return s, f"Stoch={k:.0f}{s:+d}"


def sc_52w(row, ctx):
    if row.get("_ta_window") == "3M":
        return 0, "52W skip(3M)"
    p, h = _f(row.get("price")), _f(row.get("high_52w"))
    if not p or not h or h <= 0:
        return 0, ""
    d = (p - h) / h * 100
    if   d >  -2: s = +4
    elif d >  -8: s = +2
    else:         s = 0     # v4.14: BỎ phạt đáy (cũ: d<-25%→-2, d<-40%→-4). Một chiều
                            #        dương — chỉ thưởng gần đỉnh; vùng đáy để deep_dd lo.
    return s, f"52W={d:+.0f}%{s:+d}"


def sc_deepdd(row, ctx):
    """Deep drawdown / gần đáy 52T: giá càng sát ĐÁY biên độ 52 tuần → điểm
    DƯƠNG càng lớn (kỳ vọng bật lên sau khi giảm rất sâu). MỘT CHIỀU: chỉ
    thưởng vùng đáy, KHÔNG phạt vùng đỉnh (dist_52w/breakout đã phụ trách phía
    đỉnh) → tránh đối đầu trực tiếp. Dùng low_52w/high_52w có sẵn (max/min
    OHLCV 12M). pos = (giá-đáy)/(đỉnh-đáy): 0 = sát đáy, 1 = sát đỉnh.
    Bằng chứng (INDICATIVE, dưới guard 30): nhóm giảm >40% từ đỉnh có excess5d
    +1.38% / excess10d +1.46% trên 7 phiên 30/07-07/08 — proxy theo cách-đỉnh;
    nửa 'sát-đáy' cưỡi trên pos, CHƯA kiểm forward riêng (ledger thiếu low_52w)."""
    if row.get("_ta_window") == "3M":
        return 0, "DeepDD skip(3M)"
    p  = _f(row.get("price"))
    lo = _f(row.get("low_52w"))
    hi = _f(row.get("high_52w"))
    if not p or lo is None or hi is None or hi <= lo:
        return 0, ""
    pos = (p - lo) / (hi - lo)                 # 0 = sát đáy, 1 = sát đỉnh
    pos = max(0.0, min(1.0, pos))
    # B(v4.15): chỉ thưởng ĐÁY THẬT — pos < 0.20 (cũ: pos < 0.5, quá lỏng, 73/100
    #   mã bật, phần lớn chỉ 'dưới trung điểm' chứ không phải đáy). pos>=0.20 → 0.
    s = int(round(4 * max(0.0, 1.0 - pos / 0.20)))
    if s <= 0:
        return 0, f"DeepDD pos={pos:.2f}+0"
    # C(v4.15): neo 'cơ hội định giá' — hạ thưởng đáy nếu cơ bản RÕ xấu (đáy + cơ
    #   bản xấu = dao rơi thật, không phải cơ hội). FAIL-OPEN: finance_score_fund
    #   thiếu/None → GIỮ nguyên (tránh giết deep_dd khi finance cache lỗi/zero).
    fs = _f(row.get("finance_score_fund"))
    if fs is not None:
        if   fs <= -5: s = 0                    # cơ bản rất xấu → bỏ thưởng
        elif fs <   0: s = int(round(s * 0.5))  # cơ bản hơi xấu → giảm nửa
    return s, f"DeepDD pos={pos:.2f}{s:+d}"


def sc_vol_ratio(row, ctx):
    vr = _f(row.get("vol_ma_ratio"))
    if vr is None:
        return 0, ""
    if   vr > 2.0: s = +3
    elif vr > 1.5: s = +1
    elif vr < 0.5: s = -3
    elif vr < 0.7: s = -1
    else:          s = 0
    return s, f"VolRatio={vr:.1f}x{s:+d}"


def sc_of(row, ctx):
    """Order flow SAU FIX PHASE: vol_spike chia lại theo expected fraction."""
    vs = _f(row.get("_of_vol_spike"))
    st = row.get("snap_time") or ctx.get("_snap_time")
    frac = expected_fraction(st) if st else None
    if vs is None or frac is None or frac <= 0:
        return 0, ""
    adj = ((1 + vs / 100) / frac - 1) * 100    # % so với kỳ vọng theo giờ
    if   adj >  50: s = +4
    elif adj >  20: s = +2
    elif adj < -50: s = -4
    elif adj < -20: s = -2
    else:           s = 0
    return s, f"OFadj={adj:+.0f}%(f={frac:.2f}){s:+d}"


# ── Inherited: renorm điểm v2.3 về span đối xứng (max THẬT từ audit) ──

def _renorm(v, true_max, span):
    v = _f(v)
    if v is None or true_max <= 0:
        return 0
    v = max(-true_max, min(true_max, v))
    return int(round(v / true_max * span))


def sc_ff(row, ctx):
    # v4.11: 18→15 = tran thuc cua ff_score (net-stance +-10 + momentum +-5); clamp +-20 khong cham
    s = _renorm(row.get("ff_score"), 15, 6)
    return s, (f"FF(v2.3){s:+d}" if s else "")


def sc_prop(row, ctx):
    s = _renorm(row.get("ext_prop_score"), 10, 3)
    return s, (f"Prop{s:+d}" if s else "")


def sc_insider(row, ctx):
    s = _renorm(row.get("ext_insider_score"), 5, 2)
    return s, (f"Insider{s:+d}" if s else "")


def sc_fund(row, ctx):
    # v4.11 DEFECT FIX: BO phep tru ext_fv_score.
    #   fundamental_score (field output V2) la BASE PE/PB/ROE/D-E, DA KHONG chua fv
    #   -> tru fv la tru khong, dao dau (ma dat fv<0 bi cong, ma re fv>0 bi tru).
    #   Intent goc "FairVal naive -> off" = chi dung base. true_max 23->20 = clamp thuc cua field.
    base = _f(row.get("fundamental_score"), 0) or 0
    s = _renorm(base, 20, 8)
    return s, (f"Fund{s:+d}" if s else "")


def sc_growth(row, ctx):
    # v4.11: 15->10 = tran thuc cua growth_score (clamp +-10); truoc do norm tran bi ket 0.6
    s = _renorm(row.get("growth_score"), 10, 5)
    return s, (f"Growth{s:+d}" if s else "")


def sc_context(row, ctx):
    # v4.11 DEFECT FIX: BO phep tru ext_breadth_score (cung loi fair-value, hien tiem an vi breadth=0).
    #   context_score (field output V2) KHONG chua breadth -> tru la tru khong.
    base = _f(row.get("context_score"), 0) or 0
    s = _renorm(base, 5, 2)
    return s, (f"Ctx{s:+d}" if s else "")


def sc_none(row, ctx):
    return 0, ""


FN_TABLE = {
    "sc_willr": sc_willr, "sc_bb": sc_bb, "sc_overext": sc_overext,
    "sc_rs_rev": sc_rs_rev, "sc_cmf": sc_cmf, "sc_stoch": sc_stoch,
    "sc_52w": sc_52w, "sc_deepdd": sc_deepdd, "sc_vol_ratio": sc_vol_ratio, "sc_ff": sc_ff,
    "sc_of": sc_of, "sc_prop": sc_prop, "sc_insider": sc_insider,
    "sc_fund": sc_fund, "sc_growth": sc_growth, "sc_context": sc_context,
    "sc_none": sc_none,
}


# ══════════════════════════════════════════════════════════════════════
# CORE — chấm 1 symbol, 2 khung
# ══════════════════════════════════════════════════════════════════════

# Field scoring của v2.3 KHÔNG được lọt vào output v3 (v3 phải tự chủ
# decision/điểm số; chỉ passthrough DATA THÔ: TA, _of_*, FF raw, finance...)
_V23_SCORING_KEYS = {"decision", "confidence", "total_score", "base_score_v2",
                     "signals", "pattern_flags", "confluence_bonus",
                     "data_completeness", "scoring_version"}


def _is_v23_scoring_field(k: str) -> bool:
    return (k in _V23_SCORING_KEYS or k.endswith("_score")
            or k.startswith("norm_"))


def score_symbol(row: dict, ctx: dict, caps: dict, actives: dict) -> dict:
    # PASSTHROUGH data thô từ row v2.3 → v2f_signals_v3.json TỰ CHỦ hoàn toàn:
    # price levels v3 + dashboard sau này đọc 1 file, không mượn gì của v2.3.
    out = {k: v for k, v in row.items() if not _is_v23_scoring_field(k)}
    out.update({
        "scoring_version":  SCORING_VERSION,
        "registry_version": REGISTRY_VERSION,
    })
    sig_labels = []
    sig_scores = {}                       # id → điểm (tính 1 lần, dùng 2 khung)

    for sid, factor, fn, span, horizons, status, source, _, _ in SIGNALS:
        if status != "active":
            continue
        try:
            s, label = FN_TABLE[fn](row, ctx)
        except Exception as e:
            log.warning(f"  {row.get('symbol')}: signal {sid} lỗi — {e}")
            s, label = 0, ""
        if abs(s) > span:                 # ép đối xứng — chặn bias tại nguồn
            log.warning(f"  {sid}: score {s} vượt span ±{span} → clamp")
            s = max(-span, min(span, s))
        sig_scores[sid] = s
        out[f"s_{sid}"] = s
        if label:
            sig_labels.append(label)

    for hz in ("trade", "hold"):
        f_raw = {f: 0 for f in FACTORS}
        for sid, factor, fn, span, horizons, status, source, _, _ in \
                actives[hz]:
            f_raw[factor] += sig_scores.get(sid, 0)

        f_norm, weighted = {}, 0.0
        for f in FACTORS:
            cap = caps[hz][f]
            n = max(-1.0, min(1.0, f_raw[f] / cap)) if cap > 0 else 0.0
            f_norm[f] = n
            weighted += FACTOR_WEIGHTS[hz][f] * n
            out[f"{hz}_{f}_raw"]  = f_raw[f]
            out[f"{hz}_{f}_norm"] = round(n, 4)
        pre_total = weighted * 100

        if hz == "trade":
            # Confluence: 3 siêu-nhóm độc lập, cùng hướng & đủ mạnh
            sgn = 1 if pre_total >= 0 else -1
            aligned = 0
            for name, fs in SUPERGROUPS.items():
                wsum = sum(FACTOR_WEIGHTS[hz][f] for f in fs)
                sn = (sum(FACTOR_WEIGHTS[hz][f] * f_norm[f] for f in fs)
                      / wsum) if wsum else 0
                if sn * sgn >= CONFLUENCE_MIN_NORM:
                    aligned += 1
            bonus = CONFLUENCE_BONUS * sgn if aligned >= 2 else 0
            total = max(-100.0, min(100.0, pre_total + bonus))
            out["confluence_bonus"] = bonus
            out["n_supergroups_aligned"] = aligned
            out["score_trade"] = round(total, 2)
            out["total_score"] = out["score_trade"]   # recorder compat
            for cut, name in THRESHOLDS:
                if cut is None or total >= cut:
                    out["decision"] = name
                    break
            out["confidence"] = ("HIGH" if aligned >= 2 and abs(total) >= 40
                                 else "MEDIUM" if abs(total) >= 25 else "LOW")
        else:
            out["score_hold"] = round(max(-100.0, min(100.0, pre_total)), 2)

    out["signals"] = " | ".join(sig_labels)
    return out


# ══════════════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════════════

def run():
    log.info("=== SCORING V3 (SHADOW, registry v%s) START ===",
             REGISTRY_VERSION)
    validate_registry()
    caps    = {hz: factor_caps(hz) for hz in ("trade", "hold")}
    actives = {hz: active_signals(hz) for hz in ("trade", "hold")}
    for hz in ("trade", "hold"):
        log.info(f"[{hz}] caps auto: {caps[hz]}")
    n_gate = sum(1 for s in SIGNALS if s[5].startswith("gate:"))
    if n_gate:
        log.info(f"{n_gate} tín hiệu gate:* SKIP (chờ regime gate Phase 2)")

    rows = load_json(SIGNALS_IN)
    if not rows:
        log.warning(f"{SIGNALS_IN} rỗng/không tồn tại — skip (shadow fail-soft)")
        return
    # BUGFIX 05/07: context.json của track V2F là LIST (không phải dict như
    # V1) → run đầu crash "list indices must be integers". Nhận cả 2 dạng.
    raw_ctx = load_json(CONTEXT_FILE)
    if isinstance(raw_ctx, dict):
        ctx = dict(raw_ctx)
    elif isinstance(raw_ctx, list) and raw_ctx and isinstance(raw_ctx[0], dict):
        ctx = dict(raw_ctx[0])
    else:
        ctx = {}
    if rows and isinstance(rows[0], dict) and rows[0].get("snap_time"):
        ctx["_snap_time"] = rows[0]["snap_time"]

    out_rows, n_err = [], 0
    for row in rows:
        try:
            out_rows.append(score_symbol(row, ctx, caps, actives))
        except Exception:
            n_err += 1
            log.warning(f"  skip {row.get('symbol')}:\n{traceback.format_exc()}")

    save_json(SIGNALS_OUT, out_rows)

    from collections import Counter
    dec = Counter(r.get("decision") for r in out_rows)
    log.info(f"Đã chấm {len(out_rows)}/{len(rows)} mã (lỗi {n_err}) → "
             f"{SIGNALS_OUT}")
    log.info(f"Decisions (trade): {dict(dec)}")
    if out_rows:
        top_h = sorted(out_rows, key=lambda r: r.get("score_hold") or -999,
                       reverse=True)[:5]
        log.info("Top-5 score_hold: " + ", ".join(
            f"{r['symbol']}={r.get('score_hold')}" for r in top_h))
    log.info("=== SCORING V3 (SHADOW) DONE ===")


if __name__ == "__main__":
    try:
        run()
    except Exception:
        log.error("V3 shadow crash (không chặn pipeline):\n"
                  + traceback.format_exc())
        sys.exit(0)      # fail-soft tuyệt đối
