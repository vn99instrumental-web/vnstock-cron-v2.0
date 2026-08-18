"""
scripts/diag_finance_130.py — Audit finance pipeline trên toàn VN100 + HNX30
============================================================================
Mục tiêu:
  1) Lấy đúng universe VN100 + HNX30 (~130 mã), dedupe.
  2) Audit cache hiện tại: valid / partial / non_stock / missing.
  3) Chạy production fetch_one() với concurrency = MAX_WORKERS của step_finance_scan.
  4) Với mọi mã production trả non_stock/None, RETEST TUẦN TỰ các endpoint raw:
       - KBS ratio(quarter,1)
       - KBS income_statement(quarter,4)
       - KBS cash_flow(year,1)
       - VCI Company.ratio_summary()
     để phân biệt:
       a) transient/rate-limit/concurrency (retest có data)
       b) source thật sự empty (retest vẫn empty)
  5) Không ghi đè finance/cache.json, không sửa production output.

Chạy:
  python scripts/diag_finance_130.py

Có thể override workers:
  DIAG_WORKERS=1 python scripts/diag_finance_130.py
  DIAG_WORKERS=4 python scripts/diag_finance_130.py

Output chỉ ghi file diagnostic:
  output/diag_finance_130.json
  output/diag_finance_130.csv
"""

import os
import sys
import json
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

os.environ["VNSTOCK_INTERACTIVE"] = "0"
os.environ["VNSTOCK_LANGUAGE"] = "en"
os.environ["MPLCONFIGDIR"] = "/home/runner/.config/matplotlib"
os.makedirs("/home/runner/.vnstock", exist_ok=True)
os.makedirs("/home/runner/.config/matplotlib", exist_ok=True)

import pandas as pd
from vnstock_data import Finance, Company, Listing

from steps import step_finance_scan as prod
from utils.cache import load_json


WORKERS = int(os.environ.get("DIAG_WORKERS", str(prod.MAX_WORKERS)))
OUT_JSON = "output/diag_finance_130.json"
OUT_CSV = "output/diag_finance_130.csv"


def _shape(df):
    if df is None:
        return "ERR"
    try:
        if getattr(df, "empty", True):
            return "EMPTY"
        return f"{df.shape[0]}x{df.shape[1]}"
    except Exception:
        return "?"


def _try(label, fn):
    t0 = time.time()
    try:
        df = fn()
        return {
            "label": label,
            "shape": _shape(df),
            "error": None,
            "sec": round(time.time() - t0, 2),
        }
    except Exception as e:
        return {
            "label": label,
            "shape": "ERR",
            "error": f"{type(e).__name__}: {str(e)[:300]}",
            "sec": round(time.time() - t0, 2),
        }


def _members(group):
    try:
        res = Listing(source="VCI").symbols_by_group(group=group)
    except Exception as e:
        print(f"ERROR Listing {group}: {type(e).__name__}: {e}")
        return []

    if res is None:
        return []
    if isinstance(res, pd.Series):
        vals = res.dropna().astype(str).tolist()
    elif isinstance(res, pd.DataFrame):
        if res.empty:
            return []
        col = "symbol" if "symbol" in res.columns else res.columns[0]
        vals = res[col].dropna().astype(str).tolist()
    else:
        vals = [str(x) for x in list(res)]
    return [x.strip().upper() for x in vals if str(x).strip()]


def build_universe():
    seen = set()
    out = []
    by_group = {}
    for group in ("VN100", "HNX30"):
        syms = _members(group)
        by_group[group] = syms
        for s in syms:
            if s not in seen:
                seen.add(s)
                out.append(s)
    print(f"Universe: VN100={len(by_group.get('VN100', []))}, "
          f"HNX30={len(by_group.get('HNX30', []))}, dedupe={len(out)}")
    return out, by_group


def cache_status(sym, cache):
    e = cache.get(sym)
    if not e:
        return "missing"
    if e.get("non_stock"):
        return "non_stock"
    if "finance_score" not in e:
        return "invalid_no_score"
    st = e.get("data_status") or {}
    return "partial" if st.get("incomplete") else "valid"


def prod_fetch(sym):
    t0 = time.time()
    try:
        r = prod.fetch_one(sym)
        sec = round(time.time() - t0, 2)
        if not r:
            return sym, None, "none", None, sec
        if r.get("non_stock"):
            return sym, r, "non_stock", None, sec
        st = r.get("data_status") or {}
        status = "partial" if st.get("incomplete") else "valid"
        return sym, r, status, None, sec
    except Exception as e:
        return sym, None, "error", f"{type(e).__name__}: {str(e)[:300]}", round(time.time() - t0, 2)


def raw_retest(sym):
    """Retest tuần tự, có pause để loại bớt ảnh hưởng concurrency/rate-limit."""
    calls = [
        ("kbs_ratio", lambda: Finance(source="KBS", symbol=sym).ratio(period="quarter", limit=1)),
        ("kbs_income_q", lambda: Finance(source="KBS", symbol=sym).income_statement(period="quarter", limit=4)),
        ("kbs_cashflow_y", lambda: Finance(source="KBS", symbol=sym).cash_flow(period="year", limit=1)),
        ("vci_ratio_summary", lambda: Company(source="VCI", symbol=sym).ratio_summary()),
    ]
    out = {}
    for label, fn in calls:
        x = _try(label, fn)
        out[label] = x
        time.sleep(0.6)
    any_data = any(v["shape"] not in ("EMPTY", "ERR", "?") for v in out.values())
    all_empty_or_err = all(v["shape"] in ("EMPTY", "ERR", "?") for v in out.values())
    return out, any_data, all_empty_or_err


