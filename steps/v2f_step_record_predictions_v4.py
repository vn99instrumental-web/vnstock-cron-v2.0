"""
v2f_step_record_predictions_v4.py — Ghi SỔ C (shadow #2) cho scoring v4 (RCEG)
=============================================================================
Chạy trong v2f_cron_intraday.yml SAU v2f_step_scoring_v4.py.
Fork từ v2f_step_record_predictions_v3.py. KHÁC BIỆT so với v3:
  - Đọc v2f_signals_v4.json
  - Dùng CHUNG v2f_trade_levels.json (levels entry/stop scoring-agnostic → KHÔNG
    cần step price_levels_v4 riêng)
  - Ghi output/history/v2f_predictions_v4/{YYYY-MM}.jsonl (LEDGER RIÊNG)
  - pred_id = "{symbol}_{date}_{snap_time}_v2fv4"
  - Ghi THÊM metadata RCEG: regime (hiệu lực), regime_raw (trước hysteresis),
    gate_version, gates (dict factor→hệ số) → sau này đo hiệu quả V4 THEO regime
    trực tiếp từ ledger.

Trọng tài (v2f_step_eval_predictions.py) tự nhận sổ này — cần thêm 1 entry v4
vào TRACKS (xem hướng dẫn kèm).

CHANGELOG:
  v1 (2026-07-29) — initial, shadow #2 cho RCEG v4.1.
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

FLOW              = "v2f_v4"
SCHEMA_VERSION    = 1
SIGNALS_FILE      = "v2f_signals_v4.json"
TRADE_LEVELS_FILE = "v2f_trade_levels.json"   # dùng chung levels v2.3 (agnostic)
HISTORY_SUBDIR    = "history/v2f_predictions_v4"

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
    log.info("=== RECORD PREDICTIONS V4 (SHADOW#2 RCEG) START ===")
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
        pred_id  = f"{sym}_{snap_date}_{snap_time}_v2fv4"
        if not sym or pred_id in existing:
            continue

        trade = trade_map.get(sym, {}) if decision in ("BUY", "STRONG BUY") else {}

        rec = {
            "pred_id"         : pred_id,
            "symbol"          : sym,
            "signal_date"     : snap_date,
            "snap_time"       : snap_time,
            "scoring_version" : sig.get("scoring_version") or "v4.1",
            "registry_version": sig.get("registry_version"),
            "gate_version"    : sig.get("gate_version"),
            "flow"            : FLOW,
            "universe_variant": "vn100",   # 2026-08-26: BO HNX30 (truoc: full_vn100 = VN100+HNX30)
            "schema_version"  : SCHEMA_VERSION,

            "total_score"     : sig.get("total_score"),   # = score_trade
            "score_trade"     : sig.get("score_trade"),
            "score_hold"      : sig.get("score_hold"),
            "decision"        : decision,
            "confidence"      : sig.get("confidence"),
            "confluence_bonus": sig.get("confluence_bonus"),
            "n_supergroups_aligned": sig.get("n_supergroups_aligned"),

            # ── RCEG metadata: để đo hiệu quả V4 THEO regime từ ledger ──
            "regime"          : sig.get("_regime"),        # regime hiệu lực (sau hysteresis)
            "regime_raw"      : sig.get("_regime_raw"),    # regime thô (trước hysteresis)
            "gates"           : sig.get("_gates"),         # dict factor→hệ số gate
            # ── Cờ RECOVERY (v4.2) — đánh dấu vĩnh viễn BUY nào rơi ngày điểm ngoặt ──
            "regime_v42"      : sig.get("regime_v42"),     # regime RECOVERY-aware
            "recovery_warn"   : sig.get("recovery_warn"),  # True = BUY trong RECOVERY
            "warn_msg"        : sig.get("warn_msg"),

            "price"           : sig.get("price"),
            "industry"        : sig.get("industry"),

            # rank trong nhóm ngành (kế thừa metadata — KHÔNG dùng ra quyết định)
            "sector_group"    : sig.get("sector_group"),
            "rank_fund_grp"   : sig.get("rank_fund_grp"),
            "rank_fund_uni"   : sig.get("rank_fund_uni"),
            "rank_trend_grp"  : sig.get("rank_trend_grp"),
            "rank_ff_grp"     : sig.get("rank_ff_grp"),
            "ff_intra_ratio" : sig.get("ff_intra_ratio"),
            "ff_intra_frac"  : sig.get("ff_intra_frac"),
            "ff_intra_pts"   : sig.get("ff_intra_pts"),
            "ff_intra_net"      : sig.get("ff_intra_net"),
            "ff_intra_flag_pts" : sig.get("ff_intra_flag_pts"),
            "of_bp_pts"         : sig.get("of_bp_pts"),
            # Ư5 shadow (v4.7): fundamental so-trong-ngành — KHÔNG dùng ra quyết định,
            # chỉ để forward-validate (so IC score_trade vs score_trade_altfund).
            "score_trade_altfund" : sig.get("score_trade_altfund"),
            "decision_altfund"    : sig.get("decision_altfund"),
            "_alt_fund_pts"       : sig.get("_alt_fund_pts"),
            "_altfund_delta"      : sig.get("_altfund_delta"),     # v4.10: đối xứng _gate1_delta
            # SHADOW ĐỐI CHỨNG MR-OFF (v4.8): production bật MR — forward so.
            "score_trade_nomr"    : sig.get("score_trade_nomr"),
            "decision_nomr"       : sig.get("decision_nomr"),
            "_nomr_delta"         : sig.get("_nomr_delta"),        # v4.10: đối xứng _gate1_delta
            # SHADOW RANK CROSS-SECTIONAL (v4.10): fund+growth chấm theo hạng-trong-ngành
            # thay ngưỡng tuyệt đối — forward so score_trade vs score_trade_rank.
            "score_trade_rank"    : sig.get("score_trade_rank"),
            "decision_rank"       : sig.get("decision_rank"),
            "_rank_delta"         : sig.get("_rank_delta"),
            # SHADOW NGƯỢC GATE-1 (v4.9): production GATE fund/growth ở DOWN/DEEP —
            # bản này giữ gate=1.0 (hành vi cũ) để forward so gated vs cũ.
            "score_trade_gate1"   : sig.get("score_trade_gate1"),
            "decision_gate1"      : sig.get("decision_gate1"),
            "_gate1_delta"        : sig.get("_gate1_delta"),
            "rank_cf_grp"     : sig.get("rank_cf_grp"),
            "rank_growth_grp" : sig.get("rank_growth_grp"),
            "adtv_bil"        : sig.get("adtv_bil"),
            "size_band"       : sig.get("size_band"),
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
    reg = new_records[0].get("regime")
    log.info(f"Ghi {len(new_records)} records mới → {out_path} (regime={reg})")
    log.info(f"Breakdown: {dict(dec)}")
    log.info("=== RECORD PREDICTIONS V4 (SHADOW#2 RCEG) DONE ===")


if __name__ == "__main__":
    try:
        run()
    except Exception:
        import traceback
        log.error("V4 recorder crash (không chặn pipeline):\n"
                  + traceback.format_exc())
        sys.exit(0)
