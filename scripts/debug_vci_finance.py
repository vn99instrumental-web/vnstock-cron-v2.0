"""
scripts/debug_vci_finance.py
=============================
So sánh VCI vs KBS để quyết định migrate.
Cần xem:
  1. VCI Long-form columns thực tế
  2. CF data có trong cash_flow() không (không bị trộn vào BS)
  3. Growth tính trực tiếp từ rows

Usage: python scripts/debug_vci_finance.py
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
os.environ["VNSTOCK_INTERACTIVE"] = "0"
os.environ["VNSTOCK_LANGUAGE"]    = "en"

TEST_SYMBOL = "VNM"  # stable large-cap, chắc có data

try:
    from vnstock_data import Finance
except ImportError:
    print("vnstock_data not available"); sys.exit(0)

print(f"Testing symbol: {TEST_SYMBOL}\n")

for source in ["VCI", "KBS"]:
    print(f"\n{'='*55}")
    print(f"SOURCE: {source}")
    print("="*55)

    fin = Finance(source=source, symbol=TEST_SYMBOL)

    for report in ["income_statement", "balance_sheet", "cash_flow", "ratio"]:
        print(f"\n--- {report} ---")
        try:
            kwargs = {"period": "quarter"}
            if source == "KBS":
                kwargs["limit"] = 4
            df = getattr(fin, report)(**kwargs)

            if df is None or df.empty:
                print("  EMPTY"); continue

            print(f"  Shape: {df.shape}")
            print(f"  Columns: {list(df.columns)[:10]}")

            if source == "VCI":
                # Long-form: rows are periods
                print(f"  Rows (periods): {df.shape[0]}")
                if "report_period" in df.columns:
                    print(f"  Periods: {df['report_period'].tolist()}")
                # Show latest row values
                print(f"  Latest row:\n{df.iloc[-1].to_string()[:500]}")

                # Calculate growth directly
                if df.shape[0] >= 2 and report == "income_statement":
                    # Find revenue column
                    rev_cols = [c for c in df.columns if 'revenue' in c.lower() or 'net_revenue' in c.lower()]
                    profit_cols = [c for c in df.columns if 'profit' in c.lower() and 'tax' in c.lower()]
                    print(f"\n  Revenue cols: {rev_cols}")
                    print(f"  Profit cols: {profit_cols[:3]}")
                    if rev_cols:
                        col = rev_cols[0]
                        v1 = df.iloc[-1][col]
                        v2 = df.iloc[-2][col]
                        if v2 and v2 != 0:
                            growth = (v1 - v2) / abs(v2)
                            print(f"  Rev QoQ growth: {growth:.2%}")

            else:
                # KBS Wide-form: rows are items
                idx_col = "item_id" if "item_id" in df.columns else df.columns[0]
                items = df[idx_col].tolist()
                # Show CF-related items
                cf_items = [i for i in items if any(k in str(i).lower()
                    for k in ('cash', 'flow', 'operat', 'invest', 'financ'))]
                print(f"  CF-related item_ids: {cf_items[:10]}")

        except Exception as e:
            print(f"  ERROR: {type(e).__name__}: {e}")
            import traceback; traceback.print_exc()

print("\n" + "="*55)
print("DONE - Check columns above to decide migration strategy")
