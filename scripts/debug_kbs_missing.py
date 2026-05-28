"""
scripts/debug_kbs_missing.py — Tìm item_id còn thiếu cho CFO + PE
==================================================================
Mục đích:
  Các mã top-intraday (CCC, KDC, FDC, C32, TNT) bị thiếu CFO/PE khi
  lazy-fetch. Script này dump TOÀN BỘ item_id để:
    1. CASH FLOW (period="year", limit=1) → tìm item_id chứa CFO
       mà _CFO_KEYS hiện tại chưa có.
    2. RATIO (period="quarter", limit=1) → xem pe_ratio có tồn tại /
       có phải nan không (chẩn đoán PE=None).

  VDS để làm baseline đối chứng (mã này trích CFO OK).

Cách dùng:
  Chạy qua debug.yml (workflow_dispatch), script = scripts/debug_kbs_missing.py
  Hoặc local:
    /opt/vnstock/.venv/bin/python scripts/debug_kbs_missing.py

Sau khi chạy: gửi log về để chốt exact key + fuzzy pattern.
"""
import os
import sys
import traceback

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

os.environ["VNSTOCK_INTERACTIVE"] = "0"
os.environ["VNSTOCK_LANGUAGE"]    = "en"
os.environ["MPLCONFIGDIR"]        = "/home/runner/.config/matplotlib"
os.makedirs("/home/runner/.vnstock",           exist_ok=True)
os.makedirs("/home/runner/.config/matplotlib", exist_ok=True)

import pandas as pd

try:
    from vnstock_data import Finance
except ImportError:
    print("vnstock_data not available — chạy trên GitHub Actions hoặc venv có vnstock")
    sys.exit(0)

try:
    import vnstock_data
    ver = (getattr(vnstock_data, "__version__", None) or
           getattr(vnstock_data, "VERSION", None) or "unknown")
    print(f"vnstock_data version: {ver}")
except Exception:
    pass

pd.set_option("display.max_rows",     200)
pd.set_option("display.width",        220)
pd.set_option("display.max_colwidth", 70)


# Các mã thiếu CFO/PE + VDS (baseline đối chứng — CFO OK)
SYMBOLS = ["CCC", "KDC", "FDC", "C32", "TNT", "VDS"]

# (report_name, kwargs) — dùng ĐÚNG config mà fetch_one dùng
REPORTS = [
    ("cash_flow",       {"period": "year",    "limit": 1}),  # CFO key
    ("ratio",           {"period": "quarter", "limit": 1}),  # PE diag
]

# Các pattern để highlight dòng nghi là CFO / PE
CFO_HINTS = ("operating", "kinh_doanh", "hdkd", "luu_chuyen")
PE_HINTS  = ("pe", "p_e", "price_earning")


def dump_report(symbol: str, report_name: str, kwargs: dict):
    print(f"\n  --- {report_name.upper()} {kwargs} ---")
    try:
        fin    = Finance(source="KBS", symbol=symbol)
        method = getattr(fin, report_name)
        df     = method(**kwargs)

        if df is None:
            print("    Result: None")
            return
        if not isinstance(df, pd.DataFrame):
            print(f"    Result type: {type(df).__name__} — {str(df)[:120]}")
            return
        if df.empty:
            print("    Result: empty DataFrame")
            return

        cols        = df.columns.tolist()
        period_cols = [c for c in cols if c not in ("item", "item_id")]
        print(f"    Shape: {df.shape[0]}r × {df.shape[1]}c | period_cols={period_cols}")

        if not period_cols:
            print("    ⚠️ NO PERIOD COLUMN — broken format (giống bug quarter cũ)")
            print(f"    Columns raw: {cols}")
            return

        target_col = period_cols[-1]
        idx_col    = "item_id" if "item_id" in cols else cols[0]

        hints = CFO_HINTS if report_name == "cash_flow" else PE_HINTS

        print(f"    Dump ALL item_id (value @ {target_col}):")
        print(f"    {'-'*78}")
        for _, row in df.iterrows():
            item_id = str(row.get(idx_col, ""))
            val     = row.get(target_col)
            if pd.isna(val):
                val_str = "nan"
            elif isinstance(val, (int, float)):
                val_str = f"{val:,.0f}" if abs(val) >= 1 else f"{val}"
            else:
                val_str = str(val)[:30]
            mark = "  ★" if any(h in item_id.lower() for h in hints) else "   "
            print(f"   {mark} {item_id:58s} = {val_str}")

    except Exception as e:
        print(f"    ❌ ERROR: {type(e).__name__}: {e}")
        traceback.print_exc()


def main():
    print("=" * 80)
    print("  KBS Missing-Field Diagnostic — CFO key + PE availability")
    print(f"  Symbols: {SYMBOLS}")
    print("  ★ = dòng nghi là CFO (cash_flow) hoặc PE (ratio)")
    print("=" * 80)

    for sym in SYMBOLS:
        print(f"\n{'='*80}\n  SYMBOL: {sym}\n{'='*80}")
        for report_name, kwargs in REPORTS:
            dump_report(sym, report_name, kwargs)

    print("\n" + "=" * 80)
    print("  DONE — Gửi log này về để chốt _CFO_KEYS + fuzzy pattern + PE fallback")
    print("=" * 80)


if __name__ == "__main__":
    main()
