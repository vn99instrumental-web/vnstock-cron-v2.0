"""
step_record_predictions_v2.py — Forward log cho scoring v2
===========================================================
Giống step_record_predictions.py nhưng:
  - Đọc signals_v2.json + trade_levels_v2.json
  - Ghi vào output/history/predictions_v2/{YYYY-MM}.jsonl
  - scoring_version = "v2"
  - pred_id = "{symbol}_{date}_{snap_time}_v2"

Cho phép so sánh hit-rate v3 vs v2 sau ≥30 ngày production.
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

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(levelname)s %(message)s'
)
log = logging.getLogger(__name__)

# =====================================================
# Config
# =====================================================

SCORING_VERSION   = "v2"
SCHEMA_VERSION    = 1
SIGNALS_FILE      = "signals_v2.json"
TRADE_LEVELS_FILE = "trade_levels_v2.json"
HISTORY_SUBDIR    = "history/predictions_v2"   # tách riêng với v3

# Gate: chỉ ghi ở run 14:xx ICT (run cuối ngày)
# Set RECORD_ANCHOR_HOUR=0 để ghi mọi run (debug)
# Set FORCE_RECORD=1 để bypass gate
ANCHOR_HOUR_ICT = int(os.environ.get("RECORD_ANCHOR_HOUR", "0"))
FORCE_RECORD    = os.environ.get("FORCE_RECORD", "") == "1"

from config import OUTPUT_DIR


# =====================================================
# Helpers
# =====================================================

def _should_record(now_hour: int) -> bool:
    if FORCE_RECORD:
        log.info("FORCE_RECORD=1 — bypass gate")
        return True
    if ANCHOR_HOUR_ICT == 0:
        return True  # ghi mọi run
    return now_hour >= ANCHOR_HOUR_ICT


def _load_trade_map(trade_data: dict) -> dict:
    """symbol → trade record từ trade_levels_v2.json"""
    if not trade_data:
        return {}
    result = {}
    for r in trade_data.get("buy_levels", []):
        if r.get("symbol") and not r.get("skip"):
            result[r["symbol"]] = {
                "entry_low" : r.get("entry_low"),
                "entry"     : r.get("entry"),
                "entry_high": r.get("entry_high"),
                "stop_loss" : r.get("stop_loss"),
                "risk_pct"  : r.get("risk_pct"),
                "tp1"       : r.get("tp1"),
                "tp2"       : r.get("tp2"),
                "rr_tp1"    : r.get("rr_tp1"),
                "size_hint" : r.get("size_hint"),
                "entry_style": r.get("entry_style"),
                "flags"     : r.get("flags"),
            }
    return result


def _load_existing_ids(path: Path) -> set:
    """Đọc pred_id đã ghi để dedup."""
    if not path.exists():
        return set()
    ids = set()
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
                if rec.get("pred_id"):
                    ids.add(rec["pred_id"])
            except json.JSONDecodeError:
                pass
    return ids


# =====================================================
# Main
# =====================================================

def run():
    now    = now_ict()
    hour   = now.hour

    log.info(f"=== RECORD PREDICTIONS V2 START ({now:%Y-%m-%d %H:%M:%S} ICT) ===")

    if not _should_record(hour):
        log.info(f"Gate: hour={hour} < {ANCHOR_HOUR_ICT} — skip (set FORCE_RECORD=1 để test)")
        return

    # Load signals_v2.json
    signals = load_json(SIGNALS_FILE)
    if not signals:
        log.warning(f"{SIGNALS_FILE} not found hoặc rỗng — skip")
        return

    # Load trade_levels_v2.json (optional)
    trade_data = load_json(TRADE_LEVELS_FILE)
    trade_map  = _load_trade_map(trade_data or {})

    snap_date = signals[0].get("date", today_str())
    snap_time = signals[0].get("snap_time", now.strftime("%H%M"))

    # Output dir
    out_dir = Path(OUTPUT_DIR) / HISTORY_SUBDIR
    out_dir.mkdir(parents=True, exist_ok=True)

    # Monthly file partition
    month_key   = snap_date[:7]   # YYYY-MM
    out_path    = out_dir / f"{month_key}.jsonl"

    # Load existing pred_ids for dedup
    existing_ids = _load_existing_ids(out_path)
    log.info(f"Existing pred_ids in {out_path.name}: {len(existing_ids)}")

    # Build records
    new_records = []
    for sig in signals:
        sym      = sig.get("symbol")
        decision = sig.get("decision", "NEUTRAL")

        pred_id = f"{sym}_{snap_date}_{snap_time}_v2"
        if pred_id in existing_ids:
            continue   # dedup

        trade = trade_map.get(sym, {}) if decision in ("BUY", "STRONG BUY") else {}

        rec = {
            # Identity
            "pred_id"        : pred_id,
            "symbol"         : sym,
            "signal_date"    : snap_date,
            "snap_time"      : snap_time,
            "scoring_version": SCORING_VERSION,
            "schema_version" : SCHEMA_VERSION,

            # Scores (v2 scale ±100)
            "total_score"    : sig.get("total_score"),
            "base_score_v2"  : sig.get("base_score_v2"),
            "confluence_bonus": sig.get("confluence_bonus"),
            "decision"       : decision,
            "confidence"     : sig.get("confidence"),
            "pattern_flags"  : ",".join(sig.get("pattern_flags") or []),

            # Raw group scores (để tính IC sau này)
            "trend_score"      : sig.get("trend_score"),
            "momentum_score"   : sig.get("momentum_score"),
            "volume_score"     : sig.get("volume_score"),
            "volatility_score" : sig.get("volatility_score"),
            "order_flow_score" : sig.get("order_flow_score"),
            "depth_score"      : sig.get("depth_score"),
            "ff_score"         : sig.get("ff_score"),
            "fundamental_score": sig.get("fundamental_score"),
            "cf_score"         : sig.get("cf_score"),
            "growth_score"     : sig.get("growth_score"),
            "context_score"    : sig.get("context_score"),
            "news_score"       : sig.get("news_score"),

            # Normalized scores (v2 specific)
            "norm_trend"      : sig.get("norm_trend"),
            "norm_momentum"   : sig.get("norm_momentum"),
            "norm_volume"     : sig.get("norm_volume"),
            "norm_ff"         : sig.get("norm_ff"),
            "norm_fundamental": sig.get("norm_fundamental"),

            # Weights snapshot (để biết version nào dùng weight nào)
            "w_trend"       : sig.get("w_trend"),
            "w_momentum"    : sig.get("w_momentum"),
            "w_fundamental" : sig.get("w_fundamental"),

            # Price anchor
            "price"          : sig.get("price"),
            "price_type"     : sig.get("price_type"),
            "industry"       : sig.get("industry"),
            "exchange"       : sig.get("exchange"),

            # Trade levels (nếu BUY)
            "entry_low"   : trade.get("entry_low"),
            "entry"       : trade.get("entry"),
            "entry_high"  : trade.get("entry_high"),
            "stop_loss"   : trade.get("stop_loss"),
            "risk_pct"    : trade.get("risk_pct"),
            "tp1"         : trade.get("tp1"),
            "tp2"         : trade.get("tp2"),
            "rr_tp1"      : trade.get("rr_tp1"),
            "size_hint"   : trade.get("size_hint"),
            "entry_style" : trade.get("entry_style"),
            "flags"       : trade.get("flags"),

            # Outcomes — sẽ fill bởi step_eval_predictions.py
            "price_1d"    : None,
            "price_5d"    : None,
            "price_10d"   : None,
            "price_20d"   : None,
            "price_30d"   : None,
            "return_1d"   : None,
            "return_5d"   : None,
            "return_10d"  : None,
            "return_20d"  : None,
            "return_30d"  : None,
            "hit_tp1"     : None,
            "hit_sl"      : None,
            "result_5d"   : "PENDING",
            "result_30d"  : "PENDING",
        }
        new_records.append(rec)

    if not new_records:
        log.info("Không có record mới (tất cả đã dedup hoặc signals rỗng)")
        return

    # Append to JSONL
    with out_path.open("a", encoding="utf-8") as f:
        for rec in new_records:
            f.write(json.dumps(rec, ensure_ascii=False, default=str) + "\n")

    log.info(f"Ghi {len(new_records)} records mới → {out_path}")
    log.info(f"Breakdown: "
             f"SB={sum(1 for r in new_records if r['decision']=='STRONG BUY')} "
             f"BUY={sum(1 for r in new_records if r['decision']=='BUY')} "
             f"NEU={sum(1 for r in new_records if r['decision']=='NEUTRAL')} "
             f"SELL={sum(1 for r in new_records if r['decision'] in ('SELL','STRONG SELL'))}")
    log.info("=== RECORD PREDICTIONS V2 DONE ===")


if __name__ == "__main__":
    run()
