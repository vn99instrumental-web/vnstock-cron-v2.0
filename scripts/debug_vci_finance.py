"""
scripts/debug_vci_finance.py
=============================
v2 — Print TẤT CẢ items để confirm CF item_ids và VCI params.
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
os.environ["VNSTOCK_INTERACTIVE"] = "0"
os.environ["VNSTOCK_LANGUAGE"]    = "en"

TEST_SYMBOL = "VNM"

try:
    from vnstock_data import Finance
except ImportError:
    print("vnstock_data not available"); sys.exit(0)

# ── VCI: thử các params khác nhau ───────────────────────────
print("=" * 55)
print("VCI — thử các params khác nhau")
print("=" * 55)

vci_attempts = [
    {"period": "quarter"},
    {"period": "quarter", "lang": "en"},
    {"period": "quarter", "lang": "vi"},
    {"period": "year"},
]

for kwargs in vci_attempts:
    try:
        fin = Finance(source="VCI", symbol=TEST_SYMBOL)
        df  = fin.income_statement(**kwargs)
        status = f"Shape={df.shape}, cols={list(df.columns)[:5]}" \
                 if df is not None and not df.empty else "EMPTY"
        print(f"  income_statement({kwargs}): {status}")
    except Exception as e:
        print(f"  income_statement({kwargs}): ERROR {type(e).__name__}: {e}")

# cash_flow VCI
try:
    fin = Finance(source="VCI", symbol=TEST_SYMBOL)
    df  = fin.cash_flow(period="quarter")
    print(f"  cash_flow(quarter): {'Shape='+str(df.shape) if df is not None and not df.empty else 'EMPTY'}")
except Exception as e:
    print(f"  cash_flow(quarter): ERROR {e}")

# ── KBS: In FULL CF items ────────────────────────────────────
print()
print("=" * 55)
print("KBS — FULL cash_flow() items (tất cả 50 rows)")
print("=" * 55)

try:
    fin = Finance(source="KBS", symbol=TEST_SYMBOL)
    df_cf = fin.cash_flow(period="quarter", limit=4)

    if df_cf is not None and not df_cf.empty:
        idx_col     = "item_id" if "item_id" in df_cf.columns else df_cf.columns[0]
        period_cols = [c for c in df_cf.columns if c not in ("item", "item_id")]
        latest_col  = period_cols[-1] if period_cols else None

        print(f"Shape: {df_cf.shape}")
        print(f"Period columns: {period_cols}")
        print()
        print(f"{'item_id':60s} | {'value (latest)':20s} | item_name")
        print("-" * 100)

        for _, row in df_cf.iterrows():
            item_id  = str(row.get(idx_col, ""))
            val      = str(row.get(latest_col, "")) if latest_col else ""
            item_nm  = str(row.get("item", ""))[:50]
            print(f"  {item_id:58s} | {val:20s} | {item_nm}")
    else:
        print("EMPTY")
except Exception as e:
    print(f"ERROR: {e}")
    import traceback; traceback.print_exc()

# ── KBS: Balance sheet — confirm NO CF items ─────────────────
print()
print("=" * 55)
print("KBS — balance_sheet() — tìm CF-related items")
print("=" * 55)

try:
    fin = Finance(source="KBS", symbol=TEST_SYMBOL)
    df_bs = fin.balance_sheet(period="quarter", limit=1)

    if df_bs is not None and not df_bs.empty:
        idx_col = "item_id" if "item_id" in df_bs.columns else df_bs.columns[0]
        all_items = df_bs[idx_col].tolist()
        cf_items  = [i for i in all_items
                     if any(k in str(i).lower()
                            for k in ('cash_flow','operating_activ','investing_activ',
                                      'financing_activ','net_cash','luu_chuyen'))]
        print(f"Total BS items: {len(all_items)}")
        print(f"CF-related in BS: {cf_items}")
        if not cf_items:
            print("→ CONFIRMED: CF items NOT in balance_sheet()")
            print("→ Must read from cash_flow() separately")
    else:
        print("EMPTY")
except Exception as e:
    print(f"ERROR: {e}")

print()
print("=" * 55)
print("DONE")
