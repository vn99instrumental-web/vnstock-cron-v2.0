"""
scripts/diag_step_finance_vci_5.py
==================================
READ-ONLY diagnostic for steps/step_finance_scan_vci.py.

Purpose:
  - Reproduce candidate parser error on exactly 5 representative symbols.
  - Print FULL traceback and stage checkpoints.
  - No cache/output writes.

Symbols:
  ACB = bank
  PNJ = normal corporate / jewelry
  SSI = securities
  FPT = technology
  HPG = industrial/materials

Run via debug.yml input:
  scripts/diag_step_finance_vci_5.py
"""

import os
import sys
import time
import traceback

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
os.environ["VNSTOCK_INTERACTIVE"] = "0"
os.environ["VNSTOCK_LANGUAGE"] = "en"
os.environ["MPLCONFIGDIR"] = "/home/runner/.config/matplotlib"
os.makedirs("/home/runner/.vnstock", exist_ok=True)
os.makedirs("/home/runner/.config/matplotlib", exist_ok=True)

import pandas as pd
from vnstock_data import Finance, Company
from steps import step_finance_scan_vci as cand

SYMBOLS = ["ACB", "PNJ", "SSI", "FPT", "HPG"]
DELAY = 0.5


def meta(label, obj):
    print(f"\n[{label}]")
    print(f"  type={type(obj).__name__}")
    if isinstance(obj, pd.DataFrame):
        print(f"  shape={obj.shape} empty={obj.empty}")
        print(f"  columns_type={type(obj.columns).__name__}")
        print(f"  index_type={type(obj.index).__name__}")
        print(f"  columns={list(obj.columns)[:80]}")
        print(f"  duplicated_columns={bool(obj.columns.duplicated().any())}")
        if isinstance(obj.columns, pd.MultiIndex):
            print(f"  COLUMN MULTIINDEX levels={obj.columns.nlevels}")
        if isinstance(obj.index, pd.MultiIndex):
            print(f"  INDEX MULTIINDEX levels={obj.index.nlevels}")
    elif obj is not None:
        print(f"  repr={repr(obj)[:1000]}")


def stage(label, fn):
    print(f"\n--- STAGE: {label} ---")
    try:
        out = fn()
        print(f"PASS: {label}")
        meta(label, out)
        return out, None
    except Exception as e:
        print(f"FAIL: {label}: {type(e).__name__}: {e}")
        traceback.print_exc()
        return None, e
    finally:
        time.sleep(DELAY)


def inspect_ratio(sym):
    df, err = stage(
        f"{sym} raw Company(VCI).ratio_summary",
        lambda: Company(source="VCI", symbol=sym).ratio_summary(),
    )
    if err or df is None:
        return

    stage(f"{sym} cand._fetch_ratio_summary", lambda: cand._fetch_ratio_summary(sym))

    # Isolate ratio-summary transforms one by one.
    def ratio_steps():
        work = df.copy()
        print(f"ratio columns type before={type(work.columns).__name__}")
        print(f"contains ratio_type? {'ratio_type' in work.columns}")
        if "ratio_type" in work.columns:
            print("checkpoint ratio_type filter")
            ttm = work[work["ratio_type"] == "RATIO_TTM"]
            print(f"ttm shape={ttm.shape}")
            if not ttm.empty:
                work = ttm
        sort_cols = [c for c in ("year", "quarter") if c in work.columns]
        print(f"checkpoint sort_cols={sort_cols}")
        if sort_cols:
            work = work.sort_values(sort_cols, ascending=False)
        print("checkpoint iloc[0]")
        row = work.iloc[0]
        print(f"row type={type(row).__name__} index_type={type(row.index).__name__}")
        for col in ("year", "quarter", "pe", "pb", "roe", "roa"):
            if col in work.columns:
                v = row.get(col)
                print(f"  row[{col}] type={type(v).__name__} repr={repr(v)[:300]}")
        return work

    stage(f"{sym} manual ratio transform", ratio_steps)


