"""
scripts/debug_kbs.py
====================
Chạy 1 lần để xác nhận item_id thực tế của KBS cho BS và CF.
Cần chạy trong môi trường có vnstock_data.

Usage:
  source /opt/vnstock/.venv/bin/activate
  python scripts/debug_kbs.py

Output: in ra tất cả item_ids + values để xác nhận keys cần dùng
        trong _kbs_lookup() cho bs_total_assets, bs_equity,
        cf_operating, cf_investing, cf_financing.
"""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

os.environ["VNSTOCK_INTERACTIVE"] = "0"
os.environ["VNSTOCK_LANGUAGE"]    = "en"

# Test với non-bank + bank để thấy sự khác biệt item_id
TEST_SYMBOLS = ["VNM", "VCB", "HPG"]

try:
    from vnstock_data import Finance
except ImportError:
    print("vnstock_data not available — chạy trên GitHub Actions hoặc venv có vnstock")
    sys.exit(0)

for sym in TEST_SYMBOLS:
    print(f"\n{'='*60}")
    print(f"SYMBOL: {sym}")
    print("="*60)

    for report, method_name, limit in [
        ("BALANCE SHEET", "balance_sheet",    1),
        ("CASH FLOW",     "cash_flow",        1),
        ("INCOME",        "income_statement", 4),  # limit=4 để thấy được QoQ
    ]:
        try:
            fin = Finance(source="KBS", symbol=sym)
            df  = getattr(fin, method_name)(period="quarter", limit=limit)

            if df is None or df.empty:
                print(f"\n  --- {report}: EMPTY ---")
                continue

            idx_col     = "item_id" if "item_id" in df.columns else df.columns[0]
            period_cols = [c for c in df.columns if c not in ["item", "item_id"]]

            print(f"\n  --- {report} ({len(df)} items, periods: {period_cols}) ---")
            print(f"  {'item_id':55s} | {'latest_value':20s} | item_name")
            print(f"  {'-'*55}-+-{'-'*20}-+--------")

            latest_col = period_cols[-1] if period_cols else None
            for _, row in df.iterrows():
                item_id = str(row.get(idx_col, ""))
                val     = row[latest_col] if latest_col else "-"
                item_nm = str(row.get("item", ""))[:50]
                print(f"  {item_id:55s} | {str(val):20s} | {item_nm}")

        except Exception as e:
            print(f"\n  --- {report}: ERROR — {e} ---")
            import traceback
            traceback.print_exc()

print("\n" + "="*60)
print("DONE — Copy item_ids vào _kbs_lookup() trong step_all.py")
print("="*60)
