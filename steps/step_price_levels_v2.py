"""
step_price_levels_v2.py — Trade levels cho scoring v2
======================================================
Chạy SAU step_scoring_v2.py. Đọc signals_v2.json thay vì signals.json.
Output: trade_levels_v2.json / trade_levels_v2.csv

Logic hoàn toàn giống step_price_levels.py — chỉ đổi input/output file.

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
    compute_exit,
)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(levelname)s %(message)s'
)
log = logging.getLogger(__name__)

OUT_JSON = "trade_levels_v2.json"
OUT_CSV  = "trade_levels_v2.csv"


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

    buy_results  = []
    exit_results = []

    for sig in signals:
        sym      = sig.get("symbol")
        decision = sig.get("decision", "NEUTRAL")
        of_full  = of_map.get(sym, {})
        of_sum   = of_full.get("summary", {}) if isinstance(of_full, dict) else {}

        if decision in ("BUY", "STRONG BUY"):
            res = _full_levels(sig, of_sum, of_full)
            buy_results.append(res)
            if res.get("skip"):
                # Vẫn log đủ số để soi (số liệu giờ được giữ lại, kèm cờ cảnh báo)
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
        elif decision in ("SELL", "STRONG SELL"):
            exit_results.append(compute_exit(sig, of_sum))

    out = {
        "generated_at"   : now_ict().isoformat(),
        "scoring_version": "v2",
        "buy_count"      : len(buy_results),
        "exit_count"     : len(exit_results),
        "buy_levels"     : buy_results,
        "exit_levels"    : exit_results,
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

    log.info(f"Done: {len(buy_results)} BUY levels, "
             f"{len(exit_results)} exit triggers")
    log.info("=== PRICE LEVELS V2 DONE ===")


if __name__ == "__main__":
    run()
