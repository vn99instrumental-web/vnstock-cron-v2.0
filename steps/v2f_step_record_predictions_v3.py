"""
v2f_step_record_predictions_v3.py — Ghi SỔ B (shadow ledger) cho scoring v3
=============================================================================
Chạy trong v2f_cron_intraday.yml SAU v2f_step_scoring_v3.py.
Fork từ v2f_step_record_predictions.py (đã audit 04/07). KHÁC BIỆT:
  - Đọc v2f_signals_v3.json (+ v2f_trade_levels.json dùng chung cho entry/stop)
  - Ghi output/history/v2f_predictions_v3/{YYYY-MM}.jsonl (LEDGER RIÊNG)
  - pred_id = "{symbol}_{date}_{snap_time}_v2fv3"
  - scoring_version đọc TỪ signal row (không hardcode — tránh lặp bug cũ)
  - Ghi CẢ score_trade + score_hold + factor norms 2 khung + per-signal s_*
    → sau này đo IC per-signal của v3 TRỰC TIẾP từ ledger, không cần git walk.

Trọng tài (v2f_step_eval_predictions.py) tự nhận sổ này — TRACKS đã khai sẵn.

CHANGELOG:
  v1 (2026-07-04) — initial, Phase 1 shadow.
"""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

os.environ["VNSTOCK_INTERACTIVE"] = "0"
os.environ["VNSTOCK_LANGUAGE"]    = "en"
os.environ["MPLCONFIGDIR"]        = "/home/runner/.config/matplotlib"

import json
import logging
from pathlib import Path

from utils.helpers import now_ict, today_str
from utils.cache   import load_json

logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s %(levelname)s %(message)s')
log = logging.getLogger(__name__)

FLOW              = "v2f_v3"
SCHEMA_VERSION    = 1
SIGNALS_FILE      = "v2f_signals_v3.json"
TRADE_LEVELS_FILE = "v2f_trade_levels_v3.json"  # levels RIÊNG của v3 (độc lập)
HISTORY_SUBDIR    = "history/v2f_predictions_v3"

ANCHOR_HOUR_ICT = int(os.environ.get("RECORD_ANCHOR_HOUR", "0"))
FORCE_RECORD    = os.environ.get("FORCE_RECORD", "") == "1"

from config import OUTPUT_DIR


def _should_record(now_hour: int) -> bool:
    if FORCE_RECORD:
        log.info("FORCE_RECORD=1 — bypass gate")
        return True
    if ANCHOR_HOUR_ICT == 0:
        return True
    return now_hour >= ANCHOR_HOUR_ICT


def _load_trade_map(trade_data) -> dict:
    if not trade_data:
        return {}
    items = trade_data.get("symbols") if isinstance(trade_data, dict) else trade_data
    out = {}
    if isinstance(items, dict):
        return items
    for t in items or []:
        if isinstance(t, dict) and t.get("symbol"):
            out[t["symbol"]] = t
    return out


def _load_existing_ids(path: Path) -> set:
    if not path.exists():
        return set()
    ids = set()
    with path.open(encoding="utf-8") as f:
        for ln in f:
            try:
                pid = json.loads(ln).get("pred_id")
                if pid:
                    ids.add(pid)
            except json.JSONDecodeError:
                continue
    return ids


def run():
    log.info("=== RECORD PREDICTIONS V3 (SHADOW) START ===")
    now = now_ict()
    if not _should_record(now.hour):
        log.info("Ngoài anchor hour — skip (FORCE_RECORD=1 để test)")
        return

    signals = load_json(SIGNALS_FILE)
    if not signals:
        log.warning(f"{SIGNALS_FILE} not found/rỗng — skip (shadow fail-soft)")
        return

    trade_map = _load_trade_map(load_json(TRADE_LEVELS_FILE))

    snap_date = signals[0].get("date") or today_str()
    snap_time = signals[0].get("snap_time") or now.strftime("%H:%M")

    out_dir = Path(OUTPUT_DIR) / HISTORY_SUBDIR
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{snap_date[:7]}.jsonl"

    existing = _load_existing_ids(out_path)
    log.info(f"Existing pred_ids in {out_path.name}: {len(existing)}")

    new_records = []
    for sig in signals:
        sym      = sig.get("symbol")
        decision = sig.get("decision", "NEUTRAL")
        pred_id  = f"{sym}_{snap_date}_{snap_time}_v2fv3"
        if not sym or pred_id in existing:
            continue

        trade = trade_map.get(sym, {}) if decision in ("BUY", "STRONG BUY") else {}

        rec = {
            "pred_id"         : pred_id,
            "symbol"          : sym,
            "signal_date"     : snap_date,
            "snap_time"       : snap_time,
            "scoring_version" : sig.get("scoring_version") or "v3.0",
            "registry_version": sig.get("registry_version"),
            "flow"            : FLOW,
            "universe_variant": "full_vn100",
            "schema_version"  : SCHEMA_VERSION,

            "total_score"     : sig.get("total_score"),   # = score_trade
            "score_trade"     : sig.get("score_trade"),
            "score_hold"      : sig.get("score_hold"),
            "decision"        : decision,
            "confidence"      : sig.get("confidence"),
            "confluence_bonus": sig.get("confluence_bonus"),
            "n_supergroups_aligned": sig.get("n_supergroups_aligned"),

            "price"           : sig.get("price"),
            "industry"        : sig.get("industry"),
            "exchange"        : sig.get("exchange"),

            # Trade levels (BUY/SB) — dùng chung file level với v2.3
            "entry"           : trade.get("entry"),
            "stop"            : trade.get("stop_loss") or trade.get("stop"),
            "tp1"             : trade.get("tp1"),
            "tp2"             : trade.get("tp2"),

            # Outcomes — trọng tài v2f_step_eval_predictions.py sẽ ghi sổ riêng
            "result_5d"       : "PENDING",
            "result_30d"      : "PENDING",
        }
        # Factor norms 2 khung + per-signal scores (để đo IC từ ledger)
        for k, v in sig.items():
            if k.startswith("s_") or k.endswith("_norm"):
                rec[k] = v
        new_records.append(rec)

    if not new_records:
        log.info("Không có record mới (dedup hoặc signals rỗng)")
        return

    with out_path.open("a", encoding="utf-8") as f:
        for rec in new_records:
            f.write(json.dumps(rec, ensure_ascii=False, default=str) + "\n")

    from collections import Counter
    dec = Counter(r["decision"] for r in new_records)
    log.info(f"Ghi {len(new_records)} records mới → {out_path}")
    log.info(f"Breakdown: {dict(dec)}")
    log.info("=== RECORD PREDICTIONS V3 (SHADOW) DONE ===")


if __name__ == "__main__":
    try:
        run()
    except Exception:
        import traceback
        log.error("V3 recorder crash (không chặn pipeline):\n"
                  + traceback.format_exc())
        sys.exit(0)
