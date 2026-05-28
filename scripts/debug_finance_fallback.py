"""
scripts/debug_finance_fallback.py — Test TCBS + VCI as ratio/CF fallback
========================================================================
Mục đích:
  KBS trả EMPTY cho ratio (CCC/KDC/VDS) hoặc cash_flow (CCC/KDC/FDC/C32/TNT)
  với các mã top-intraday động. Cần biết:

  1. TCBS có data cho các mã này không? (most likely fallback)
  2. VCI có data không? (kiến trúc ghi "ALL empty" nhưng test lại)
  3. Nếu có, schema của TCBS/VCI khác KBS thế nào? (long-form vs wide-form,
     tên item_id, key cho PE/CFO)

  Kết quả → quyết định có nên thêm TCBS fallback vào fetch_one không.

Cách dùng:
  Chạy qua debug.yml, script = scripts/debug_finance_fallback.py
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
    print("vnstock_data not available")
    sys.exit(0)

pd.set_option("display.max_rows",     50)
pd.set_option("display.width",        220)
pd.set_option("display.max_colwidth", 60)

# Mã có KBS thiếu data
SYMBOLS = ["CCC", "KDC", "FDC", "C32", "TNT", "VDS"]

# (source, report, kwargs)
TESTS = [
    # --- TCBS ---
    ("TCBS", "ratio",     {"period": "quarter", "limit": 1}),
    ("TCBS", "ratio",     {"period": "year",    "limit": 1}),
    ("TCBS", "cash_flow", {"period": "quarter", "limit": 1}),
    ("TCBS", "cash_flow", {"period": "year",    "limit": 1}),
    # --- VCI ---
    ("VCI",  "ratio",     {"period": "quarter", "limit": 1}),
    ("VCI",  "ratio",     {"period": "year",    "limit": 1}),
    ("VCI",  "cash_flow", {"period": "quarter", "limit": 1}),
    ("VCI",  "cash_flow", {"period": "year",    "limit": 1}),
]

# Pattern để highlight
PE_HINTS  = ("pe_ratio", "p_e", "price_to_earnings", "price_earning")
CFO_HINTS = ("operating", "kinh_doanh", "hdkd", "luu_chuyen", "cfo")


def _find_pe(df):
    """Tìm PE value trong df (wide hoặc long form). Return (key, value) or None."""
    if df is None or df.empty:
        return None
    # Wide-form: item_id × period
    if "item_id" in df.columns:
        period_cols = [c for c in df.columns if c not in ("item", "item_id")]
        if not period_cols:
            return None
        target = period_cols[-1]
        for _, row in df.iterrows():
            k = str(row["item_id"]).lower()
            if any(h in k for h in PE_HINTS):
                return (row["item_id"], row.get(target))
    # Long-form: cột metric
    else:
        for col in df.columns:
            if any(h in str(col).lower() for h in PE_HINTS):
                return (col, df.iloc[-1][col] if len(df) else None)
    return None


def _find_cfo(df):
    """Tìm CFO value trong df. Return (key, value) or None."""
    if df is None or df.empty:
        return None
    if "item_id" in df.columns:
        period_cols = [c for c in df.columns if c not in ("item", "item_id")]
        if not period_cols:
            return None
        target = period_cols[-1]
        # Ưu tiên dòng có "operating" + "activ" hoặc "operating" + "cash"
        candidates = []
        for _, row in df.iterrows():
            k = str(row["item_id"]).lower()
            if any(h in k for h in CFO_HINTS):
                candidates.append((row["item_id"], row.get(target)))
        return candidates[0] if candidates else None
    else:
        for col in df.columns:
            if any(h in str(col).lower() for h in CFO_HINTS):
                return (col, df.iloc[-1][col] if len(df) else None)
    return None


def run_test(symbol: str, source: str, report: str, kwargs: dict):
    label = f"{source:5s} {report:12s} {kwargs}"
    try:
        fin    = Finance(source=source, symbol=symbol)
        method = getattr(fin, report)
        df     = method(**kwargs)

        if df is None:
            print(f"  {label} → None")
            return
        if not isinstance(df, pd.DataFrame):
            print(f"  {label} → {type(df).__name__}: {str(df)[:80]}")
            return
        if df.empty:
            print(f"  {label} → empty")
            return

        shape = df.shape
        cols  = df.columns.tolist()
        has_item_id = "item_id" in cols
        period_cols = [c for c in cols if c not in ("item", "item_id")]

        form = "wide" if has_item_id else "long"
        print(f"  {label} → ✅ {shape[0]}r×{shape[1]}c [{form}-form]")

        if report == "ratio":
            hit = _find_pe(df)
            if hit:
                print(f"      PE found: {hit[0]!r} = {hit[1]}")
            else:
                print(f"      PE NOT found. Cols sample: {cols[:8]}...")
                if not has_item_id:
                    print(f"      Sample row:\n{df.head(1).to_string()}")
        else:  # cash_flow
            hit = _find_cfo(df)
            if hit:
                print(f"      CFO found: {hit[0]!r} = {hit[1]:,.0f}"
                      if isinstance(hit[1], (int, float)) and pd.notna(hit[1])
                      else f"      CFO found: {hit[0]!r} = {hit[1]}")
            else:
                print(f"      CFO NOT found. Cols sample: {cols[:8]}...")
                if not has_item_id and len(df) > 0:
                    print(f"      Sample row:\n{df.head(1).to_string()}")

    except Exception as e:
        print(f"  {label} → ❌ {type(e).__name__}: {str(e)[:120]}")


def main():
    print("=" * 80)
    print("  Finance Fallback Source Diagnostic — TCBS + VCI")
    print(f"  Symbols: {SYMBOLS}")
    print(f"  Tests per symbol: {len(TESTS)}")
    print("=" * 80)

    summary = []  # (symbol, source, report, has_data, has_target)

    for sym in SYMBOLS:
        print(f"\n{'='*80}\n  SYMBOL: {sym}\n{'='*80}")
        for source, report, kwargs in TESTS:
            run_test(sym, source, report, kwargs)

    print("\n" + "=" * 80)
    print("  DONE — Tìm dòng '✅' để xem nguồn nào có data + key cần dùng")
    print("=" * 80)


if __name__ == "__main__":
    main()
