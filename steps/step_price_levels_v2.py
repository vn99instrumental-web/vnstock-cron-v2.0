"""
step_price_levels_v2.py — Trade levels cho scoring v2
======================================================
Chạy SAU step_scoring_v2.py. Đọc signals_v2.json thay vì signals.json.
Output: trade_levels_v2.json / trade_levels_v2.csv

Logic dựa trên step_price_levels.py (V1, dùng chung với V3) — KHÔNG sửa V1.

CHANGELOG:
  2026-06-23 — HƯỚNG ĐẦY ĐỦ: mã BUY bị "wide_stop" vẫn xuất ĐẦY ĐỦ
               entry/SL/TP/RR (thay vì null), chỉ gắn cờ cảnh báo để
               dashboard hiển thị "⚠️ KHÔNG VÀO LỆNH" + warn-box.
               Cách làm: KHÔNG sửa step_price_levels.py (dùng chung với V3).
               Thay vào đó tạm nâng MAX_RISK_PCT lên ∞ quanh lúc gọi
               compute_levels (→ không rơi nhánh wide_stop → tính đủ số,
               không null), rồi tự áp lại ngưỡng rủi ro THẬT ở wrapper
               (gắn SKIP_WIDE_STOP / size_hint=NO_TRADE / skip="wide_stop",
               GIỮ NGUYÊN số). V1/V3 không đổi một dòng — patch được khôi
               phục trong finally.
               Lưu ý: "invalid_stop" (không có stop hợp lệ) vẫn để null —
               số liệu lúc đó vô nghĩa, hiển thị số là sai lệch.

  2026-06-24 — ĐỔI CONCEPT (Phương án A): tính trade levels cho TẤT CẢ mã
               (không chỉ BUY/STRONG BUY) để dashboard hiển thị entry/SL/TP
               cho mọi card.
                 • compute_levels (long, qua _full_levels) chạy cho cả 40 mã.
                 • Mã KHÔNG phải BUY/STRONG BUY → giữ NGUYÊN số nhưng gắn
                   skip="not_buy" + size_hint="NO_TRADE" + flag REF_ONLY:
                   đây là mức THAM CHIẾU kỹ thuật, KHÔNG phải tín hiệu vào lệnh.
                 • Toàn bộ kết quả gộp vào "buy_levels" (1 dòng / symbol,
                   không trùng) → n8n Trade Parse1/Trade Merge1 KHÔNG phải đổi.
                 • "exit_levels" để rỗng (giữ key cho tương thích ngược;
                   Generate HTML1 không dùng exit_trigger).
               Forward-validation KHÔNG đổi: step_record_predictions_v2 chỉ
               ghi buy_levels có `not skip` → chỉ mã BUY actionable vào ledger,
               mọi mã REF_ONLY (skip="not_buy") bị loại tự động. Integrity giữ.
               invalid_stop vẫn để null như cũ.
"""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

os.environ["VNSTOCK_INTERACTIVE"] = "0"
os.environ["VNSTOCK_LANGUAGE"]    = "en"
os.environ["MPLCONFIGDIR"]        = "/home/runner/.config/matplotlib"

import logging
import pandas as pd

from utils.helpers import now_ict
from utils.cache   import load_json, save_json, save_csv

# Import toàn bộ logic từ v1 — chỉ đổi file paths.
# Import thêm chính MODULE để patch tạm MAX_RISK_PCT (xem _full_levels).
import steps.step_price_levels as spl
from steps.step_price_levels import (
    compute_levels,
    compute_exit,  # giữ import cho tương thích (không còn dùng ở luồng chính)
)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(levelname)s %(message)s'
)
log = logging.getLogger(__name__)

OUT_JSON = "trade_levels_v2.json"
OUT_CSV  = "trade_levels_v2.csv"

# Quyết định được coi là "vào lệnh thật" (long-only thị trường VN).
ACTIONABLE_DECISIONS = ("BUY", "STRONG BUY")


# =====================================================
# HƯỚNG ĐẦY ĐỦ — giữ số khi wide_stop, chỉ gắn cờ cảnh báo
# =====================================================

def _reapply_risk_gate(res: dict, max_risk_pct: float) -> None:
    """
    Sau khi compute_levels chạy với MAX_RISK_PCT=∞ (không skip wide_stop, có
    đủ số), áp lại ngưỡng rủi ro THẬT:
      - risk_pct > max_risk_pct  → đánh dấu wide_stop nhưng GIỮ NGUYÊN số.
      - invalid_stop (compute_levels tự set)  → để nguyên (số đã null, đúng).
    """
    if res.get("skip") == "invalid_stop":
        return                       # không có stop hợp lệ → số rỗng là đúng

    rp = res.get("risk_pct")
    if rp is not None and rp > max_risk_pct:
        flags = [f for f in (res.get("flags", "") or "").split(",") if f]
        if "SKIP_WIDE_STOP" not in flags:
            flags.append("SKIP_WIDE_STOP")
        res["flags"]     = ",".join(flags)
        res["size_hint"] = "NO_TRADE"
        res["skip"]      = "wide_stop"


