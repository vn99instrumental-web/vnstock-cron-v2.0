"""
step_record_predictions.py — Ghi đề xuất (forward log) để validate sau
========================================================================
Chạy trong cron_intraday.yml SAU step_price_levels.py.
Đọc signals.json + trade_levels.json (đã có sẵn, KHÔNG gọi API) và
append snapshot của 20 mã vào ledger append-only theo tháng:

    output/history/predictions/{YYYY-MM}.jsonl   (1 dòng / mã / ngày)

Mục đích: khóa lại "tại thời điểm T, mô hình đề xuất gì" → để sau N phiên
step_eval_predictions.py đối chiếu với giá thật, tính hit-rate / IC từng
nhóm điểm → calibrate lại trọng số.

NGUYÊN TẮC LƯU TRỮ LÂU DÀI (đã chốt):
  - APPEND-ONLY, KHÔNG bao giờ sửa dòng đã ghi.
  - File này CHỈ ghi predictions; outcomes do step_eval ghi file riêng.
    → 2 workflow không đụng cùng file → không git conflict.
  - Partition theo tháng (signal_date[:7]) → eval chỉ nạp tháng gần đây.
  - Dedup theo pred_id = "{symbol}_{signal_date}" → chạy lại idempotent.
  - Mỗi dòng mang schema_version + scoring_version → lọc performance
    theo từng phiên bản mô hình (BẮT BUỘC khi tune trọng số).

KHI NÀO GHI:
  - Mặc định: MỌI run intraday đều ghi (ANCHOR_HOUR_ICT=0). Mỗi run là một
    observation độc lập — cho phép phân tích decision sáng vs chiều, model
    có flip nhiều trong ngày không, v.v.
  - pred_id chứa cả snap_time ("HPG_2026-06-04_1325") → 5 run/ngày → 5
    record/symbol/ngày. Cùng run bị retry (cùng snap_time) → dedup chặn.
  - Muốn quay lại "chỉ ghi run cuối": set env RECORD_ANCHOR_HOUR=14.
  - Ép ghi bất kể giờ: FORCE_RECORD=1.

⚠️ scoring_version: signals.json KHÔNG mang version → khai báo cứng ở đây.
   MỖI LẦN đổi trọng số / cap / threshold trong step_scoring.py → bump
   SCORING_VERSION bên dưới, nếu không phân tích performance sẽ trộn model.

CHANGELOG:
  v1 (2026-06-03) — initial: anchor-run gating, monthly JSONL, dedup,
                    join trade_levels (entry/stop/tp cho BUY, exit cho SELL).
"""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

os.environ["VNSTOCK_INTERACTIVE"] = "0"
os.environ["VNSTOCK_LANGUAGE"]    = "en"
os.environ["MPLCONFIGDIR"]        = "/home/runner/.config/matplotlib"
os.makedirs("/home/runner/.vnstock",           exist_ok=True)
os.makedirs("/home/runner/.config/matplotlib", exist_ok=True)

import json
import math
import logging

from config import OUTPUT_DIR
from utils.helpers import now_ict, today_str
from utils.cache import load_json

logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s %(levelname)s %(message)s')
log = logging.getLogger(__name__)

# =====================================================
# Config
# =====================================================

# ⚠️ BUMP MỖI KHI ĐỔI TRỌNG SỐ / CAP / THRESHOLD TRONG step_scoring.py
SCORING_VERSION = "v3"      # scoring system v3 (Phase 1+2)
SCHEMA_VERSION  = 1         # cấu trúc dòng predictions; bump nếu đổi field

SIGNALS_FILE    = "signals.json"
TRADE_LEVELS_FILE = "trade_levels.json"
HISTORY_SUBDIR  = "history/predictions"   # dưới OUTPUT_DIR

# Chỉ ghi ở run cuối ngày (ICT). Run cuối ~14:25 → hour == 14.
ANCHOR_HOUR_ICT = int(os.getenv("RECORD_ANCHOR_HOUR", "0"))
FORCE_RECORD    = os.getenv("FORCE_RECORD", "").lower() in ("1", "true", "yes")

BUY_DECISIONS  = {"BUY", "STRONG BUY"}
SELL_DECISIONS = {"SELL", "STRONG SELL"}

# Field copy nguyên tên từ signals.json → record (đủ để calibrate)
SIGNAL_COPY = [
    # identity
    "symbol", "exchange", "industry", "icb_code", "group",
    # decision
    "decision", "confidence",
    # aggregate scores
    "total_score", "tech_score", "fund_score",
    # group sub-scores (cho IC analysis từng nhóm)
    "trend_score", "momentum_score", "volume_score", "volatility_score",
    "order_flow_score", "ff_score", "fundamental_score", "cf_score",
    "growth_score", "news_score", "confluence_bonus", "context_score",
    # news breakdown
    "news_industry", "news_mention", "news_macro",
    # ref price (price_type cho biết realtime hay last_close)
    "price_type",
]

# Field trade_levels (buy_levels) → record, đổi tên flags để khỏi nhầm
TL_BUY_COPY = [
    "entry_style", "entry", "entry_low", "entry_high",
    "stop_loss", "risk_pct", "tp1", "tp2", "rr_tp1", "rr_headroom",
    "size_hint", "nearest_support", "nearest_resist",
]


# =====================================================
# Helpers
# =====================================================

