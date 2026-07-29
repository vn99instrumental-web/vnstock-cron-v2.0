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

SCORING_VERSION = "v4.1"          # +gate v2 (breakout theo regime) + hysteresis
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
# CORE — chấm 1 symbol, 2 khung, CÓ gate theo regime
# ══════════════════════════════════════════════════════════════════════

def score_symbol_v4(row: dict, ctx: dict, caps: dict, actives: dict,
                    regime: str, regime_raw: str = None) -> dict:
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

    # gate theo regime cho từng factor (cùng regime cho mọi factor trong run)
    gates = {f: gate_for(f, regime) for f in FACTORS}
    out["_gates"] = dict(gates)

    for hz in ("trade", "hold"):
        f_raw = {f: 0 for f in FACTORS}
        for sid, factor, fn, span, horizons, status, source, _, _ in actives[hz]:
            f_raw[factor] += sig_scores.get(sid, 0)

        f_norm, weighted = {}, 0.0
        for f in FACTORS:
            cap = caps[hz][f]
            n = max(-1.0, min(1.0, f_raw[f] / cap)) if cap > 0 else 0.0
            f_norm[f] = n
            # CÁCH B: gate × weight × norm, KHÔNG renorm mẫu số → điểm co lại
            weighted += FACTOR_WEIGHTS[hz][f] * gates[f] * n
            out[f"{hz}_{f}_raw"]  = f_raw[f]
            out[f"{hz}_{f}_norm"] = round(n, 4)
        pre_total = weighted * 100

        if hz == "trade":
            sgn = 1 if pre_total >= 0 else -1
            aligned = 0
            for name, fs in SUPERGROUPS.items():
                # confluence dùng weight ĐÃ gate → không đếm factor đã tắt
                wsum = sum(FACTOR_WEIGHTS[hz][f] * gates[f] for f in fs)
                sn = (sum(FACTOR_WEIGHTS[hz][f] * gates[f] * f_norm[f]
                          for f in fs) / wsum) if wsum else 0
                if sn * sgn >= CONFLUENCE_MIN_NORM:
                    aligned += 1
            bonus = CONFLUENCE_BONUS * sgn if aligned >= 2 else 0
            total = max(-100.0, min(100.0, pre_total + bonus))
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

    gates = {f: gate_for(f, regime) for f in FACTORS}
    off   = [f for f in FACTORS if gates[f] == 0.0]
    half  = [f for f in FACTORS if 0.0 < gates[f] < 1.0]
    log.info(f"[V4] regime thô={raw_regime} → hiệu lực={regime} "
             f"(hysteresis: {hyst_status}) | date={run_date}")
    log.info(f"[V4] gates={gates}")
    if off:
        log.info(f"[V4] factor TẮT: {off} (Cách B → điểm co lại)")
    if half:
        log.info(f"[V4] factor NỬA LIỀU: " +
                 ", ".join(f"{f}={gates[f]}" for f in half))

    out_rows, n_err = [], 0
    for row in rows:
        try:
            out_rows.append(score_symbol_v4(row, ctx, caps, actives,
                                            regime, raw_regime))
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
            log.info("  (regime GIẢM → MR bật ở cả V3 lẫn V4 → Δ≈0 là ĐÚNG)")
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