def main():
    started = datetime.now().isoformat()
    print("=" * 90)
    print("DIAG FINANCE 130 — production-like fetch + sequential retest failures")
    print(f"workers={WORKERS}")
    print("=" * 90)

    universe, groups = build_universe()
    if not universe:
        raise SystemExit("Universe empty — abort")

    cache_raw = load_json("finance/cache.json") or {}
    cache = cache_raw.get("symbols", cache_raw) if isinstance(cache_raw, dict) else {}

    rows = []
    cache_counts = {}
    for sym in universe:
        cs = cache_status(sym, cache)
        cache_counts[cs] = cache_counts.get(cs, 0) + 1
    print(f"CACHE STATUS: {cache_counts}")

    print("\nPHASE 1 — production fetch_one() across 130 symbols")
    results = {}
    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        futs = {ex.submit(prod_fetch, sym): sym for sym in universe}
        done = 0
        for fut in as_completed(futs):
            sym, data, status, err, sec = fut.result()
            results[sym] = (data, status, err, sec)
            done += 1
            if done % 10 == 0 or status in ("non_stock", "none", "error"):
                print(f"  {done:3d}/{len(universe)} {sym:5s} status={status:10s} sec={sec}")

    phase1_counts = {}
    failures = []
    for sym in universe:
        data, status, err, sec = results.get(sym, (None, "missing_result", None, None))
        phase1_counts[status] = phase1_counts.get(status, 0) + 1
        if status in ("non_stock", "none", "error", "missing_result"):
            failures.append(sym)

    print(f"PHASE 1 STATUS: {phase1_counts}")
    print(f"Need sequential retest: {len(failures)} symbols")

    print("\nPHASE 2 — sequential raw retest only failed/non_stock symbols")
    retests = {}
    transient_recovered = []
    still_empty = []
    for i, sym in enumerate(failures, 1):
        print(f"  retest {i:3d}/{len(failures)} {sym}")
        detail, any_data, all_empty = raw_retest(sym)
        retests[sym] = detail
        if any_data:
            transient_recovered.append(sym)
        elif all_empty:
            still_empty.append(sym)
        time.sleep(0.8)

    for sym in universe:
        data, status, err, sec = results.get(sym, (None, "missing_result", None, None))
        old = cache.get(sym) or {}
        st = (data or {}).get("data_status") or {}
        fs = (data or {}).get("finance_score") or {}
        rt = retests.get(sym) or {}

        row = {
            "symbol": sym,
            "in_vn100": sym in groups.get("VN100", []),
            "in_hnx30": sym in groups.get("HNX30", []),
            "cache_status_before": cache_status(sym, cache),
            "cache_non_stock_before": bool(old.get("non_stock")),
            "cache_fetched_at": old.get("fetched_at"),
            "prod_status": status,
            "prod_sec": sec,
            "prod_error": err,
            "ratio_source": st.get("ratio_source"),
            "cf_available": st.get("cf_available"),
            "growth_available": st.get("growth_available"),
            "incomplete": st.get("incomplete"),
            "score_fundamental": fs.get("fundamental"),
            "score_cashflow": fs.get("cashflow"),
            "score_growth": fs.get("growth"),
            "retest_any_data": sym in transient_recovered,
            "retest_still_empty": sym in still_empty,
            "retest_kbs_ratio": (rt.get("kbs_ratio") or {}).get("shape"),
            "retest_kbs_income_q": (rt.get("kbs_income_q") or {}).get("shape"),
            "retest_kbs_cashflow_y": (rt.get("kbs_cashflow_y") or {}).get("shape"),
            "retest_vci_ratio_summary": (rt.get("vci_ratio_summary") or {}).get("shape"),
        }
        rows.append(row)

    summary = {
        "started_at": started,
        "finished_at": datetime.now().isoformat(),
        "workers": WORKERS,
        "universe_count": len(universe),
        "vn100_count": len(groups.get("VN100", [])),
        "hnx30_count": len(groups.get("HNX30", [])),
        "cache_status_before": cache_counts,
        "phase1_status": phase1_counts,
        "phase1_failure_symbols": failures,
        "sequential_recovered_count": len(transient_recovered),
        "sequential_recovered_symbols": transient_recovered,
        "still_empty_count": len(still_empty),
        "still_empty_symbols": still_empty,
        "interpretation": {
            "recovered_on_sequential_retest": "Strong evidence of transient API / concurrency / rate-limit issue",
            "still_empty_after_sequential_retest": "Likely source coverage/outage/schema issue; inspect endpoint errors",
            "cache_non_stock_but_prod_valid": "Confirms stale false non_stock classification in cache",
        },
    }

    os.makedirs("output", exist_ok=True)
    with open(OUT_JSON, "w", encoding="utf-8") as f:
        json.dump({"summary": summary, "rows": rows, "retests": retests}, f,
                  ensure_ascii=False, indent=2, default=str)
    pd.DataFrame(rows).to_csv(OUT_CSV, index=False, encoding="utf-8-sig")

    false_non_stock = [r["symbol"] for r in rows
                       if r["cache_non_stock_before"] and r["prod_status"] in ("valid", "partial")]

    print("\n" + "=" * 90)
    print("FINAL SUMMARY")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"FALSE NON_STOCK CONFIRMED (cache non_stock -> prod now valid/partial): {len(false_non_stock)}")
    if false_non_stock:
        print(",".join(false_non_stock))
    print(f"Saved: {OUT_JSON}")
    print(f"Saved: {OUT_CSV}")
    print("NOTE: diagnostic does NOT modify finance/cache.json")
    print("=" * 90)


if __name__ == "__main__":
    main()
