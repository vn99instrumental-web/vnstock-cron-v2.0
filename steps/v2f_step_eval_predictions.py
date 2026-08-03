"""
v2f_step_eval_predictions.py — TRỌNG TÀI cho track V2F (cả v2.3 lẫn shadow v3)
================================================================================
Chạy trong cron_weekly.yml SAU step_eval_predictions.py (track V1 cũ).

VAI TRÒ (giải thích đơn giản): mỗi dự đoán trong sổ (ledger) là một "phiếu
niêm phong". Script này chờ phiếu "đủ tuổi" (đủ số phiên trôi qua), lấy GIÁ
THẬT từ VCI, chấm điểm rồi ghi vào sổ kết quả. Cùng một trọng tài, cùng một
luật cho cả hai người chơi (v2.3 và v3 shadow) → so sánh công bằng tuyệt đối.

CHẤM 2 SỔ × 2 KHUNG:
  ledger v2f_predictions      → v2f_outcomes       (TRADE, đủ 10 phiên)
                              → v2f_outcomes_hold  (HOLD,  đủ 20 phiên)
  ledger v2f_predictions_v3   → v2f_outcomes_v3      (TRADE)
                              → v2f_outcomes_v3_hold (HOLD)
  (ledger v3 chưa tồn tại → skip êm, không lỗi — sẵn sàng cho shadow Phase 1)

NGUYÊN TẮC (kế thừa step_eval_predictions.py, đã chốt):
  - APPEND-ONLY: mỗi pred chấm đúng MỘT lần/khung; dedup theo pred_id.
  - Đọc JSONL bằng RAW reader — TUYỆT ĐỐI KHÔNG dùng cache.load_json
    (load_json xóa file nếu gặp dòng lỗi!).
  - t0 = CLOSE của signal_date (không dùng giá giữa phiên → không look-ahead).
    Lưu ý V2F: 6 run/ngày → 6 pred/mã/ngày cùng chung t0; chúng khác nhau ở
    DECISION tại thời điểm chụp — đúng thứ ta muốn so sánh.
  - Intrabar chạm cả stop lẫn TP cùng phiên → giả định STOP trước (bảo thủ).
  - Fetch giá 1 lần/mã DÙNG CHUNG cho mọi sổ + mọi khung (tiết kiệm quota).

VERSION MAPPING (vấn đề audit 04/07): records trước 03/07 gắn tag "v2" dù
scoring thực tế đã đổi. Outcome ghi thêm scoring_version_effective suy từ
signal_date để lọc bucket chính xác:
    signal_date >= V23_START (2026-06-21)  → "v2.3"
    trước đó                               → "v2x_mixed" (v2.1/v2.2 trộn)
  ⚠️ Nếu ngày deploy v2.3 thực tế khác 21/06 → sửa hằng số V23_START.

ENV:
  EVAL_HORIZON_BARS : số phiên tối thiểu để đóng khung TRADE (default 10)
  HOLD_HORIZON_BARS : số phiên tối thiểu để đóng khung HOLD  (default 20)
  EVAL_MONTHS_BACK  : nạp thêm N tháng trước tháng hiện tại (default 1)

CHANGELOG:
  v1 (2026-07-04) — initial. Lấp lỗ hổng "sổ ghi đều nhưng không ai chấm"
                    (audit: không tồn tại outcomes cho v2f). Chấm HỒI TỐ được
                    toàn bộ backlog tháng 6 → không mất record nào.
  v2 (2026-07-18) — (A) GHI TĂNG DẦN: flush outcomes sau MỖI mã (trước đây
                    chỉ ghi 1 lần cuối vòng → timeout-minutes chém ngang là
                    mất trắng, sự cố 18/07: 2 lần cancel ở mã 60/140, 0 byte
                    ghi ra đĩa). Dedup pred_id sẵn có → rerun an toàn, chấm
                    tiếp từ chỗ dở.
                    (B) LỌC UNIVERSE: chỉ chấm mã thuộc universe hiện tại
                    (nguồn chuẩn utils/v2f_universe; fallback v2f_ranking.json
                    trên đĩa nếu VCI chết; fallback cuối = không lọc). Mã
                    ngoài universe (penny đời cũ) để OPEN, không đốt quota VCI.
                    Tắt lọc: EVAL_UNIVERSE_FILTER=0.
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
from pathlib import Path

from config import OUTPUT_DIR
from utils.helpers import today_str

logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s %(levelname)s %(message)s')
log = logging.getLogger(__name__)

# =====================================================
# Config
# =====================================================

SCHEMA_VERSION = 1

# (pred_subdir, out_trade_subdir, out_hold_subdir, nhãn log)
TRACKS = [
    ("history/v2f_predictions",    "history/v2f_outcomes",
     "history/v2f_outcomes_hold",    "v2.3-prod"),
    ("history/v2f_predictions_v3", "history/v2f_outcomes_v3",
     "history/v2f_outcomes_v3_hold", "v3-shadow"),
    ("history/v2f_predictions_v4", "history/v2f_outcomes_v4",
     "history/v2f_outcomes_v4_hold", "v4-shadow"),
]

TRADE_BARS = int(os.getenv("EVAL_HORIZON_BARS", "10"))
HOLD_BARS  = int(os.getenv("HOLD_HORIZON_BARS", "20"))
# Sub-horizon 10 phiên cho khung HOLD (2026-08-02): ghi outcome hold SỚM ở 10
# phiên → sổ *_hold10 đầy ngay để calibrate score_hold/rank_fund_grp mà không
# phải đợi đủ 20 phiên. Ghi vào SỔ RIÊNG (subdir +"10") → dedup pred_id riêng,
# KHÔNG va chạm sổ hold-20d (mỗi pred_id chấm đúng 1 lần/sổ). Không đụng scoring.
HOLD10_BARS = int(os.getenv("HOLD10_HORIZON_BARS", "10"))
MONTHS_BACK = int(os.getenv("EVAL_MONTHS_BACK", "1"))

RET_H_TRADE  = [1, 3, 5, 10]
RET_H_HOLD   = [10, 20]
RET_H_HOLD10 = [5, 10]

FETCH_BUFFER_DAYS = 12
FLAT_R_THRESHOLD  = 0.15   # |realized_R| dưới ngưỡng & không chạm tp/sl → FLAT

# Ngày deploy scoring v2.3 lên track V2F — dùng suy version thật cho records
# cũ gắn tag "v2". SỬA nếu ngày thực tế khác.
V23_START = "2026-06-21"


# =====================================================
# Helpers — RAW JSONL (không dùng cache.load_json!)
# =====================================================

def _path(subdir: str, month: str) -> Path:
    return Path(OUTPUT_DIR) / subdir / f"{month}.jsonl"


def _read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    out = []
    with path.open(encoding="utf-8") as f:
        for ln in f:
            ln = ln.strip()
            if not ln:
                continue
            try:
                out.append(json.loads(ln))
            except json.JSONDecodeError:
                log.warning(f"  bỏ qua 1 dòng JSONL lỗi trong {path.name}")
    return out


def _append_jsonl(path: Path, recs: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        for r in recs:
            f.write(json.dumps(r, ensure_ascii=False, default=str) + "\n")


def _month_of(date_str: str) -> str:
    return date_str[:7]


def _months_window() -> list[str]:
    """Tháng hiện tại + MONTHS_BACK tháng trước (đủ nạp backlog)."""
    months, d = [], datetime.strptime(today_str()[:7] + "-01", "%Y-%m-%d")
    for _ in range(MONTHS_BACK + 1):
        months.append(d.strftime("%Y-%m"))
        d = (d - timedelta(days=1)).replace(day=1)
    return sorted(set(months))


def _date_minus(date_str: str, days: int) -> str:
    d = datetime.strptime(date_str, "%Y-%m-%d") - timedelta(days=days)
    return d.strftime("%Y-%m-%d")


def _f(v):
    try:
        if v is None:
            return None
        x = float(v)
        return x if x == x else None
    except (TypeError, ValueError):
        return None


def effective_version(pred: dict) -> str:
    """Suy version thật cho records cũ gắn tag 'v2' (xem docstring)."""
    tagged = str(pred.get("scoring_version") or "")
    if tagged not in ("", "v2"):
        return tagged                      # v2.3+ tag đúng từ 03/07
    sd = pred.get("signal_date") or ""
    return "v2.3" if sd >= V23_START else "v2x_mixed"


# =====================================================
# Fetch OHLCV (VCI + retry backoff — giống step_eval gốc)
# =====================================================

def fetch_ohlcv(symbol: str, start: str, end: str) -> list[dict]:
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
            return [{
                "date":  r["time"].strftime("%Y-%m-%d"),
                "open":  _f(r.get("open")),
                "high":  _f(r.get("high")),
                "low":   _f(r.get("low")),
                "close": _f(r.get("close")),
            } for _, r in df.iterrows()]
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


# =====================================================
# Universe hiện tại (Patch B) + flush tăng dần (Patch A)
# =====================================================

UNIVERSE_FILTER = os.getenv("EVAL_UNIVERSE_FILTER", "1") != "0"
MIN_UNIVERSE_SIZE = 50   # sanity: nhỏ hơn mức này coi như fetch hỏng → fallback


def _load_current_universe() -> set | None:
    """
    Trả set mã thuộc universe hiện tại, hoặc None nếu không xác định được
    (None → KHÔNG lọc, giữ hành vi cũ — an toàn tuyệt đối).

    Thứ tự nguồn:
      1) utils.v2f_universe._build_core_universe (nguồn chuẩn, 2 call VCI nhẹ)
      2) output/v2f_ranking.json trên đĩa (universe từ lượt intraday gần nhất,
         KHÔNG cần mạng — cứu cánh khi VCI đang chập chờn)
      3) None → không lọc
    """
    # Nguồn 1: module chuẩn
    try:
        from utils.v2f_universe import _build_core_universe, INDEX_GROUPS
        syms = _build_core_universe(INDEX_GROUPS)
        if syms and len(syms) >= MIN_UNIVERSE_SIZE:
            log.info(f"  [universe] nguồn chuẩn v2f_universe: {len(syms)} mã")
            return set(syms)
        log.warning(f"  [universe] v2f_universe trả {len(syms) if syms else 0} mã "
                    f"(< {MIN_UNIVERSE_SIZE}) — thử fallback ranking file")
    except Exception as e:
        log.warning(f"  [universe] v2f_universe lỗi ({e}) — thử fallback ranking file")

    # Nguồn 2: ranking file trên đĩa
    try:
        rk_path = Path(OUTPUT_DIR) / "v2f_ranking.json"
        if rk_path.exists():
            with rk_path.open(encoding="utf-8") as f:
                data = json.load(f)
            rows = data if isinstance(data, list) else (
                data.get("rows") or data.get("data") or data.get("ranking") or [])
            syms = {str(r.get("symbol")).strip().upper()
                    for r in rows if isinstance(r, dict) and r.get("symbol")}
            if len(syms) >= MIN_UNIVERSE_SIZE:
                log.info(f"  [universe] fallback v2f_ranking.json: {len(syms)} mã")
                return syms
            log.warning(f"  [universe] ranking file chỉ có {len(syms)} mã "
                        f"(< {MIN_UNIVERSE_SIZE}) — bỏ lọc")
    except Exception as e:
        log.warning(f"  [universe] đọc v2f_ranking.json lỗi ({e}) — bỏ lọc")

    return None


def _flush_outcomes(outcomes: dict) -> int:
    """
    Patch A: append mọi record đang buffer xuống đĩa NGAY rồi xóa buffer.
    Gọi sau MỖI mã → timeout chém ngang chỉ mất tối đa 1 mã đang dở,
    phần đã chấm được commit if:always() vớt về repo.
    """
    n = 0
    for (out_sub, m), recs in sorted(outcomes.items()):
        if not recs:
            continue
        _append_jsonl(_path(out_sub, m), recs)
        n += len(recs)
    outcomes.clear()
    return n


# =====================================================
# Evaluate 1 prediction — 1 khung (trade hoặc hold)
# =====================================================

def evaluate_one(pred: dict, bars: list[dict],
                 min_bars: int, ret_horizons: list[int],
                 lens: str) -> tuple[dict | None, str]:
    """
    Trả (outcome | None, reason). None → chưa đủ điều kiện, để OPEN thử lại
    tuần sau. reason: ok | no_anchor | bad_t0 | immature
    """
    sd  = pred.get("signal_date")
    idx = next((i for i, b in enumerate(bars) if b["date"] == sd), None)
    if idx is None:
        return None, "no_anchor"

    t0 = bars[idx]["close"]
    if not t0 or t0 <= 0:
        return None, "bad_t0"

    future = bars[idx + 1:]
    if len(future) < min_bars:
        return None, "immature"

    window = future[:min_bars]

    out = {
        "schema_version":            SCHEMA_VERSION,
        "lens":                      lens,
        "scoring_version":           pred.get("scoring_version"),
        "scoring_version_effective": effective_version(pred),
        "pred_id":     pred["pred_id"],
        "symbol":      pred.get("symbol"),
        "signal_date": sd,
        "snap_time":   pred.get("snap_time"),
        "eval_date":   today_str(),
        "decision":    pred.get("decision"),
        "confidence":  pred.get("confidence"),
        "total_score": pred.get("total_score"),
        "t0_close":    round(t0, 4),
        "n_bars":      len(future),
    }

    # ── Lăng kính SIGNAL: forward returns ──
    for h in ret_horizons:
        if len(future) >= h and future[h - 1]["close"]:
            out[f"ret_{h}d"] = round((future[h - 1]["close"] - t0) / t0 * 100, 2)
        else:
            out[f"ret_{h}d"] = None

    highs = [b["high"] for b in window if b["high"] is not None]
    lows  = [b["low"]  for b in window if b["low"]  is not None]
    out["mfe_pct"] = round((max(highs) - t0) / t0 * 100, 2) if highs else None
    out["mae_pct"] = round((min(lows)  - t0) / t0 * 100, 2) if lows  else None

    # ── Lăng kính TRADE (chỉ khung trade + pred actionable có entry/stop) ──
    if lens == "trade":
        entry = _f(pred.get("entry"))
        stop  = _f(pred.get("stop") if pred.get("stop") is not None
                   else pred.get("stop_loss"))
        tp1   = _f(pred.get("tp1"))
        if (pred.get("decision") in ("BUY", "STRONG BUY")
                and entry and stop and entry > stop):
            filled_i = next((i for i, b in enumerate(window)
                             if b["low"] is not None and b["low"] <= entry), None)
            out["filled"] = filled_i is not None
            if filled_i is not None:
                risk = entry - stop
                hit_sl = hit_tp = None
                for b in window[filled_i:]:
                    lo, hi = b["low"], b["high"]
                    # cùng phiên chạm cả 2 → STOP trước (bảo thủ)
                    if lo is not None and lo <= stop:
                        hit_sl = b["date"]
                        break
                    if tp1 and hi is not None and hi >= tp1:
                        hit_tp = b["date"]
                        break
                out["hit_sl"]  = hit_sl
                out["hit_tp1"] = hit_tp
                if hit_sl:
                    out["realized_R"] = -1.0
                    out["outcome"]    = "STOP"
                elif hit_tp:
                    out["realized_R"] = round((tp1 - entry) / risk, 2)
                    out["outcome"]    = "TP1"
                else:
                    last = window[-1]["close"]
                    r = round((last - entry) / risk, 2) if last else None
                    out["realized_R"] = r
                    out["outcome"] = ("FLAT" if r is not None
                                      and abs(r) < FLAT_R_THRESHOLD
                                      else ("WIN_OPEN" if (r or 0) > 0
                                            else "LOSS_OPEN"))

    return out, "ok"


# =====================================================
# Main
# =====================================================

def main():
    log.info("=" * 60)
    log.info("  EVAL PREDICTIONS V2F — trọng tài 2 sổ × 2 khung")
    log.info(f"  TRADE ≥{TRADE_BARS} | HOLD ≥{HOLD_BARS} | "
             f"HOLD10 ≥{HOLD10_BARS} phiên | months={_months_window()}")
    log.info("=" * 60)
    months = _months_window()

    # ── Gom pending của mọi (track × khung), fetch giá chung ──
    jobs = []   # (pred, out_subdir, min_bars, ret_hs, lens, label)
    for pred_sub, out_trade, out_hold, label in TRACKS:
        preds = []
        for m in months:
            preds += _read_jsonl(_path(pred_sub, m))
        if not preds:
            log.info(f"[{label}] ledger trống/chưa tồn tại — skip")
            continue

        # Sổ hold10 = sổ hold + hậu tố "10" (subdir riêng, dedup riêng)
        out_hold10 = out_hold + "10"

        for out_sub, min_bars, ret_hs, lens in (
                (out_trade,  TRADE_BARS,  RET_H_TRADE,  "trade"),
                (out_hold,   HOLD_BARS,   RET_H_HOLD,   "hold"),
                (out_hold10, HOLD10_BARS, RET_H_HOLD10, "hold")):
            done = set()
            for m in months:
                for o in _read_jsonl(_path(out_sub, m)):
                    if o.get("pred_id"):
                        done.add(o["pred_id"])
            pend = [p for p in preds
                    if p.get("pred_id") and p["pred_id"] not in done
                    and p.get("symbol") and p.get("signal_date")]
            # Log theo tên sổ (phân biệt hold vs hold10 cho rõ)
            book = out_sub.split("/")[-1]
            log.info(f"[{label}/{book}] preds={len(preds)} "
                     f"đã chấm={len(done)} pending={len(pend)}")
            for p in pend:
                jobs.append((p, out_sub, min_bars, ret_hs, lens, label))

    if not jobs:
        log.info("Không có pred nào cần chấm — xong.")
        return

    # ── Fetch 1 lần/mã dùng chung ──
    by_symbol: dict[str, list] = defaultdict(list)
    for j in jobs:
        by_symbol[j[0]["symbol"]].append(j)

    # ── Patch B: chỉ chấm mã thuộc universe hiện tại ──
    if UNIVERSE_FILTER:
        universe = _load_current_universe()
        if universe:
            skipped = sorted(s for s in by_symbol if s not in universe)
            if skipped:
                n_jobs_skip = sum(len(by_symbol[s]) for s in skipped)
                log.info(f"  [universe] bỏ qua {len(skipped)} mã ngoài universe "
                         f"({n_jobs_skip} pred để OPEN): {', '.join(skipped)}")
                for s in skipped:
                    del by_symbol[s]
        else:
            log.warning("  [universe] không xác định được universe — "
                        "chấm TẤT CẢ mã (hành vi cũ)")

    end = today_str()
    outcomes: dict[tuple, list] = defaultdict(list)   # (out_sub, month) → recs
    stats = defaultdict(int)
    total = 0   # Patch A: cộng dồn qua các lần flush

    for i, (sym, jlist) in enumerate(sorted(by_symbol.items()), 1):
        earliest = min(j[0]["signal_date"] for j in jlist)
        bars = fetch_ohlcv(sym, _date_minus(earliest, FETCH_BUFFER_DAYS), end)
        if not bars:
            stats["fetch_empty"] += len(jlist)
            log.info(f"  [{i}/{len(by_symbol)}] ⊘ {sym}: no OHLCV "
                     f"({len(jlist)} job để OPEN)")
            time.sleep(0.4)
            continue

        n_ok = n_open = 0
        for pred, out_sub, min_bars, ret_hs, lens, label in jlist:
            out, reason = evaluate_one(pred, bars, min_bars, ret_hs, lens)
            if out is None:
                stats[reason] += 1
                n_open += 1
                continue
            outcomes[(out_sub, _month_of(pred["signal_date"]))].append(out)
            # hold10 đếm riêng (cùng lens="hold" nhưng sổ khác)
            _tag = "hold10" if out_sub.endswith("hold10") else lens
            stats[f"closed_{_tag}"] += 1
            n_ok += 1

        # ── Patch A: flush NGAY sau mỗi mã (chống mất trắng khi timeout) ──
        flushed = _flush_outcomes(outcomes)
        total += flushed

        log.info(f"  [{i}/{len(by_symbol)}] ✓ {sym}: {len(bars)} bars → "
                 f"chấm {n_ok}, OPEN {n_open}"
                 + (f" (💾 +{flushed}, tổng {total})" if flushed else ""))
        time.sleep(0.4)

    # ── Vét buffer còn sót (thường rỗng nhờ Patch A) ──
    total += _flush_outcomes(outcomes)

    log.info("─" * 50)
    log.info(f"Đã chấm (đóng)  : trade={stats['closed_trade']} "
             f"hold={stats['closed_hold']} hold10={stats['closed_hold10']} "
             f"(tổng {total})")
    log.info(f"Để OPEN         : immature={stats['immature']} "
             f"no_anchor={stats['no_anchor']} bad_t0={stats['bad_t0']} "
             f"fetch_empty={stats['fetch_empty']}")
    log.info("=== EVAL PREDICTIONS V2F DONE ===")


if __name__ == "__main__":
    main()