def _clean(v):
    """NaN/inf float → None (JSON an toàn, eval không vướng NaN)."""
    if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
        return None
    return v


def _hist_path(month: str) -> str:
    """output/history/predictions/{YYYY-MM}.jsonl — tạo parent nếu cần."""
    path = os.path.join(OUTPUT_DIR, HISTORY_SUBDIR, f"{month}.jsonl")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    return path


def _existing_pred_ids(path: str, signal_date: str) -> set[str]:
    """pred_id đã ghi cho signal_date này (để dedup, idempotent re-run)."""
    ids: set[str] = set()
    if not os.path.exists(path):
        return ids
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                r = json.loads(line)
            except json.JSONDecodeError:
                continue
            if r.get("signal_date") == signal_date and r.get("pred_id"):
                ids.add(r["pred_id"])
    return ids


def _append_jsonl(path: str, records: list[dict]) -> None:
    """Append-only. Mỗi record 1 dòng."""
    with open(path, "a", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False, default=str) + "\n")


def _build_record(sig: dict, signal_date: str, recorded_at: str,
                  buy_map: dict, exit_map: dict) -> dict | None:
    sym = sig.get("symbol")
    if not sym:
        return None

    # pred_id chứa cả snap_time → mỗi run trong ngày là 1 record riêng.
    # Cùng run bị retry (cùng snap_time) → dedup chặn ghi trùng.
    snap = (sig.get("snap_time") or now_ict().strftime("%H:%M")).replace(":", "")
    pid  = f"{sym}_{signal_date}_{snap}"

    rec = {
        "schema_version": SCHEMA_VERSION,
        "scoring_version": SCORING_VERSION,
        "pred_id":   pid,
        "signal_date": signal_date,
        "recorded_at": recorded_at,
        "snap_time": sig.get("snap_time"),
    }

    for k in SIGNAL_COPY:
        rec[k] = _clean(sig.get(k))

    # ref price (đổi tên cho rõ: đây là mốc tham chiếu lúc đề xuất)
    rec["ref_price"] = _clean(sig.get("price"))

    # pattern_flags: list[str]
    rec["pattern_flags"] = sig.get("pattern_flags") or []

    decision = sig.get("decision")
    rec["actionable"] = decision in BUY_DECISIONS

    # ── Join trade_levels ──
    if decision in BUY_DECISIONS and sym in buy_map:
        tl = buy_map[sym]
        for k in TL_BUY_COPY:
            rec[k] = _clean(tl.get(k))
        rec["tl_flags"] = tl.get("flags") or ""
        rec["tl_skip"]  = tl.get("skip") or ""
    elif decision in SELL_DECISIONS and sym in exit_map:
        rec["exit_trigger"] = _clean(exit_map[sym])

    return rec


# =====================================================
# MAIN
# =====================================================

def main():
    now = now_ict()
    log.info(f"Time: {now:%Y-%m-%d %H:%M:%S} ICT | "
             f"anchor_hour={ANCHOR_HOUR_ICT} force={FORCE_RECORD}")

    # ── Anchor gate: chỉ ghi run cuối ngày ──
    if not FORCE_RECORD and now.hour < ANCHOR_HOUR_ICT:
        log.info(f"Bỏ qua: chưa tới run cuối ngày (hour {now.hour} < "
                 f"{ANCHOR_HOUR_ICT}). Đặt FORCE_RECORD=1 để ép ghi.")
        return

    signals = load_json(SIGNALS_FILE)
    if not signals or not isinstance(signals, list):
        log.warning(f"{SIGNALS_FILE} trống hoặc không hợp lệ — bỏ qua.")
        return

    # signal_date lấy từ record (đồng nhất cả 20 mã); fallback hôm nay
    signal_date = signals[0].get("date") or today_str()
    recorded_at = now.isoformat()
    month = signal_date[:7]   # YYYY-MM

    # ── Build map từ trade_levels ──
    tl = load_json(TRADE_LEVELS_FILE) or {}
    buy_map = {b["symbol"]: b for b in tl.get("buy_levels", [])
               if isinstance(b, dict) and b.get("symbol")}
    exit_map = {e["symbol"]: e.get("exit_trigger")
                for e in tl.get("exit_levels", [])
                if isinstance(e, dict) and e.get("symbol")}
    log.info(f"trade_levels: {len(buy_map)} buy, {len(exit_map)} exit")

    # ── Dedup ──
    path = _hist_path(month)
    existing = _existing_pred_ids(path, signal_date)
    if existing:
        log.info(f"Đã có {len(existing)} pred_id cho {signal_date} — "
                 f"sẽ bỏ qua các mã trùng (idempotent).")

    # ── Build records ──
    new_records = []
    for sig in signals:
        rec = _build_record(sig, signal_date, recorded_at, buy_map, exit_map)
        if rec is None:
            continue
        if rec["pred_id"] in existing:
            continue
        new_records.append(rec)

    if not new_records:
        log.info("Không có record mới để ghi (tất cả đã tồn tại).")
        return

    _append_jsonl(path, new_records)

    n_buy = sum(1 for r in new_records if r["actionable"])
    log.info(f"💾 Ghi {len(new_records)} record vào {path} "
             f"({n_buy} actionable BUY) | scoring={SCORING_VERSION}")
    log.info("=== RECORD PREDICTIONS DONE ===")


if __name__ == "__main__":
    main()
