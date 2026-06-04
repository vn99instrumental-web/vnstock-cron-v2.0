"""
step_eval_predictions.py — Đối chiếu đề xuất với giá thật (weekly)
====================================================================
Chạy trong cron_weekly.yml. Đọc ledger predictions, lấy các pred đã
"đủ tuổi" (≥ EVAL_HORIZON_BARS phiên sau signal_date), fetch OHLCV thật
từ VCI rồi tính kết quả, ghi append-only vào:

    output/history/outcomes/{YYYY-MM}.jsonl   (partition theo signal_date)

KHÔNG gọi tới step nào khác. Chỉ đọc predictions + VCI Quote.history.

NGUYÊN TẮC (đã chốt):
  - APPEND-ONLY, ghi MỘT LẦN/pred khi đủ tuổi → outcomes immutable.
  - File này CHỈ ghi outcomes; predictions do recorder ghi → không đụng nhau.
  - Dedup theo pred_id: pred đã có trong outcomes → bỏ qua, không eval lại.
  - Đọc predictions/outcomes bằng RAW reader, KHÔNG dùng cache.load_json
    (load_json sẽ XÓA file nếu gặp dòng JSONL không parse được!).
  - copy scoring_version từ prediction → analyzer lọc theo model không cần join.

MỐC ĐO (tránh look-ahead):
  - t0 = CLOSE của signal_date (không dùng ref_price vì recorder chạy
    ~14:25, price_type="realtime" = giá giữa phiên).
  - Forward window = các phiên SAU signal_date (strictly future).
  - Path intrabar: cùng phiên chạm cả stop lẫn TP → giả định STOP trước
    (bảo thủ, tránh thổi phồng kết quả).

2 LĂNG KÍNH:
  - SIGNAL : ret_1/3/5/10d so với t0_close + MFE/MAE (mọi decision).
  - TRADE  : chỉ pred actionable (BUY/STRONG BUY, có entry, không skip) —
             fill (low ≤ entry), hit_tp/stop, first_hit, realized_R, outcome.

CHANGELOG:
  v1 (2026-06-03) — initial.
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
import time
import logging
from collections import defaultdict
from datetime import datetime, timedelta

from config import OUTPUT_DIR
from utils.helpers import now_ict, today_str

logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s %(levelname)s %(message)s')
log = logging.getLogger(__name__)

# =====================================================
# Config
# =====================================================

SCHEMA_VERSION  = 1

PRED_SUBDIR  = "history/predictions"
OUT_SUBDIR   = "history/outcomes"

# Số phiên giao dịch sau signal_date cần có để "đóng" 1 pred.
EVAL_HORIZON_BARS = int(os.getenv("EVAL_HORIZON_BARS", "10"))
RET_HORIZONS      = [1, 3, 5, 10]

# Fetch dư vài ngày lịch để chắc chắn có bar của signal_date.
FETCH_BUFFER_DAYS = 12

# |realized_R| dưới ngưỡng này (khi không chạm tp/stop) → coi như FLAT.
FLAT_R = 0.25

BUY_DECISIONS = {"BUY", "STRONG BUY"}


# =====================================================
# JSONL I/O (raw — KHÔNG dùng cache.load_json)
# =====================================================

def _path(subdir: str, month: str) -> str:
    path = os.path.join(OUTPUT_DIR, subdir, f"{month}.jsonl")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    return path


def _read_jsonl(path: str) -> list[dict]:
    out = []
    if not os.path.exists(path):
        return out
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                log.warning(f"  bỏ qua dòng JSONL lỗi trong {path}")
    return out


def _append_jsonl(path: str, records: list[dict]) -> None:
    with open(path, "a", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False, default=str) + "\n")


# =====================================================
# Date helpers
# =====================================================

def _month_of(date_str: str) -> str:
    return date_str[:7]


def _prev_month(month: str) -> str:
    y, m = int(month[:4]), int(month[5:7])
    y, m = (y - 1, 12) if m == 1 else (y, m - 1)
    return f"{y:04d}-{m:02d}"


def _date_minus(date_str: str, days: int) -> str:
    d = datetime.strptime(date_str, "%Y-%m-%d") - timedelta(days=days)
    return d.strftime("%Y-%m-%d")


def _scan_months() -> list[str]:
    """Tháng hiện tại + tháng trước (đủ phủ pred ~10 phiên tuổi qua ranh giới tháng)."""
    this_m = _month_of(today_str())
    return [_prev_month(this_m), this_m]


# =====================================================
# Fetch OHLCV (theo bt_data.fetch_ohlcv: VCI + retry backoff)
# =====================================================

def fetch_ohlcv(symbol: str, start: str, end: str) -> list[dict]:
    """
    Trả list bar {date, open, high, low, close} sort tăng dần.
    [] nếu không có data. Retry backoff khi rate limit.
    """
    import pandas as pd
    from vnstock_data import Quote

    MAX_RETRIES = 4
    for attempt in range(MAX_RETRIES):
        try:
            df = Quote(source="VCI", symbol=symbol).history(
                start=start, end=end, interval="1D")
            if df is None or df.empty:
                return []

            df = df.sort_values("time").reset_index(drop=True)
            df["time"] = pd.to_datetime(df["time"])

            rename = {}
            for col in df.columns:
                lc = col.lower()
                if lc in ("vol", "volume"):
                    rename[col] = "volume"
                if lc in ("open", "high", "low", "close"):
                    rename[col] = lc
            if rename:
                df = df.rename(columns=rename)

            bars = []
            for _, r in df.iterrows():
                bars.append({
                    "date":  r["time"].strftime("%Y-%m-%d"),
                    "open":  _f(r.get("open")),
                    "high":  _f(r.get("high")),
                    "low":   _f(r.get("low")),
                    "close": _f(r.get("close")),
                })
            return bars

        except Exception as e:
            msg = str(e).lower()
            is_rate = ("rate limit" in msg or "giới hạn" in msg
                       or "300/300" in msg or "429" in msg)
            if is_rate and attempt < MAX_RETRIES - 1:
                wait = 15 * (attempt + 1)
                log.warning(f"  {symbol}: rate limit — chờ {wait}s "
                            f"(lần {attempt+1}/{MAX_RETRIES})")
                time.sleep(wait)
                continue
            log.warning(f"  {symbol}: fetch lỗi — {e}")
            return []
    return []


def _f(v):
    try:
        if v is None:
            return None
        f = float(v)
        return f if f == f else None   # loại NaN
    except (TypeError, ValueError):
        return None


# =====================================================
# Evaluate 1 prediction
# =====================================================

def evaluate_one(pred: dict, bars: list[dict]) -> tuple[dict | None, str]:
    """
    Trả (outcome_dict | None, reason).
    reason: "ok" | "no_anchor" | "immature" | "bad_t0"
    None → chưa eval được, để OPEN, tuần sau thử lại.
    """
    sd = pred.get("signal_date")
    idx = next((i for i, b in enumerate(bars) if b["date"] == sd), None)
    if idx is None:
        return None, "no_anchor"

    t0 = bars[idx]["close"]
    if not t0 or t0 <= 0:
        return None, "bad_t0"

    future = bars[idx + 1:]
    if len(future) < EVAL_HORIZON_BARS:
        return None, "immature"

    window = future[:EVAL_HORIZON_BARS]

    out = {
        "schema_version":  SCHEMA_VERSION,
        "scoring_version": pred.get("scoring_version"),
        "pred_id":     pred["pred_id"],
        "symbol":      pred.get("symbol"),
        "signal_date": sd,
        "eval_date":   today_str(),
        "decision":    pred.get("decision"),
        "actionable":  bool(pred.get("actionable")),
        "t0_close":    round(t0, 4),
        "n_bars":      len(future),
    }

    # ── Lăng kính SIGNAL: forward returns ──
    for h in RET_HORIZONS:
        if len(future) >= h and future[h - 1]["close"]:
            out[f"ret_{h}d"] = round((future[h - 1]["close"] - t0) / t0 * 100, 2)
        else:
            out[f"ret_{h}d"] = None

    highs = [b["high"] for b in window if b["high"] is not None]
    lows  = [b["low"]  for b in window if b["low"]  is not None]
    out["mfe_pct"] = round((max(highs) - t0) / t0 * 100, 2) if highs else None
    out["mae_pct"] = round((min(lows)  - t0) / t0 * 100, 2) if lows  else None

    # ── Lăng kính TRADE: chỉ pred actionable hợp lệ ──
    entry = _f(pred.get("entry"))
    stop  = _f(pred.get("stop_loss"))
    tp1   = _f(pred.get("tp1"))
    tp2   = _f(pred.get("tp2"))
    tradeable = (pred.get("actionable") and entry and stop
                 and (entry - stop) > 0 and not pred.get("tl_skip"))

    if not tradeable:
        out.update(filled=None, hit_tp1=None, hit_tp2=None, hit_stop=None,
                   first_hit=None, realized_R=None, outcome=None)
        return out, "ok"

    risk = entry - stop

    # Fill: phiên đầu tiên có low ≤ entry (pullback)
    start_scan = next((j for j, b in enumerate(window)
                       if b["low"] is not None and b["low"] <= entry), None)
    if start_scan is None:
        out.update(filled=False, fill_offset=None, hit_tp1=False, hit_tp2=False,
                   hit_stop=False, first_hit="NONE", realized_R=None,
                   outcome="NOT_FILLED")
        return out, "ok"

    hit_tp1 = hit_tp2 = hit_stop = False
    first_hit = "NONE"
    for b in window[start_scan:]:
        hi, lo = b["high"], b["low"]
        stop_touch = lo is not None and lo <= stop
        tp2_touch  = tp2 is not None and hi is not None and hi >= tp2
        tp1_touch  = tp1 is not None and hi is not None and hi >= tp1
        if stop_touch:                 # bảo thủ: stop ưu tiên nếu cùng phiên
            hit_stop = True
            first_hit = "STOP"
            break
        if tp2_touch:
            hit_tp1 = hit_tp2 = True
            first_hit = "TP2"
            break
        if tp1_touch:
            hit_tp1 = True
            first_hit = "TP1"
            break

    last_close = window[-1]["close"]
    if first_hit == "STOP":
        realized_R, outcome = round((stop - entry) / risk, 2), "LOSS"
    elif first_hit == "TP2":
        realized_R, outcome = round((tp2 - entry) / risk, 2), "WIN"
    elif first_hit == "TP1":
        realized_R, outcome = round((tp1 - entry) / risk, 2), "WIN"
    else:  # không chạm gì → mark-to-market cuối horizon
        if last_close:
            realized_R = round((last_close - entry) / risk, 2)
            outcome = ("WIN" if realized_R > FLAT_R else
                       "LOSS" if realized_R < -FLAT_R else "FLAT")
        else:
            realized_R, outcome = None, "FLAT"

    out.update(filled=True, fill_offset=start_scan + 1,
               hit_tp1=hit_tp1, hit_tp2=hit_tp2, hit_stop=hit_stop,
               first_hit=first_hit, realized_R=realized_R, outcome=outcome)
    return out, "ok"


# =====================================================
# MAIN
# =====================================================

def main():
    log.info(f"Time: {now_ict():%Y-%m-%d %H:%M:%S} ICT | "
             f"horizon={EVAL_HORIZON_BARS} phiên")

    months = _scan_months()
    log.info(f"Scan months: {months}")

    # ── Load predictions ──
    preds = []
    for m in months:
        preds += _read_jsonl(_path(PRED_SUBDIR, m))
    if not preds:
        log.info("Không có prediction nào trong cửa sổ — xong.")
        return

    # ── Pred đã eval (dedup) ──
    done_ids = set()
    for m in months:
        for o in _read_jsonl(_path(OUT_SUBDIR, m)):
            if o.get("pred_id"):
                done_ids.add(o["pred_id"])

    pending = [p for p in preds
               if p.get("pred_id") and p["pred_id"] not in done_ids]
    log.info(f"Predictions: {len(preds)} | đã eval: {len(done_ids)} | "
             f"pending: {len(pending)}")
    if not pending:
        log.info("Không có pred mới cần eval — xong.")
        return

    # ── Gom theo symbol, fetch 1 lần/mã ──
    by_symbol: dict[str, list[dict]] = defaultdict(list)
    for p in pending:
        by_symbol[p["symbol"]].append(p)

    end = today_str()
    outcomes_by_month: dict[str, list[dict]] = defaultdict(list)
    stats = defaultdict(int)

    for i, (sym, plist) in enumerate(sorted(by_symbol.items()), 1):
        earliest = min(p["signal_date"] for p in plist)
        start = _date_minus(earliest, FETCH_BUFFER_DAYS)
        bars = fetch_ohlcv(sym, start, end)
        if not bars:
            stats["fetch_empty"] += len(plist)
            log.info(f"  [{i}/{len(by_symbol)}] ⊘ {sym}: no OHLCV "
                     f"({len(plist)} pred để lại OPEN)")
            time.sleep(0.4)
            continue

        n_ok = n_skip = 0
        for p in plist:
            out, reason = evaluate_one(p, bars)
            if out is None:
                stats[reason] += 1
                n_skip += 1
                continue
            outcomes_by_month[_month_of(p["signal_date"])].append(out)
            stats["evaluated"] += 1
            if out.get("outcome"):
                stats[f"outcome_{out['outcome']}"] += 1
            n_ok += 1

        log.info(f"  [{i}/{len(by_symbol)}] ✓ {sym}: {len(bars)} bars → "
                 f"eval {n_ok}, để OPEN {n_skip}")
        time.sleep(0.4)

    # ── Ghi outcomes (append-only, partition theo signal_date) ──
    total_written = 0
    for m, recs in outcomes_by_month.items():
        _append_jsonl(_path(OUT_SUBDIR, m), recs)
        total_written += len(recs)
        log.info(f"  💾 {len(recs)} outcome → {OUT_SUBDIR}/{m}.jsonl")

    # ── Summary ──
    log.info("─" * 50)
    log.info(f"Evaluated (đóng) : {total_written}")
    log.info(f"Để OPEN          : immature={stats['immature']} "
             f"no_anchor={stats['no_anchor']} bad_t0={stats['bad_t0']} "
             f"fetch_empty={stats['fetch_empty']}")
    outcome_keys = [k for k in stats if k.startswith("outcome_")]
    if outcome_keys:
        dist = {k.replace('outcome_', ''): stats[k] for k in outcome_keys}
        log.info(f"Trade outcomes   : {dist}")
    log.info("=== EVAL PREDICTIONS DONE ===")


if __name__ == "__main__":
    main()
