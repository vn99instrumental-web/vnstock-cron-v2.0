#!/usr/bin/env python3
"""
export_ohlc_to_supabase.py — [E7/ADR-010-B] Backfill OHLC daily thật → bảng v4_ohlc.

Nguồn: vnstock (VCI), interval 1D — GIỐNG fetch_ohlcv của v2f_step_eval_predictions.py.
Danh sách mã: các symbol DISTINCT trong ledger predictions_v4 (không cần gọi API để lấy list).
Ghi: upsert idempotent v4_ohlc (unique symbol,date) — chạy lại không nhân đôi.

Chạy trên GH Actions (cần vnstock env + VNSTOCK_API_KEY). Ngoài giờ vẫn chạy được
(lấy lịch sử daily). Env: SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY, VNSTOCK_API_KEY[/DEVICE_ID].

  python3 scripts/export_ohlc_to_supabase.py                 # ~400 ngày, mọi mã trong ledger
  python3 scripts/export_ohlc_to_supabase.py --days 250 --symbols HPG REE
  python3 scripts/export_ohlc_to_supabase.py --dry-run       # chỉ liệt kê mã + số bản ghi
"""
from __future__ import annotations

import argparse
import glob
import json
import logging
import os
import sys
import time
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from sync_supabase import Supabase  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
PRED_GLOB = str(ROOT / "output/history/v2f_predictions_v4/*.jsonl")
THROTTLE = 0.4  # giây giữa các mã (tránh rate limit VCI)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("export_ohlc")


def _f(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def symbols_from_ledger() -> list[str]:
    seen = set()
    for fp in glob.glob(PRED_GLOB):
        with open(fp, encoding="utf-8") as fh:
            for ln in fh:
                ln = ln.strip()
                if not ln:
                    continue
                try:
                    s = json.loads(ln).get("symbol")
                    if s:
                        seen.add(str(s).upper())
                except json.JSONDecodeError:
                    pass
    return sorted(seen)


def fetch_ohlcv(symbol: str, start: str, end: str) -> list[dict]:
    """Daily OHLC từ vnstock VCI (kế thừa logic v2f_step_eval_predictions.fetch_ohlcv)."""
    import pandas as pd
    from vnstock_data import Quote

    for attempt in range(4):
        try:
            df = Quote(source="VCI", symbol=symbol).history(start=start, end=end, interval="1D")
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
                "symbol": symbol,
                "date": r["time"].strftime("%Y-%m-%d"),
                "open": _f(r.get("open")),
                "high": _f(r.get("high")),
                "low": _f(r.get("low")),
                "close": _f(r.get("close")),
                "volume": _f(r.get("volume")),
            } for _, r in df.iterrows()]
        except Exception as e:  # noqa: BLE001
            msg = str(e).lower()
            is_rate = any(k in msg for k in ("rate limit", "giới hạn", "300/300", "429"))
            if is_rate and attempt < 3:
                wait = 15 * (attempt + 1)
                log.warning("  %s: rate limit — chờ %ds (lần %d/4)", symbol, wait, attempt + 1)
                time.sleep(wait)
                continue
            log.warning("  %s: fetch lỗi — %s", symbol, e)
            return []
    return []


def main() -> int:
    ap = argparse.ArgumentParser(description="Backfill OHLC daily → v4_ohlc.")
    ap.add_argument("--days", type=int, default=900, help="số ngày lịch sử (mặc định 900 ~ đủ EMA200 nếu nguồn cho)")
    ap.add_argument("--symbols", nargs="*", help="lọc mã (mặc định: mọi mã trong ledger)")
    ap.add_argument("--limit", type=int, default=0, help="giới hạn số mã (0 = tất cả)")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    end = date.today().strftime("%Y-%m-%d")
    start = (date.today() - timedelta(days=args.days)).strftime("%Y-%m-%d")
    symbols = [s.upper() for s in args.symbols] if args.symbols else symbols_from_ledger()
    if args.limit:
        symbols = symbols[: args.limit]
    log.info("OHLC %s → %s | %d mã", start, end, len(symbols))

    if args.dry_run:
        log.info("DRY-RUN: %s", ", ".join(symbols[:30]) + (" …" if len(symbols) > 30 else ""))
        return 0

    url = os.environ.get("SUPABASE_URL") or os.environ.get("NEXT_PUBLIC_SUPABASE_URL")
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
    if not url or not key:
        log.error("Thiếu SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY.")
        return 2
    sb = Supabase(url, key)

    total_rows = 0
    ok = 0
    for i, sym in enumerate(symbols, 1):
        bars = fetch_ohlcv(sym, start, end)
        if bars:
            sb.upsert("v4_ohlc", bars, on_conflict="symbol,date")
            total_rows += len(bars)
            ok += 1
        log.info("[%d/%d] %s: %d bars", i, len(symbols), sym, len(bars))
        time.sleep(THROTTLE)

    log.info("=== OHLC DONE === %d/%d mã có data, %d bars", ok, len(symbols), total_rows)
    return 0


if __name__ == "__main__":
    sys.exit(main())
