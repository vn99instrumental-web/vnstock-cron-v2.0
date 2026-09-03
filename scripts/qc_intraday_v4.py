#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
qc_intraday_v4.py — PHASE CHECK OFFLINE sau mỗi intraday run.

MỤC ĐÍCH
  Đọc lại các file output/*.json mà run vừa tạo, phát hiện "thiếu data / lỗi data"
  của CHÍNH run đó, rồi ghi kết luận ra output/qc_last.json.
  KHÔNG gọi API, KHÔNG cần venv/vnstock (chỉ stdlib) → chạy vài giây.
  KHÔNG gửi Telegram trực tiếp: n8n đọc qc_last.json rồi tự bắn Telegram.

NGUYÊN TẮC
  - Chỉ ĐỌC data; file duy nhất được GHI là output/qc_last.json.
  - Luôn exit 0 (trừ khi QC_FAIL_ON_ERROR=1) → không làm đỏ pipeline; ok/không-ok
    nằm trong qc_last.json để n8n quyết định.
  - Mỗi check gắn severity: "ok" | "warn" | "error".
      error = chắc chắn hỏng (thiếu file, 0 dòng, price None, ledger run này rỗng).
      warn  = đáng ngờ (date cũ, thiếu dòng, lệch 2 track, BUY thiếu entry/tp1).
  - ok = KHÔNG có error VÀ KHÔNG có warn.

BIẾN MÔI TRƯỜNG (đều có default hợp lý)
  QC_EXPECT_DATE      : ép ngày kỳ vọng YYYY-MM-DD (rỗng = hôm nay theo ICT).
  QC_MIN_ROWS         : sàn số mã mỗi track (default 95; universe VN100 ~100).
  QC_MAX_NONE_PRICE   : số price None/0 tối đa cho phép (default 0).
  QC_SKIP_FRESHNESS   : "1" để bỏ qua check date cũ (ngày lễ/test).
  QC_CHECK_BUY_LEVELS : "1" (default) bật check BUY thiếu entry/tp1 trong ledger.
  QC_FAIL_ON_ERROR    : "1" để exit 1 khi có error (mặc định exit 0).
"""

import os
import sys
import json
import glob
from pathlib import Path
from datetime import datetime, timezone, timedelta

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "output"
LEDGER_DIR = OUT / "history" / "v2f_predictions_v4"

ICT = timezone(timedelta(hours=7))

# ── file cần có ──────────────────────────────────────────────────────────────
SIGNALS_V23 = OUT / "v2f_signals.json"
SIGNALS_V4 = OUT / "v2f_signals_v4.json"
TRADE_V4 = OUT / "v2f_trade_levels_v4.json"
CONTEXT = OUT / "context.json"
VNINDEX = OUT / "vnindex_live.json"
REGIME_ST = OUT / "v2f_v4_regime_state.json"

MIN_ROWS = int(os.environ.get("QC_MIN_ROWS", "95"))
MAX_NONE_PRICE = int(os.environ.get("QC_MAX_NONE_PRICE", "0"))
SKIP_FRESH = os.environ.get("QC_SKIP_FRESHNESS", "") == "1"
CHECK_BUY_LEVELS = os.environ.get("QC_CHECK_BUY_LEVELS", "1") == "1"
FAIL_ON_ERROR = os.environ.get("QC_FAIL_ON_ERROR", "") == "1"

BUY_SET = {"BUY", "STRONG BUY"}


def _load(path: Path):
    """Đọc JSON; trả (data, err_msg). err_msg=None nếu OK."""
    if not path.exists():
        return None, "không tồn tại"
    try:
        with path.open(encoding="utf-8") as f:
            return json.load(f), None
    except Exception as e:
        return None, f"lỗi parse: {e}"


class QC:
    def __init__(self):
        self.checks = []

    def add(self, cid, severity, msg):
        self.checks.append({"id": cid, "severity": severity, "msg": msg})

    def ok(self, cid, msg):
        self.add(cid, "ok", msg)

    def warn(self, cid, msg):
        self.add(cid, "warn", msg)

    def error(self, cid, msg):
        self.add(cid, "error", msg)


def main():
    qc = QC()
    now_ict = datetime.now(ICT)
    expect_date = os.environ.get("QC_EXPECT_DATE", "").strip() or now_ict.strftime("%Y-%m-%d")

    # 1) NẠP 2 file signals (bắt buộc) ──────────────────────────────────────
    sig4, e4 = _load(SIGNALS_V4)
    sig23, e23 = _load(SIGNALS_V23)

    if e4 or not isinstance(sig4, list):
        qc.error("signals_v4", f"{SIGNALS_V4.name}: {e4 or 'không phải list'}")
        sig4 = []
    if e23 or not isinstance(sig23, list):
        qc.error("signals_v23", f"{SIGNALS_V23.name}: {e23 or 'không phải list'}")
        sig23 = []

    n4, n23 = len(sig4), len(sig23)
    run_date = str(sig4[0].get("date")) if sig4 else (str(sig23[0].get("date")) if sig23 else None)
    snap_time = str(sig4[0].get("snap_time")) if sig4 else None

    # 2) SỐ DÒNG (đủ mã) ────────────────────────────────────────────────────
    if n4 == 0:
        qc.error("rows_v4", "v4 = 0 dòng (run không ra data)")
    elif n4 < MIN_ROWS:
        qc.warn("rows_v4", f"v4 chỉ {n4} dòng (< sàn {MIN_ROWS}) — nghi run cụt")
    else:
        qc.ok("rows_v4", f"v4 = {n4} dòng")

    if n23 == 0:
        qc.error("rows_v23", "v2.3 = 0 dòng")
    elif n23 < MIN_ROWS:
        qc.warn("rows_v23", f"v2.3 chỉ {n23} dòng (< sàn {MIN_ROWS})")
    else:
        qc.ok("rows_v23", f"v2.3 = {n23} dòng")

    # 3) LỆCH 2 TRACK (một nhánh hỏng một phần) ─────────────────────────────
    if n4 and n23:
        if n4 != n23:
            qc.warn("track_parity", f"lệch số mã v2.3={n23} vs v4={n4} — nghi 1 nhánh cụt")
        else:
            qc.ok("track_parity", f"khớp {n4} mã cả 2 track")

    # 4) PRICE None/0 + field bắt buộc ───────────────────────────────────────
    if sig4:
        none_price = sum(1 for r in sig4 if not r.get("price"))
        null_score = sum(1 for r in sig4 if r.get("score_trade") is None)
        null_dec = sum(1 for r in sig4 if not r.get("decision"))
        if none_price > MAX_NONE_PRICE:
            qc.error("price_v4", f"{none_price} mã price None/0 (cho phép ≤ {MAX_NONE_PRICE})")
        else:
            qc.ok("price_v4", "price đầy đủ")
        if null_score or null_dec:
            qc.error("fields_v4", f"{null_score} mã thiếu score_trade, {null_dec} mã thiếu decision")
        else:
            qc.ok("fields_v4", "score_trade/decision đầy đủ")

    # 5) TƯƠI (date == hôm nay ICT) ──────────────────────────────────────────
    if SKIP_FRESH:
        qc.ok("freshness", "bỏ qua (QC_SKIP_FRESHNESS=1)")
    elif run_date is None:
        qc.error("freshness", "không đọc được date từ signals")
    elif run_date != expect_date:
        qc.warn("freshness", f"data date={run_date} ≠ kỳ vọng {expect_date} — nghi dùng cache/không refresh")
    else:
        qc.ok("freshness", f"date={run_date} (đúng hôm nay)")

    # 6) VNINDEX live sidecar ────────────────────────────────────────────────
    vnx, evn = _load(VNINDEX)
    if evn or not isinstance(vnx, dict):
        qc.warn("vnindex_live", f"{VNINDEX.name}: {evn or 'sai shape'}")
    else:
        asof = str(vnx.get("asof_date"))
        if not SKIP_FRESH and asof != expect_date:
            qc.warn("vnindex_live", f"vnindex asof={asof} ≠ {expect_date}")
        elif vnx.get("level") in (None, 0):
            qc.warn("vnindex_live", "level None/0")
        else:
            qc.ok("vnindex_live", f"level={vnx.get('level')} asof={asof}")

    # 7) CONTEXT + REGIME STATE parse được ──────────────────────────────────
    ctx, ectx = _load(CONTEXT)
    if ectx or not ctx:
        qc.warn("context", f"{CONTEXT.name}: {ectx or 'rỗng'}")
    else:
        qc.ok("context", "context OK")

    rst, erst = _load(REGIME_ST)
    if erst or not isinstance(rst, dict) or "effective_regime" not in rst:
        qc.warn("regime_state", f"{REGIME_ST.name}: {erst or 'thiếu effective_regime'}")
    else:
        qc.ok("regime_state", f"regime={rst.get('effective_regime')}")

    # 8) LEDGER V4: run NÀY đã ghi chưa + BUY có entry/tp1 không ─────────────
    ledger_rows = _read_ledger_for_run(run_date, snap_time)
    if run_date is None:
        qc.warn("ledger_v4", "bỏ qua (không có run_date)")
    elif ledger_rows is None:
        qc.error("ledger_v4", f"không mở được partition {run_date[:7]}.jsonl")
    else:
        n_led = len(ledger_rows)
        if n_led == 0:
            qc.error("ledger_v4", f"ledger KHÔNG có dòng cho run này ({run_date} {snap_time}) — record step hỏng")
        else:
            qc.ok("ledger_v4", f"ledger có {n_led} dòng cho run này")
            # 8b) BUY thiếu entry/tp1 (bug _load_trade_map / sai file levels)
            if CHECK_BUY_LEVELS:
                buys = [r for r in ledger_rows if str(r.get("decision")) in BUY_SET]
                miss = [r for r in buys if r.get("entry") is None or r.get("tp1") is None]
                if buys and len(miss) == len(buys):
                    qc.warn("buy_levels", f"TẤT CẢ {len(buys)} BUY thiếu entry/tp1 → forward TP/SL không grade được (nghi record đọc sai file levels)")
                elif miss:
                    qc.warn("buy_levels", f"{len(miss)}/{len(buys)} BUY thiếu entry/tp1")
                elif buys:
                    qc.ok("buy_levels", f"{len(buys)} BUY đều có entry/tp1")
                else:
                    qc.ok("buy_levels", "run này không có BUY")

    # ── TỔNG HỢP ────────────────────────────────────────────────────────────
    errs = [c for c in qc.checks if c["severity"] == "error"]
    warns = [c for c in qc.checks if c["severity"] == "warn"]
    problems = errs + warns
    is_ok = not problems

    if is_ok:
        summary = f"✅ QC sạch — {run_date} {snap_time or ''} ({n4} mã)"
    else:
        head = f"⚠️ QC {run_date} {snap_time or ''}: {len(errs)} lỗi / {len(warns)} cảnh báo"
        bullets = "\n".join(f"• [{c['severity'].upper()}] {c['msg']}" for c in problems)
        summary = head + "\n" + bullets

    report = {
        "asof_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "asof_ict": now_ict.strftime("%Y-%m-%d %H:%M:%S"),
        "run_date": run_date,
        "snap_time": snap_time,
        "expect_date": expect_date,
        "rows_v4": n4,
        "rows_v23": n23,
        "ok": is_ok,
        "n_errors": len(errs),
        "n_warns": len(warns),
        "summary": summary,
        "problems": problems,
        "checks": qc.checks,
    }

    OUT.mkdir(parents=True, exist_ok=True)
    with (OUT / "qc_last.json").open("w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    # log ra Actions cho dễ debug
    print(summary)
    print(f"[qc] wrote {OUT / 'qc_last.json'} | ok={is_ok}")

    if FAIL_ON_ERROR and errs:
        sys.exit(1)
    sys.exit(0)


def _read_ledger_for_run(run_date, snap_time):
    """Trả list dòng ledger của ĐÚNG run này (signal_date==run_date, snap_time khớp).
    None nếu không mở được partition. [] nếu partition có nhưng không match."""
    if not run_date:
        return []
    month = run_date[:7]
    path = LEDGER_DIR / f"{month}.jsonl"
    if not path.exists():
        # thử partition mới nhất nếu tháng lệch
        cands = sorted(glob.glob(str(LEDGER_DIR / "*.jsonl")))
        if not cands:
            return None
        path = Path(cands[-1])
    rows = []
    try:
        with path.open(encoding="utf-8") as f:
            for ln in f:
                ln = ln.strip()
                if not ln:
                    continue
                try:
                    r = json.loads(ln)
                except json.JSONDecodeError:
                    continue
                if str(r.get("signal_date")) != run_date:
                    continue
                if snap_time and str(r.get("snap_time")) != snap_time:
                    continue
                rows.append(r)
    except Exception:
        return None
    return rows


if __name__ == "__main__":
    main()