def _mark_reference_only(res: dict) -> None:
    """
    Mã KHÔNG phải BUY/STRONG BUY: số entry/SL/TP vẫn được tính & GIỮ NGUYÊN
    để dashboard hiển thị, nhưng đánh dấu rõ đây là mức THAM CHIẾU kỹ thuật,
    KHÔNG phải tín hiệu vào lệnh.
      - invalid_stop → để nguyên (số đã null, không có gì để hiển thị).
      - còn lại → flag REF_ONLY + size_hint=NO_TRADE + skip="not_buy".
        skip="not_buy" khiến step_record_predictions_v2 bỏ qua (không vào
        forward-validation ledger) — chỉ mã BUY actionable mới được ghi.
    """
    if res.get("skip") == "invalid_stop":
        return
    flags = [f for f in (res.get("flags", "") or "").split(",") if f]
    if "REF_ONLY" not in flags:
        flags.append("REF_ONLY")
    res["flags"]     = ",".join(flags)
    res["size_hint"] = "NO_TRADE"
    # Không ghi đè skip nếu đã là wide_stop (giữ lý do cụ thể hơn cho log/CSV),
    # nhưng vẫn đảm bảo bị loại khỏi ledger qua not_buy nếu chưa có skip.
    if not res.get("skip"):
        res["skip"] = "not_buy"


def _full_levels(sig: dict, of_sum: dict, of_full: dict) -> dict:
    """
    Gọi compute_levels nhưng tạm nâng MAX_RISK_PCT lên ∞ để KHÔNG rơi nhánh
    wide_stop → tính đủ entry/SL/TP/RR, không null. Khôi phục ngưỡng trong
    finally rồi áp lại gate ở wrapper. KHÔNG đụng step_price_levels.py / V3.
    """
    orig = getattr(spl, "MAX_RISK_PCT", 7.0)
    try:
        spl.MAX_RISK_PCT = float("inf")
        res = compute_levels(sig, of_sum, of_full)
    finally:
        spl.MAX_RISK_PCT = orig      # luôn khôi phục, kể cả khi lỗi
    _reapply_risk_gate(res, orig)
    return res


def run():
    log.info(f"=== PRICE LEVELS V2 START ({now_ict():%Y-%m-%d %H:%M:%S} ICT) ===")

    signals    = load_json("signals_v2.json")
    order_flow = load_json("order_flow_v2.json")

    if not signals:
        log.error("signals_v2.json not found — abort")
        return

    if not order_flow:
        log.warning("order_flow.json not found — levels sẽ thiếu POC/VAL data")
        order_flow = []

    # Build order_flow map
    of_map = {}
    if isinstance(order_flow, list):
        for r in order_flow:
            if isinstance(r, dict) and r.get("symbol"):
                of_map[r["symbol"]] = r

    buy_results   = []        # giờ chứa TẤT CẢ mã (actionable + reference)
    actionable_ct = 0
    ref_ct        = 0

    for sig in signals:
        sym      = sig.get("symbol")
        decision = sig.get("decision", "NEUTRAL")
        of_full  = of_map.get(sym, {})
        of_sum   = of_full.get("summary", {}) if isinstance(of_full, dict) else {}

        # Tính levels (long) cho MỌI mã — đủ số kể cả wide_stop.
        res = _full_levels(sig, of_sum, of_full)

        is_actionable = decision in ACTIONABLE_DECISIONS
        if not is_actionable:
            _mark_reference_only(res)   # giữ số, gắn REF_ONLY/NO_TRADE/not_buy

        buy_results.append(res)

        if is_actionable:
            actionable_ct += 1
            if res.get("skip"):
                log.info(f"  {sym} [{decision}] {res.get('entry_style','')} "
                         f"→ SKIP ({res['skip']}) [GIỮ SỐ] "
                         f"entry={res.get('entry')} SL={res.get('stop_loss')} "
                         f"({res.get('risk_pct')}%) TP1={res.get('tp1')} "
                         f"RR={res.get('rr_tp1')}")
            else:
                log.info(f"  {sym} [{decision}/{res.get('confidence','')}] "
                         f"{res.get('entry_style','')} entry={res.get('entry')} "
                         f"SL={res.get('stop_loss')} ({res.get('risk_pct')}%) "
                         f"TP1={res.get('tp1')} RR={res.get('rr_tp1')}")
        else:
            ref_ct += 1
            log.info(f"  {sym} [{decision}] REF_ONLY "
                     f"entry={res.get('entry')} SL={res.get('stop_loss')} "
                     f"({res.get('risk_pct')}%) TP1={res.get('tp1')} "
                     f"RR={res.get('rr_tp1')} skip={res.get('skip')}")

    out = {
        "generated_at"   : now_ict().isoformat(),
        "scoring_version": "v2",
        "buy_count"      : len(buy_results),   # = tổng số mã có levels
        "actionable_count": actionable_ct,     # mã BUY/STRONG BUY thực sự vào lệnh
        "reference_count": ref_ct,             # mã NEUTRAL/SELL — chỉ tham chiếu
        "exit_count"     : 0,
        "buy_levels"     : buy_results,
        "exit_levels"    : [],                 # giữ key cho tương thích ngược
    }
    save_json(OUT_JSON, out)

    if buy_results:
        df = pd.DataFrame(buy_results)
        col_order = [
            "symbol", "exchange", "decision", "confidence",
            "entry_style", "price", "entry_low", "entry", "entry_high",
            "stop_loss", "risk_pct", "tp1", "tp2", "rr_tp1",
            "rr_headroom", "size_hint", "nearest_support",
            "nearest_resist", "levels_used", "flags", "skip",
        ]
        cols = [c for c in col_order if c in df.columns]
        save_csv(OUT_CSV, df[cols])

    log.info(f"Done: {len(buy_results)} mã có levels "
             f"({actionable_ct} actionable, {ref_ct} reference-only)")
    log.info("=== PRICE LEVELS V2 DONE ===")


if __name__ == "__main__":
    run()
