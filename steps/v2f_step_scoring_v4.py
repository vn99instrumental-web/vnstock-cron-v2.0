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

SCORING_VERSION = "v4.0"
SIGNALS_IN      = "v2f_signals.json"
CONTEXT_FILE    = "context.json"
SIGNALS_OUT     = "v2f_signals_v4.json"

_VALID_REGIMES = set(REGIMES)


def _resolve_regime(ctx: dict, row: dict) -> str:
    r = (ctx.get("market_regime") or row.get("_ctx_regime")
         or row.get("market_regime") or "UNKNOWN")
    r = str(r).upper()
    return r if r in _VALID_REGIMES else "UNKNOWN"


# ══════════════════════════════════════════════════════════════════════
# CORE — chấm 1 symbol, 2 khung, CÓ gate theo regime
# ══════════════════════════════════════════════════════════════════════

def score_symbol_v4(row: dict, ctx: dict, caps: dict, actives: dict,
                    regime: str) -> dict:
    # passthrough data thô (bỏ field scoring của v2.3) — giống V3
    out = {k: v for k, v in row.items() if not _is_v23_scoring_field(k)}
    out.update({
        "scoring_version":  SCORING_VERSION,
        "registry_version": REGISTRY_VERSION,
        "gate_version":     GATE_VERSION,
        "_regime":          regime,
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

    regime = _resolve_regime(ctx, rows[0] if rows else {})
    gates  = {f: gate_for(f, regime) for f in FACTORS}
    off    = [f for f in FACTORS if gates[f] == 0.0]
    log.info(f"[V4] regime={regime} | gates={gates}")
    if off:
        log.info(f"[V4] factor TẮT theo regime: {off} (Cách B → điểm co lại)")

    out_rows, n_err = [], 0
    for row in rows:
        try:
            rg = _resolve_regime(ctx, row)     # regime thường đồng nhất cả run
            out_rows.append(score_symbol_v4(row, ctx, caps, actives, rg))
        except Exception:
            n_err += 1
            log.warning(f"  skip {row.get('symbol')}:\n{traceback.format_exc()}")

    save_json(SIGNALS_OUT, out_rows)

    dec = Counter(r.get("decision") for r in out_rows)
    log.info(f"Đã chấm {len(out_rows)}/{len(rows)} mã (lỗi {n_err}) → {SIGNALS_OUT}")
    log.info(f"Decisions (trade, regime={regime}): {dict(dec)}")
    if out_rows:
        top_h = sorted(out_rows, key=lambda r: r.get("score_hold") or -999,
                       reverse=True)[:5]
        log.info("Top-5 score_hold: " + ", ".join(
            f"{r['symbol']}={r.get('score_hold')}" for r in top_h))
    log.info("=== SCORING V4 (RCEG SHADOW#2) DONE ===")


if __name__ == "__main__":
    try:
        run()
    except Exception:
        log.error("V4 shadow crash (không chặn pipeline):\n"
                  + traceback.format_exc())
        sys.exit(0)      # fail-soft tuyệt đối
