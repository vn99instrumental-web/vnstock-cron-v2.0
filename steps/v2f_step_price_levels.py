"""
v2f_step_price_levels.py — Trade levels cho nhánh V2F (full-VN100)
==================================================================
FORK của step_price_levels_v2.py. KHÁC BIỆT: chỉ đổi I/O sang prefix v2f_.
  - Input : v2f_signals.json + v2f_order_flow.json
  - Output: v2f_trade_levels.json / v2f_trade_levels.csv

Giữ nguyên LOGIC ĐẦY ĐỦ: tính entry/SL/TP cho TẤT CẢ mã (không chỉ BUY) để
dashboard V2F hiển thị levels mọi card; mã không phải BUY/STRONG BUY giữ số
nhưng gắn skip="not_buy" + size_hint=NO_TRADE + flag REF_ONLY.
KHÔNG đụng steps/step_price_levels.py (V1 dùng chung với V3) — patch tạm
MAX_RISK_PCT rồi khôi phục trong finally.
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

import steps.step_price_levels as spl
from steps.step_price_levels import compute_levels

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(levelname)s %(message)s'
)
log = logging.getLogger(__name__)

# ── V2F namespacing ──
SIGNALS_FILE = "v2f_signals.json"
OF_FILE      = "v2f_order_flow.json"
OUT_JSON     = "v2f_trade_levels.json"
OUT_CSV      = "v2f_trade_levels.csv"

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
    log.info(f"=== PRICE LEVELS V2F START ({now_ict():%Y-%m-%d %H:%M:%S} ICT) ===")

    signals    = load_json(SIGNALS_FILE)
    order_flow = load_json(OF_FILE)

    if not signals:
        log.error(f"{SIGNALS_FILE} not found — abort")
        return

    if not order_flow:
        log.warning(f"{OF_FILE} not found — levels sẽ thiếu POC/VAL data")
        order_flow = []

    of_map = {}
    if isinstance(order_flow, list):
        for r in order_flow:
            if isinstance(r, dict) and r.get("symbol"):
                of_map[r["symbol"]] = r

    buy_results   = []
    actionable_ct = 0
    ref_ct        = 0

    for sig in signals:
        sym      = sig.get("symbol")
        decision = sig.get("decision", "NEUTRAL")
        of_full  = of_map.get(sym, {})
        of_sum   = of_full.get("summary", {}) if isinstance(of_full, dict) else {}

        res = _full_levels(sig, of_sum, of_full)

        is_actionable = decision in ACTIONABLE_DECISIONS
        if not is_actionable:
            _mark_reference_only(res)

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
        "generated_at"    : now_ict().isoformat(),
        "scoring_version" : "v2f",
        "buy_count"       : len(buy_results),
        "actionable_count": actionable_ct,
        "reference_count" : ref_ct,
        "exit_count"      : 0,
        "buy_levels"      : buy_results,
        "exit_levels"     : [],
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
    log.info("=== PRICE LEVELS V2F DONE ===")


if __name__ == "__main__":
    run()
