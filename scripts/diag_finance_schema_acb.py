"""
scripts/diag_finance_schema_acb.py
==================================
Diagnostic-only. KHÔNG ghi cache, KHÔNG sửa output.

Mục tiêu: tìm vì sao Finance(KBS) trả DataFrame non-empty nhưng production
_kbs_lookup() vẫn extract PE/ROE/revenue/CFO = None.

Default symbol: ACB. Override bằng env DIAG_SYMBOL nếu cần.
Chạy qua debug.yml với input:
  scripts/diag_finance_schema_acb.py
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
from steps import step_finance_scan as prod

SYMBOL = os.environ.get("DIAG_SYMBOL", "ACB").strip().upper()
DELAY = 0.6


def pkg_version(name):
    try:
        return metadata.version(name)
    except Exception:
        return "UNKNOWN"


def safe_call(label, fn):
    print(f"\n{'=' * 90}\nCALL: {label}\n{'=' * 90}")
    try:
        df = fn()
        if df is None:
            print("RESULT: None")
            return None
        print(f"TYPE: {type(df).__name__}")
        print(f"SHAPE: {getattr(df, 'shape', None)}")
        print(f"EMPTY: {getattr(df, 'empty', None)}")
        return df
    except Exception as e:
        print(f"ERROR: {type(e).__name__}: {e}")
        return None
    finally:
        time.sleep(DELAY)


def dump_df(name, df, key_groups=None):
    print(f"\n--- DUMP {name} ---")
    if df is None:
        print("None")
        return
    if not isinstance(df, pd.DataFrame):
        print(f"Not DataFrame: {type(df)}")
        print(repr(df)[:3000])
        return
    if df.empty:
        print("EMPTY DataFrame")
        print(f"columns={list(df.columns)}")
        return

    print(f"index_type={type(df.index).__name__} index_name={df.index.name!r}")
    print(f"columns({len(df.columns)}): {list(df.columns)}")
    print("dtypes:")
    print(df.dtypes.to_string())

    for col in ("item_id", "item"):
        if col in df.columns:
            vals = df[col].dropna().astype(str).tolist()
            print(f"{col} values sample ({min(len(vals), 40)}/{len(vals)}):")
            print(vals[:40])

    print("head(12):")
    try:
        print(df.head(12).to_string())
    except Exception as e:
        print(f"head dump failed: {e}")

    print("tail(5):")
    try:
        print(df.tail(5).to_string())
    except Exception as e:
        print(f"tail dump failed: {e}")

    if key_groups:
        print("production _kbs_lookup tests:")
        for label, keys in key_groups.items():
            try:
                val = prod._kbs_lookup(df, keys)
                print(f"  {label:24s} keys={keys} -> {val!r}")
            except Exception as e:
                print(f"  {label:24s} ERROR {type(e).__name__}: {e}")


def main():
    print("=" * 90)
    print(f"FINANCE SCHEMA DIAGNOSTIC — symbol={SYMBOL}")
    print(f"python={sys.version.split()[0]}")
    for p in ("vnstock", "vnstock_data", "vnai"):
        print(f"{p}={pkg_version(p)}")
    print(f"production SCHEMA_VERSION={prod.SCHEMA_VERSION}")
    print("NOTE: diagnostic is read-only; no save_cache() call.")
    print("=" * 90)

    ratio = safe_call(
        "KBS ratio(period=quarter, limit=1)",
        lambda: Finance(source="KBS", symbol=SYMBOL).ratio(period="quarter", limit=1),
    )
    dump_df("KBS ratio", ratio, {
        "pe": ["pe_ratio"],
        "pb": ["pb_ratio"],
        "roe": ["roe", "roe_trailling"],
        "roa": ["roa_trailling", "roa"],
        "div_yield": ["dividend_yield"],
    })

    income_q = safe_call(
        "KBS income_statement(period=quarter, limit=4)",
        lambda: Finance(source="KBS", symbol=SYMBOL).income_statement(period="quarter", limit=4),
    )
    dump_df("KBS income_q", income_q, {
        "revenue": prod._REVENUE_KEYS,
        "net_profit": prod._NET_PROFIT_KEYS,
        "operating_profit": ["11_operating_profit", "operating_profit"],
    })

    balance = safe_call(
        "KBS balance_sheet(period=quarter, limit=1)",
        lambda: Finance(source="KBS", symbol=SYMBOL).balance_sheet(period="quarter", limit=1),
    )
    dump_df("KBS balance", balance, {
        "short_assets": ["a_short_term_assets"],
        "long_assets": ["b_long_term_assets"],
        "total_assets": ["total_assets"],
        "equity": ["owner_s_equity", "d_owner_s_equity", "total_equity", "equity"],
    })

    cashflow = safe_call(
        "KBS cash_flow(period=year, limit=1)",
        lambda: Finance(source="KBS", symbol=SYMBOL).cash_flow(period="year", limit=1),
    )
    dump_df("KBS cashflow_y", cashflow, {
        "cfo": prod._CFO_KEYS,
        "cfi": prod._CFI_KEYS,
        "cff": prod._CFF_KEYS,
    })

    income_y = safe_call(
        "KBS income_statement(period=year, limit=1)",
        lambda: Finance(source="KBS", symbol=SYMBOL).income_statement(period="year", limit=1),
    )
    dump_df("KBS income_y", income_y, {
        "net_profit_year": prod._NET_PROFIT_KEYS,
    })

    ratio_vci = safe_call(
        "VCI Company.ratio_summary()",
        lambda: Company(source="VCI", symbol=SYMBOL).ratio_summary(),
    )
    dump_df("VCI ratio_summary", ratio_vci)

    print("\n" + "=" * 90)
    print("PRODUCTION fetch_one() RESULT (same symbol, sequential after schema dumps)")
    print("=" * 90)
    try:
        result = prod.fetch_one(SYMBOL)
        if result is None:
            print("fetch_one -> None")
        else:
            print(f"fetch_one keys={list(result.keys())}")
            print(f"ratio={result.get('ratio')}")
            print(f"income={result.get('income')}")
            print(f"balance={result.get('balance')}")
            print(f"cashflow={result.get('cashflow')}")
            print(f"data_status={result.get('data_status')}")
            print(f"finance_score={result.get('finance_score')}")
    except Exception as e:
        print(f"fetch_one ERROR: {type(e).__name__}: {e}")

    print("\nDONE — attach this log back to ChatGPT. No files were modified by this script.")


if __name__ == "__main__":
    main()
