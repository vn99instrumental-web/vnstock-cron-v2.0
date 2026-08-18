"""
scripts/diag_step_finance_vci_validate.py
=========================================
READ-ONLY vs production cache. Validates a proven parser fix in two phases:

Phase 1: fetch_one() for 5 representative symbols.
Phase 2: ONLY if all 5 return usable finance data, run full candidate universe (~150).

This script monkey-patches candidate._long_rows at runtime to avoid pandas
Categorical.map(tuple) -> MultiIndex bug. It writes ONLY:
  output/finance/cache_vci_validation.json
Production output/finance/cache.json is untouched.

Run via debug.yml input:
  scripts/diag_step_finance_vci_validate.py
"""

import os
import sys
import traceback

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
os.environ["VNSTOCK_INTERACTIVE"] = "0"
os.environ["VNSTOCK_LANGUAGE"] = "en"
os.environ["MPLCONFIGDIR"] = "/home/runner/.config/matplotlib"

import pandas as pd
from steps import step_finance_scan_vci as cand

SAMPLE = ["ACB", "PNJ", "SSI", "FPT", "HPG"]


def fixed_long_rows(df, ids):
    """
    Same contract as candidate._long_rows, but avoids Series.map() on a
    Categorical period column when mapper returns tuples. Pandas may create a
    MultiIndex for mapped categories and then raise:
      NotImplementedError: isna is not defined for MultiIndex

    Fix: convert period values to plain Python objects, derive numeric year/q
    columns, and sort by those scalar columns.
    """
    if df is None or not isinstance(df, pd.DataFrame) or df.empty:
        return pd.DataFrame()
    if not {"id", "value"}.issubset(df.columns):
        return pd.DataFrame()

    work = df[df["id"].astype(str).isin(ids)].copy()
    if work.empty:
        return work

    if "period" not in work.columns:
        work["period"] = ""

    periods = work["period"].astype(object).tolist()
    keys = [cand._period_key(p) for p in periods]
    work["_period_year"] = [k[0] for k in keys]
    work["_period_quarter"] = [k[1] for k in keys]
    work = work.sort_values(
        ["_period_year", "_period_quarter"],
        ascending=[False, False],
    )
    return work


# Runtime patch only; repository candidate remains unchanged until validation passes.
cand._long_rows = fixed_long_rows
cand.CACHE_FILE = "finance/cache_vci_validation.json"


def usable(result):
    if not isinstance(result, dict):
        return False
    r = result.get("ratio") or {}
    i = result.get("income") or {}
    b = result.get("balance") or {}
    c = result.get("cashflow") or {}
    return any(v is not None for v in (
        r.get("pe"), r.get("roe"), i.get("net_profit"),
        b.get("total_assets"), c.get("cf_operating"),
    ))


def main():
    print("=" * 110)
    print("VCI CANDIDATE STAGED VALIDATION")
    print("Parser fix: categorical period -> scalar year/quarter sort columns")
    print("Production cache untouched")
    print("=" * 110)

    print("\nPHASE 1 — 5 SYMBOLS")
    passed = []
    failed = []

    for sym in SAMPLE:
        try:
            result = cand.fetch_one(sym)
            if not usable(result):
                failed.append(sym)
                print(f"❌ {sym}: fetch_one returned no usable finance fields")
                continue

            passed.append(sym)
            print(
                f"✅ {sym} | "
                f"PE={(result.get('ratio') or {}).get('pe')} "
                f"ROE={(result.get('ratio') or {}).get('roe')} "
                f"REV={(result.get('income') or {}).get('revenue')} "
                f"NP={(result.get('income') or {}).get('net_profit')} "
                f"ASSET={(result.get('balance') or {}).get('total_assets')} "
                f"EQ={(result.get('balance') or {}).get('equity')} "
                f"CFO={(result.get('cashflow') or {}).get('cf_operating')} "
                f"score={(result.get('finance_score') or {}).get('total')} "
                f"status={result.get('data_status')}"
            )
        except Exception as e:
            failed.append(sym)
            print(f"❌ {sym}: {type(e).__name__}: {e}")
            traceback.print_exc()

    print(f"\nPHASE 1 RESULT: passed={len(passed)}/5 {passed}; failed={failed}")

    if failed:
        print("STOP: Phase 1 not clean. Full 150 will NOT run.")
        return

    print("\n" + "=" * 110)
    print("PHASE 2 — FULL CANDIDATE UNIVERSE")
    print("=" * 110)

    try:
        cache = cand.run()
    except Exception as e:
        print(f"FULL RUN FAIL: {type(e).__name__}: {e}")
        traceback.print_exc()
        return

    print(f"FULL RUN cache entries={len(cache) if isinstance(cache, dict) else 'N/A'}")

    # Core quality summary from resulting validation cache in memory.
    universe_good = 0
    complete = 0
    with_cfo = 0
    with_equity = 0
    with_growth = 0
    for sym, entry in (cache or {}).items():
        if not isinstance(entry, dict) or entry.get("non_stock"):
            continue
        if entry.get("finance_score") is not None:
            universe_good += 1
        ds = entry.get("data_status") or {}
        if not ds.get("incomplete", True):
            complete += 1
        if (entry.get("cashflow") or {}).get("cf_operating") is not None:
            with_cfo += 1
        if (entry.get("balance") or {}).get("equity") is not None:
            with_equity += 1
        inc = entry.get("income") or {}
        if inc.get("rev_growth_qoq") is not None or inc.get("profit_growth_qoq") is not None:
            with_growth += 1

    print("\nVALIDATION CACHE QUALITY (all cached entries, not only current universe):")
    print(f"  finance_score entries = {universe_good}")
    print(f"  complete             = {complete}")
    print(f"  with CFO             = {with_cfo}")
    print(f"  with Equity          = {with_equity}")
    print(f"  with Growth          = {with_growth}")
    print("Validation file: output/finance/cache_vci_validation.json")
    print("DONE")


if __name__ == "__main__":
    main()
