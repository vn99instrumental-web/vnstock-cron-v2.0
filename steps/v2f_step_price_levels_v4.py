"""
v2f_step_price_levels_v4.py — Trade levels RIÊNG cho shadow v4 "RCEG"
==========================================================================
FORK mỏng theo đúng pattern v2f_step_price_levels_v3.py (chỉ đổi I/O), để bộ
output của v4 TỰ CHỦ hoàn toàn — KHÔNG mượn levels của v2.3.

LÝ DO TỒN TẠI (bug đã phát hiện 03/08/2026):
  Trước đây node dashboard V4 nạp v2f_trade_levels.json (bản v2.3) làm nguồn
  trade-levels. File đó mang sẵn decision/confidence của v2.3. Khi n8n merge
  (combine, enrichInput2) ghép nó với v2f_signals_v4.json theo symbol, các
  field trùng tên decision/confidence của v2.3 ĐÈ LÊN decision v4 → dashboard
  hiển thị "điểm v4 âm nhưng quyết định BUY (v2.3)". Bản v4 này cắt đứt gốc:
  trade-levels tính TRỰC TIẾP từ v2f_signals_v4.json nên decision/confidence
  trong output là của v4 → merge không còn gì để đè sai.

  - Input : v2f_signals_v4.json  (đã passthrough đủ TA thô: ema/bb/atr/
            supertrend/vol_ma_ratio... — engine v4 lo việc này)
            + v2f_order_flow.json (data thị trường thô — dùng chung là đúng;
            "độc lập" nghĩa là không mượn QUYẾT ĐỊNH của v2.3, không phải
            không dùng chung dữ liệu gốc)
  - Output: v2f_trade_levels_v4.json (LIST phẳng — Trade V4 Parse tự nhận)

LOGIC tính entry/SL/TP: import compute_levels từ step_price_levels (một
nguồn sự thật duy nhất cho công thức levels toàn hệ — sửa công thức 1 chỗ,
mọi track hưởng). Giữ nguyên cơ chế của bản v2f/v3:
  - Tính đủ số cho MỌI mã; không phải BUY/STRONG BUY → REF_ONLY + not_buy.
  - Patch tạm MAX_RISK_PCT=∞ để không rơi nhánh wide_stop null số, rồi áp
    lại gate — khôi phục trong finally, KHÔNG đụng module gốc.

LƯU Ý CHỦ ĐÍCH: signals_v4 KHÔNG có momentum_score/pattern_flags (bị lọc khi
passthrough — giống v3) → điều kiện BREAKOUT entry trong compute_levels không
bao giờ thỏa → v4 luôn dùng PULLBACK entry. Đây là hành vi ĐÚNG với engine
nghiêng mean-reversion: mua tại hỗ trợ, không đuổi breakout. (Nhất quán v3.)

CHANGELOG:
  v1 (2026-08-03) — initial: cắt phụ thuộc v2.3, bộ output độc lập cho v4.
"""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

os.environ["VNSTOCK_INTERACTIVE"] = "0"
os.environ["VNSTOCK_LANGUAGE"]    = "en"
os.environ["MPLCONFIGDIR"]        = "/home/runner/.config/matplotlib"

import logging
import traceback

from utils.helpers import now_ict
from utils.cache   import load_json, save_json

import steps.step_price_levels as spl
from steps.step_price_levels import compute_levels

logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s %(levelname)s %(message)s')
log = logging.getLogger(__name__)

# ── V4 namespacing — bộ file độc lập ──
SIGNALS_FILE = "v2f_signals_v4.json"
OF_FILE      = "v2f_order_flow.json"
OUT_JSON     = "v2f_trade_levels_v4.json"

ACTIONABLE_DECISIONS = ("BUY", "STRONG BUY")


def _reapply_risk_gate(res: dict, max_risk_pct: float) -> None:
    if res.get("skip") == "invalid_stop":
        return
    rp = res.get("risk_pct")
    if rp is not None and rp > max_risk_pct:
        flags = [f for f in (res.get("flags", "") or "").split(",") if f]
        if "SKIP_WIDE_STOP" not in flags:
            flags.append("SKIP_WIDE_STOP")
        res["flags"]     = ",".join(flags)
        res["size_hint"] = "NO_TRADE"
        res["skip"]      = "wide_stop"


def _mark_reference_only(res: dict) -> None:
    if res.get("skip") == "invalid_stop":
        return
    flags = [f for f in (res.get("flags", "") or "").split(",") if f]
    if "REF_ONLY" not in flags:
        flags.append("REF_ONLY")
    res["flags"]     = ",".join(flags)
    res["size_hint"] = "NO_TRADE"
    if not res.get("skip"):
        res["skip"] = "not_buy"


def _full_levels(sig: dict, of_sum: dict, of_full: dict) -> dict:
    orig = getattr(spl, "MAX_RISK_PCT", 7.0)
    try:
        spl.MAX_RISK_PCT = float("inf")
        res = compute_levels(sig, of_sum, of_full)
    finally:
        spl.MAX_RISK_PCT = orig
    _reapply_risk_gate(res, orig)
    return res


def run():
    log.info(f"=== PRICE LEVELS V4 (SHADOW) START "
             f"({now_ict():%Y-%m-%d %H:%M:%S} ICT) ===")

    signals    = load_json(SIGNALS_FILE)
    order_flow = load_json(OF_FILE)

    if not signals:
        log.warning(f"{SIGNALS_FILE} not found/rỗng — skip (shadow fail-soft)")
        return
    if not order_flow:
        log.warning(f"{OF_FILE} not found — levels sẽ thiếu POC/VAL data")
        order_flow = []

    of_map = {}
    if isinstance(order_flow, list):
        for r in order_flow:
            if isinstance(r, dict) and r.get("symbol"):
                of_map[r["symbol"]] = r

    results, actionable_ct, skip_ct = [], 0, 0
    for sig in signals:
        sym      = sig.get("symbol")
        decision = sig.get("decision", "NEUTRAL")
        of_full  = of_map.get(sym, {})
        of_sum   = of_full.get("summary", {}) if isinstance(of_full, dict) else {}

        try:
            res = _full_levels(sig, of_sum, of_full)
        except Exception as e:
            log.warning(f"  {sym}: compute_levels lỗi — {e}")
            continue

        if decision in ACTIONABLE_DECISIONS:
            actionable_ct += 1
            if res.get("skip"):
                skip_ct += 1
        else:
            _mark_reference_only(res)
        results.append(res)

    save_json(OUT_JSON, results)
    log.info(f"Đã tính levels {len(results)}/{len(signals)} mã → {OUT_JSON}")
    log.info(f"Actionable (BUY/SB theo V4): {actionable_ct} "
             f"(trong đó skip gate: {skip_ct})")
    log.info("=== PRICE LEVELS V4 (SHADOW) DONE ===")


if __name__ == "__main__":
    try:
        run()
    except Exception:
        log.error("V4 price levels crash (không chặn pipeline):\n"
                  + traceback.format_exc())
        sys.exit(0)