def inspect_long(sym, api_name, df, aliases):
    if df is None:
        return

    def check_columns():
        print(f"required id/value present? { {'id', 'value'}.issubset(df.columns) }")
        print(f"'period' present? {'period' in df.columns}")
        return df

    _, e = stage(f"{sym} {api_name} column-contract", check_columns)
    if e:
        return

    for label, ids in aliases.items():
        stage(
            f"{sym} {api_name} _long_rows {label}",
            lambda ids=ids: cand._long_rows(df, ids),
        )
        stage(
            f"{sym} {api_name} _long_lookup {label}",
            lambda ids=ids: cand._long_lookup(df, ids),
        )


def inspect_symbol(sym):
    print("\n" + "#" * 110)
    print(f"SYMBOL {sym}")
    print("#" * 110)

    inspect_ratio(sym)

    iq, _ = stage(
        f"{sym} raw VCI income_q",
        lambda: Finance(source="VCI", symbol=sym).income_statement(period="quarter", limit=8),
    )
    inspect_long(sym, "income_q", iq, {
        "revenue": cand._REVENUE_IDS,
        "net_profit": cand._NET_PROFIT_IDS,
        "gross_profit": cand._GROSS_PROFIT_IDS,
    })
    if iq is not None:
        stage(f"{sym} income revenue qoq", lambda: cand._qoq_growth(iq, cand._REVENUE_IDS))
        stage(f"{sym} income revenue yoy", lambda: cand._yoy_growth(iq, cand._REVENUE_IDS))
        stage(f"{sym} income profit qoq", lambda: cand._qoq_growth(iq, cand._NET_PROFIT_IDS))

    bs, _ = stage(
        f"{sym} raw VCI balance_q",
        lambda: Finance(source="VCI", symbol=sym).balance_sheet(period="quarter", limit=1),
    )
    inspect_long(sym, "balance_q", bs, {
        "total_assets": cand._TOTAL_ASSETS_IDS,
        "equity": cand._EQUITY_IDS,
        "total_liab": cand._TOTAL_LIAB_IDS,
    })

    cf, _ = stage(
        f"{sym} raw VCI cashflow_y",
        lambda: Finance(source="VCI", symbol=sym).cash_flow(period="year", limit=2),
    )
    inspect_long(sym, "cashflow_y", cf, {
        "cfo": cand._CFO_IDS,
        "cfi": cand._CFI_IDS,
        "cff": cand._CFF_IDS,
    })

    iy, _ = stage(
        f"{sym} raw VCI income_y",
        lambda: Finance(source="VCI", symbol=sym).income_statement(period="year", limit=2),
    )
    inspect_long(sym, "income_y", iy, {
        "net_profit": cand._NET_PROFIT_IDS,
    })

    print(f"\n=== FINAL CANDIDATE fetch_one({sym}) ===")
    try:
        result = cand.fetch_one(sym)
        print(f"fetch_one returned type={type(result).__name__}")
        if result is not None:
            print(f"ratio={result.get('ratio')}")
            print(f"income={result.get('income')}")
            print(f"balance={result.get('balance')}")
            print(f"cashflow={result.get('cashflow')}")
            print(f"status={result.get('data_status')}")
            print(f"score={result.get('finance_score')}")
    except Exception as e:
        print(f"FINAL FAIL {sym}: {type(e).__name__}: {e}")
        traceback.print_exc()


def main():
    print("=" * 110)
    print("5-SYMBOL VCI CANDIDATE TRACEBACK DIAGNOSTIC")
    print(f"symbols={SYMBOLS}")
    print("READ-ONLY: no save_cache(), no output writes")
    print("=" * 110)

    for sym in SYMBOLS:
        inspect_symbol(sym)

    print("\nDONE — attach log to ChatGPT before running full 150.")


if __name__ == "__main__":
    main()
