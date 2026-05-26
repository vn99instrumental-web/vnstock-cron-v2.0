"""
debug_kbs_cf.py — Diagnostic dump KBS Finance structure
========================================================
Mục đích chính: Bug Cash Flow đang 100% None
  Run này sẽ in TOÀN BỘ structure (columns, item_ids, values)
  của 4 reports cho 5 symbols thuộc các sectors khác nhau.

Sau khi chạy, gửi log ra để fix actual keys trong _kbs_lookup.

Sectors tested:
  - HPG : Industrials (steel) — confirmed có CF data trong run cũ
  - VHM : Real Estate (Vinhomes)
  - VCB : Banks (Vietcombank)
  - VRE : Real Estate retail (Vincom)
  - PVD : Oil & Gas

Cách chạy:
  - Trigger workflow .github/workflows/debug_cf.yml manually
  - Hoặc local: python debug_kbs_cf.py 2>&1 | tee debug_output.txt
"""
import os
import sys
import json
import traceback

os.environ["VNSTOCK_INTERACTIVE"] = "0"
os.environ["VNSTOCK_LANGUAGE"]    = "en"
os.environ["MPLCONFIGDIR"]        = "/home/runner/.config/matplotlib"
os.makedirs("/home/runner/.vnstock",           exist_ok=True)
os.makedirs("/home/runner/.config/matplotlib", exist_ok=True)

import pandas as pd
from vnstock_data import Finance


# Try to get version
try:
    import vnstock_data
    version = (getattr(vnstock_data, "__version__", None) or
               getattr(vnstock_data, "VERSION", None) or
               "unknown")
    print(f"vnstock_data version: {version}")
except Exception as e:
    print(f"Could not detect vnstock_data version: {e}")


# Configure pandas to show full data — không truncate
pd.set_option("display.max_rows",     200)
pd.set_option("display.max_columns",  20)
pd.set_option("display.width",        220)
pd.set_option("display.max_colwidth", 70)


SYMBOLS = [
    ("HPG", "Industrials (steel)"),
    ("VHM", "Real Estate (Vinhomes)"),
    ("VCB", "Banks (Vietcombank)"),
    ("VRE", "Real Estate retail (Vincom)"),
    ("PVD", "Oil & Gas"),
]

REPORTS = ["ratio", "income_statement", "balance_sheet", "cash_flow"]


def dump_report(symbol: str, report_name: str):
    """Dump 1 report cho 1 symbol — print full structure + summary."""
    print(f"\n--- {report_name.upper()} ---")

    try:
        fin    = Finance(source="KBS", symbol=symbol)
        method = getattr(fin, report_name)
        df     = method(period="quarter", limit=1)

        # ── Type & emptiness checks ──
        if df is None:
            print("  Result: None")
            return
        if not isinstance(df, pd.DataFrame):
            print(f"  Result type: {type(df).__name__}")
            print(f"  Repr: {df!r}"[:500])
            return
        if df.empty:
            print("  Result: empty DataFrame")
            return

        # ── Basic info ──
        print(f"  Shape: {df.shape[0]} rows × {df.shape[1]} cols")
        print(f"  Columns: {df.columns.tolist()}")

        print(f"  Dtypes:")
        for col, dtype in df.dtypes.items():
            print(f"    {col}: {dtype}")

        # ── Full DataFrame dump ──
        print(f"\n  RAW DataFrame.to_string():")
        try:
            print(df.to_string())
        except Exception as e:
            print(f"    (to_string failed: {e})")

        # ── Detailed item_id listing (KEY for fixing bug) ──
        if "item_id" in df.columns:
            period_cols = [c for c in df.columns if c not in ("item", "item_id")]
            target_col  = period_cols[-1] if period_cols else None

            print(f"\n  ALL ITEM_IDs ({len(df)} rows):")
            print(f"  Format: [idx] item_id = value_in_latest_period")
            print(f"  " + "-" * 65)

            for idx in range(len(df)):
                row     = df.iloc[idx]
                item_id = row.get("item_id", "?")
                if target_col is not None:
                    val = row.get(target_col)
                    # Format value: nan → "nan", number → use comma sep
                    if pd.isna(val):
                        val_str = "nan"
                    elif isinstance(val, (int, float)):
                        val_str = f"{val:,.0f}" if abs(val) >= 1 else f"{val}"
                    else:
                        val_str = str(val)[:50]
                else:
                    val_str = "(no period cols)"
                print(f"  [{idx:3d}] {item_id!r:55s} = {val_str}")

    except Exception as e:
        print(f"  ❌ ERROR: {type(e).__name__}: {e}")
        traceback.print_exc()


def main():
    print("=" * 75)
    print("  KBS Finance Structure Diagnostic — Cash Flow Bug Investigation")
    print("=" * 75)
    print(f"  Time: {__import__('datetime').datetime.now().isoformat()}")
    print(f"  Testing {len(SYMBOLS)} symbols × {len(REPORTS)} reports = "
          f"{len(SYMBOLS) * len(REPORTS)} API calls")

    for sym, sector in SYMBOLS:
        print(f"\n\n{'=' * 75}")
        print(f"  SYMBOL: {sym}  ({sector})")
        print(f"{'=' * 75}")

        for report in REPORTS:
            dump_report(sym, report)

    print("\n" + "=" * 75)
    print("  DONE — Send this log back để fix _kbs_lookup keys")
    print("=" * 75)


if __name__ == "__main__":
    main()
