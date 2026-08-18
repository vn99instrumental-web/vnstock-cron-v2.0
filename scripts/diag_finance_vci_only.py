"""
scripts/diag_finance_vci_only.py
================================
Diagnostic-only. KHÔNG ghi cache, KHÔNG sửa output.

Mục tiêu: kiểm tra VCI có thể thay KBS làm nguồn finance chính hay không.
Default symbols: ACB (bank) + PNJ (normal corporate).
Override bằng env DIAG_SYMBOLS, ví dụ: ACB,PNJ,FPT,VCB.

Test:
  - Finance(source='VCI').ratio(quarter,1)
  - Finance(source='VCI').income_statement(quarter,4)
  - Finance(source='VCI').balance_sheet(quarter,1)
  - Finance(source='VCI').cash_flow(year,1)
  - Finance(source='VCI').income_statement(year,1)
  - Company(source='VCI').ratio_summary()

Chạy qua debug.yml input:
  scripts/diag_finance_vci_only.py
"""
import os
import sys
import time
from importlib import metadata

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
os.environ["VNSTOCK_INTERACTIVE"] = "0"
os.environ["VNSTOCK_LANGUAGE"] = "en"
os.environ["MPLCONFIGDIR"] = "/home/runner/.config/matplotlib"
os.makedirs("/home/runner/.vnstock", exist_ok=True)
os.makedirs("/home/runner/.config/matplotlib", exist_ok=True)

import pandas as pd
from vnstock_data import Finance, Company

SYMBOLS = [s.strip().upper() for s in os.environ.get("DIAG_SYMBOLS", "ACB,PNJ").split(",") if s.strip()]
DELAY = 0.6


def pkg_version(name):
    try:
        return metadata.version(name)
    except Exception:
        return "UNKNOWN"


def call(label, fn):
    print(f"\n{'=' * 100}\nCALL: {label}\n{'=' * 100}")
    try:
        df = fn()
        if df is None:
            print("RESULT: None")
            return None
        print(f"TYPE={type(df).__name__}")
        print(f"SHAPE={getattr(df, 'shape', None)}")
        print(f"EMPTY={getattr(df, 'empty', None)}")
        return df
    except Exception as e:
        print(f"ERROR: {type(e).__name__}: {e}")
        return None
    finally:
        time.sleep(DELAY)


def dump_df(name, df, max_rows=12):
    print(f"\n--- {name} ---")
    if df is None:
        print("None")
        return
    if not isinstance(df, pd.DataFrame):
        print(f"Not DataFrame: {type(df)}")
        print(repr(df)[:4000])
        return
    print(f"columns({len(df.columns)}): {list(df.columns)}")
    if df.empty:
        print("EMPTY DataFrame")
        return
    for col in ("id", "item_id", "item", "name", "period", "year", "quarter", "value"):
        if col in df.columns:
            vals = df[col].dropna().astype(str).tolist()
            print(f"{col} sample ({min(len(vals), 35)}/{len(vals)}): {vals[:35]}")
    print(f"head({max_rows}):")
    try:
        print(df.head(max_rows).to_string())
    except Exception as e:
        print(f"head dump failed: {e}")


def non_null_summary(df):
    if df is None or not isinstance(df, pd.DataFrame) or df.empty:
        return "EMPTY"
    try:
        counts = df.notna().sum().sort_values(ascending=False)
        top = [(str(k), int(v)) for k, v in counts.head(12).items()]
        return str(top)
    except Exception as e:
        return f"ERR {e}"


def ratio_summary_fields(df):
    if df is None or not isinstance(df, pd.DataFrame) or df.empty:
        return {}
    sort_cols = [c for c in ("year", "quarter") if c in df.columns]
    work = df.copy()
    if "ratio_type" in work.columns:
        ttm = work[work["ratio_type"] == "RATIO_TTM"]
        if not ttm.empty:
            work = ttm
    if sort_cols:
        work = work.sort_values(sort_cols, ascending=False)
    row = work.iloc[0]
    fields = [
        "pe", "pb", "roe", "roa", "dividend_yield", "gross_margin",
        "after_tax_profit_margin", "quick_ratio", "ev_to_ebitda",
        "revenue", "net_profit", "total_assets", "equity"
    ]
    out = {}
    for f in fields:
        if f in work.columns:
            v = row.get(f)
            out[f] = None if pd.isna(v) else v
    return out


def main():
    print("=" * 100)
    print("VCI-ONLY FINANCE DIAGNOSTIC")
    print(f"symbols={SYMBOLS}")
    print(f"python={sys.version.split()[0]}")
    for p in ("vnstock", "vnstock_data", "vnai"):
        print(f"{p}={pkg_version(p)}")
    print("READ-ONLY: no cache/output writes")
    print("=" * 100)

    coverage = {
        "ratio": 0,
        "income_q": 0,
        "balance_q": 0,
        "cashflow_y": 0,
        "income_y": 0,
        "ratio_summary": 0,
    }

    for sym in SYMBOLS:
        print("\n" + "#" * 100)
        print(f"SYMBOL: {sym}")
        print("#" * 100)

        calls = {
            "ratio": lambda: Finance(source="VCI", symbol=sym).ratio(period="quarter", limit=1),
            "income_q": lambda: Finance(source="VCI", symbol=sym).income_statement(period="quarter", limit=4),
            "balance_q": lambda: Finance(source="VCI", symbol=sym).balance_sheet(period="quarter", limit=1),
            "cashflow_y": lambda: Finance(source="VCI", symbol=sym).cash_flow(period="year", limit=1),
            "income_y": lambda: Finance(source="VCI", symbol=sym).income_statement(period="year", limit=1),
            "ratio_summary": lambda: Company(source="VCI", symbol=sym).ratio_summary(),
        }

        results = {}
        for label, fn in calls.items():
            df = call(f"{sym} / VCI / {label}", fn)
            results[label] = df
            if isinstance(df, pd.DataFrame) and not df.empty:
                coverage[label] += 1
            dump_df(f"{sym} {label}", df)
            print(f"non-null summary: {non_null_summary(df)}")
            if label == "ratio_summary":
                print(f"ratio_summary key fields: {ratio_summary_fields(df)}")

        print("\n--- SYMBOL DECISION ---")
        statement_ok = all(
            isinstance(results[k], pd.DataFrame) and not results[k].empty
            for k in ("income_q", "balance_q", "cashflow_y")
        )
        ratio_ok = (
            isinstance(results["ratio_summary"], pd.DataFrame)
            and not results["ratio_summary"].empty
        )
        print(f"ratio_summary_available={ratio_ok}")
        print(f"all_statement_apis_available={statement_ok}")
        if ratio_ok and statement_ok:
            print("VCI_ONLY_CANDIDATE=YES (subject to field/parser validation)")
        elif ratio_ok:
            print("VCI_ONLY_CANDIDATE=NO — ratio works but one or more statement APIs are missing")
        else:
            print("VCI_ONLY_CANDIDATE=NO — ratio_summary also unavailable")

    n = len(SYMBOLS)
    print("\n" + "=" * 100)
    print("COVERAGE SUMMARY")
    for k, v in coverage.items():
        print(f"{k:14s}: {v}/{n}")
    print("=" * 100)
    print("Decision rule:")
    print("- VCI ratio_summary 100% + income/balance/cashflow 100% => can consider VCI-only.")
    print("- ratio_summary works but statements are empty => use VCI for ratio only; keep another source for statements.")
    print("DONE — attach this log back to ChatGPT.")


if __name__ == "__main__":
    main()
