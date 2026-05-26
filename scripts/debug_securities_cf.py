"""
debug_securities_cf.py — Diagnostic Bug #8
============================================
Bug đã xác định: 16/143 symbols có CFO=None sau v5 fix.
Pattern: các symbols này đều là securities brokers (VND, VIX, VFS, VIG, VIE,
WSS, VUA, VTR, VTE, VSN, VSI, VRG, VPX, VPD, VE2, VE4)

Khả năng: KBS dùng item_id khác cho ngành chứng khoán (Securities Industry)
vì cash flow schema khác (no "operating", instead "I.cash_flows_from_brokerage"
hoặc tương tự).

Test 5 securities brokers, dump full CF structure:
  VND, VIX, VFS, SSI, HCM  (top 5 securities firms by liquidity)
"""
import os
import sys

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

pd.set_option("display.max_rows",     200)
pd.set_option("display.max_columns",  20)
pd.set_option("display.width",        220)
pd.set_option("display.max_colwidth", 70)

# 5 securities brokers
SYMBOLS = [
    ("VND", "Securities — VNDirect"),
    ("VIX", "Securities — VIX"),
    ("VFS", "Securities — VFS"),
    ("SSI", "Securities — SSI"),
    ("HCM", "Securities — HSC"),
]


def dump_cf(symbol: str, sector: str):
    print(f"\n{'=' * 75}")
    print(f"  SYMBOL: {symbol}  ({sector})")
    print(f"{'=' * 75}")

    # Try KBS year (working for non-securities)
    try:
        df = Finance(source="KBS", symbol=symbol).cash_flow(period="year", limit=1)

        if df is None:
            print("  ❌ Result: None")
            return

        if not isinstance(df, pd.DataFrame):
            print(f"  ❌ Result type: {type(df).__name__}")
            return

        if df.empty:
            print("  ❌ Result: empty DataFrame")
            return

        cols     = df.columns.tolist()
        non_meta = [c for c in cols if c not in ("item", "item_id")]
        shape    = df.shape

        print(f"  Shape: {shape[0]}r × {shape[1]}c")
        print(f"  Columns: {cols}")
        print(f"  Period columns: {non_meta}")

        if not non_meta:
            print("  ❌ NO PERIOD COLUMN!")
            return

        target_col = non_meta[-1]
        idx_col    = "item_id" if "item_id" in df.columns else cols[0]

        print(f"\n  ALL item_ids ({len(df)} rows):")
        print(f"  Format: [idx] item_id = value_in_{target_col}")
        print(f"  " + "-" * 70)

        # Print ALL items, especially looking for anything related to
        # cash flow, brokerage, operating, securities
        try:
            df_idx = df.set_index(idx_col)[target_col]
            if isinstance(df_idx, pd.DataFrame):
                df_idx = df_idx.iloc[:, 0]
        except Exception as e:
            print(f"  ❌ set_index failed: {e}")
            return

        for idx in range(len(df)):
            row     = df.iloc[idx]
            item_id = str(row.get(idx_col, "?"))
            item_nm = str(row.get("item", ""))[:50]
            val     = row.get(target_col)

            if pd.isna(val):
                val_str = "nan"
            elif isinstance(val, (int, float)):
                val_str = f"{val:>20,.0f}" if abs(val) >= 1 else f"{val:>20}"
            else:
                val_str = f"{str(val):>20}"

            # Highlight non-nan rows (these have actual data)
            marker = "★" if not pd.isna(val) else " "
            print(f"  {marker} [{idx:3d}] {item_id:55s} = {val_str}  | {item_nm}")

        # Quick test current keys
        print(f"\n  Quick test current _CFO_KEYS / _CFI_KEYS / _CFF_KEYS:")
        for label, keys in [
            ("CFO", ["operating_cash_flow",
                     "net_cash_flows_from_operating_activities",
                     "i_cash_flows_from_operating_activities"]),
            ("CFI", ["investing_cash_flow",
                     "net_cash_flows_from_investing_activities",
                     "ii_cash_flows_from_investing_activities"]),
            ("CFF", ["financing_cash_flow",
                     "net_cash_flows_from_financing_activities",
                     "iii_cash_flows_from_financing_activities"]),
        ]:
            matched = None
            for k in keys:
                if k in df_idx.index:
                    v = df_idx[k]
                    if pd.notna(v):
                        matched = (k, v)
                        break
            if matched:
                k, v = matched
                v_str = f"{v:,.0f}" if isinstance(v, (int, float)) else str(v)
                print(f"    {label}: ✅ matched {k!r} = {v_str}")
            else:
                print(f"    {label}: ❌ none of {keys[:1]}... matched (or all nan)")

    except Exception as e:
        print(f"  ❌ Exception: {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()


def main():
    print("=" * 75)
    print("  Securities brokers cash_flow Schema Diagnostic")
    print("=" * 75)

    for sym, sector in SYMBOLS:
        dump_cf(sym, sector)

    print("\n" + "=" * 75)
    print("  DONE — Look for ★ rows (have data) to find correct item_ids")
    print("=" * 75)


if __name__ == "__main__":
    main()
