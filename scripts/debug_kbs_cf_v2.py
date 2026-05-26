"""
debug_kbs_cf_v2.py — Cash Flow source/config search
====================================================
Bug đã xác định: KBS cash_flow(period="quarter", limit=1) trả về
  DataFrame 2 cols [item, item_id] — THIẾU period column.

V2 này test multiple combinations để tìm config work:
  - KBS với các period/limit khác nhau
  - VCI source (có thể work)
  - TCBS source (fallback)

Sau khi chạy: pick variant nào có period column + values → fix
  step_finance_scan dùng config đó.
"""
import os
import sys
import traceback

os.environ["VNSTOCK_INTERACTIVE"] = "0"
os.environ["VNSTOCK_LANGUAGE"]    = "en"
os.environ["MPLCONFIGDIR"]        = "/home/runner/.config/matplotlib"
os.makedirs("/home/runner/.vnstock",           exist_ok=True)
os.makedirs("/home/runner/.config/matplotlib", exist_ok=True)

import pandas as pd
from vnstock_data import Finance

try:
    import vnstock_data
    version = (getattr(vnstock_data, "__version__", None) or
               getattr(vnstock_data, "VERSION", None) or "unknown")
    print(f"vnstock_data version: {version}")
except Exception:
    pass

pd.set_option("display.max_rows",     50)
pd.set_option("display.max_columns",  15)
pd.set_option("display.width",        220)
pd.set_option("display.max_colwidth", 60)


# 2 symbols đại diện: industrials + bank
SYMBOLS = ["HPG", "VCB"]

# Test variants: (label, source, kwargs)
VARIANTS = [
    # KBS variations
    ("KBS quarter limit=1 (baseline broken)",
        "KBS", {"period": "quarter", "limit": 1}),
    ("KBS quarter limit=4",
        "KBS", {"period": "quarter", "limit": 4}),
    ("KBS quarter limit=8",
        "KBS", {"period": "quarter", "limit": 8}),
    ("KBS quarter (no limit)",
        "KBS", {"period": "quarter"}),
    ("KBS year limit=1",
        "KBS", {"period": "year", "limit": 1}),
    ("KBS year limit=4",
        "KBS", {"period": "year", "limit": 4}),
    ("KBS no args",
        "KBS", {}),
    # VCI source
    ("VCI quarter limit=1",
        "VCI", {"period": "quarter", "limit": 1}),
    ("VCI quarter limit=4",
        "VCI", {"period": "quarter", "limit": 4}),
    ("VCI year limit=1",
        "VCI", {"period": "year", "limit": 1}),
    # TCBS fallback
    ("TCBS quarter limit=1",
        "TCBS", {"period": "quarter", "limit": 1}),
    ("TCBS year limit=1",
        "TCBS", {"period": "year", "limit": 1}),
]


def test_variant(symbol: str, label: str, source: str, kwargs: dict):
    """Run 1 variant and report findings."""
    prefix = f"  [{label:42s}]"

    try:
        fin = Finance(source=source, symbol=symbol)
        df  = fin.cash_flow(**kwargs)

        if df is None:
            print(f"{prefix} → None")
            return

        if not isinstance(df, pd.DataFrame):
            print(f"{prefix} → {type(df).__name__}: {str(df)[:80]}")
            return

        if df.empty:
            print(f"{prefix} → empty")
            return

        cols     = df.columns.tolist()
        non_meta = [c for c in cols if c not in ("item", "item_id")]
        shape    = df.shape

        # Detect if has data
        has_data = len(non_meta) > 0

        status = "✅ HAS DATA" if has_data else "❌ NO DATA"
        print(f"{prefix} → {shape[0]}r × {shape[1]}c, "
              f"period_cols={non_meta}, {status}")

        # If has data, show 3 key cash flow values
        if has_data:
            target_col = non_meta[-1]
            key_items = [
                ("operating_cash_flow",
                    ["operating_cash_flow",
                     "net_cash_flows_from_operating_activities",
                     "i_cash_flows_from_operating_activities"]),
                ("investing_cash_flow",
                    ["investing_cash_flow",
                     "net_cash_flows_from_investing_activities",
                     "ii_cash_flows_from_investing_activities"]),
                ("financing_cash_flow",
                    ["financing_cash_flow",
                     "net_cash_flows_from_financing_activities",
                     "iii_cash_flows_from_financing_activities"]),
            ]

            # idx by item_id (or first column if no item_id)
            idx_col = "item_id" if "item_id" in df.columns else cols[0]
            try:
                df_idx = df.set_index(idx_col)[target_col]
                if isinstance(df_idx, pd.DataFrame):
                    df_idx = df_idx.iloc[:, 0]

                print(f"    Values for {target_col}:")
                for label_name, keys in key_items:
                    found = None
                    for k in keys:
                        if k in df_idx.index:
                            v = df_idx[k]
                            if pd.notna(v):
                                found = (k, v)
                                break
                    if found:
                        k, v = found
                        v_str = f"{v:,.0f}" if isinstance(v, (int, float)) and abs(v) >= 1 else str(v)
                        print(f"      {label_name:24s}: {k!r} = {v_str}")
                    else:
                        # Print all available item_ids if not found (for VCI long-form)
                        print(f"      {label_name:24s}: NOT FOUND in {len(df_idx)} items")
            except Exception as e:
                print(f"    [value lookup failed: {e}]")

            # Also dump full column structure if shape differs from KBS wide-form
            if len(non_meta) > 1 or cols != ['item', 'item_id'] + non_meta:
                print(f"    All columns: {cols}")
                # For VCI/TCBS that may use long-form: show sample rows
                if "item_id" not in df.columns:
                    print(f"    Sample rows (first 3):")
                    print(df.head(3).to_string())

    except Exception as e:
        print(f"{prefix} → ❌ ERROR: {type(e).__name__}: {e}")


def main():
    print("=" * 75)
    print("  Cash Flow Source/Config Search")
    print("=" * 75)

    for sym in SYMBOLS:
        print(f"\n{'=' * 75}")
        print(f"  SYMBOL: {sym}")
        print(f"{'=' * 75}")

        for label, source, kwargs in VARIANTS:
            test_variant(sym, label, source, kwargs)

    print("\n" + "=" * 75)
    print("  DONE — Look for '✅ HAS DATA' lines to find working config")
    print("=" * 75)


if __name__ == "__main__":
    main()
