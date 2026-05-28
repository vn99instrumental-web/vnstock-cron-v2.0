"""
scripts/debug_finance_mas.py — Test MAS as ratio/CF fallback
=============================================================
Diagnostic TCBS+VCI cho kết quả:
  - TCBS: không tồn tại (vnstock_data 3.0 chỉ accept VCI hoặc MAS)
  - VCI:  empty 100% cho 6 mã thiếu data

Còn 1 nguồn chưa test: MAS (Mirae Asset Securities).
Đây là lần test cuối trước khi quyết accept data gap.

Cách dùng:
  Chạy qua debug.yml, script = scripts/debug_finance_mas.py
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

# 6 mã có KBS thiếu data + 1 large-cap đối chứng (HPG, KBS work)
SYMBOLS = ["CCC", "KDC", "FDC", "C32", "TNT", "VDS", "HPG"]

# (report, kwargs)
TESTS = [
    ("ratio",     {"period": "quarter", "limit": 1}),
    ("ratio",     {"period": "year",    "limit": 1}),
    ("cash_flow", {"period": "quarter", "limit": 1}),
    ("cash_flow", {"period": "year",    "limit": 1}),
]

PE_HINTS  = ("pe_ratio", "p_e", "price_to_earnings", "price_earning")
CFO_HINTS = ("operating", "kinh_doanh", "hdkd", "luu_chuyen", "cfo")


def _find_match(df, hints):
    """Wide hoặc long form — tìm key/col match hints."""
    if df is None or df.empty:
        return None
    if "item_id" in df.columns:
        period_cols = [c for c in df.columns if c not in ("item", "item_id")]
        if not period_cols:
            return None
        target = period_cols[-1]
        for _, row in df.iterrows():
            k = str(row["item_id"]).lower()
            if any(h in k for h in hints):
                return (row["item_id"], row.get(target))
    else:
        for col in df.columns:
            if any(h in str(col).lower() for h in hints):
                return (col, df.iloc[-1][col] if len(df) else None)
    return None


def run_test(symbol: str, report: str, kwargs: dict):
    label = f"MAS {report:12s} {kwargs}"
    try:
        fin    = Finance(source="MAS", symbol=symbol)
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

        shape       = df.shape
        cols        = df.columns.tolist()
        has_item_id = "item_id" in cols
        form        = "wide" if has_item_id else "long"
        period_cols = [c for c in cols if c not in ("item", "item_id")]
        print(f"  {label} → ✅ {shape[0]}r×{shape[1]}c [{form}-form] periods={period_cols}")

        hints = PE_HINTS if report == "ratio" else CFO_HINTS
        hit   = _find_match(df, hints)
        target_name = "PE" if report == "ratio" else "CFO"
        if hit:
            k, v = hit
            if isinstance(v, (int, float)) and pd.notna(v):
                v_str = f"{v:,.0f}" if abs(v) >= 1 else f"{v}"
            else:
                v_str = str(v)
            print(f"      {target_name} found: {k!r} = {v_str}")
        else:
            print(f"      {target_name} NOT found. Cols: {cols[:10]}...")
            if not has_item_id and len(df) > 0:
                print(f"      Sample row:\n{df.head(1).to_string()}")

    except Exception as e:
        print(f"  {label} → ❌ {type(e).__name__}: {str(e)[:120]}")


def main():
    print("=" * 80)
    print("  Finance MAS Source Diagnostic — last fallback test")
    print(f"  Symbols: {SYMBOLS} (HPG = control: KBS work tốt)")
    print(f"  Tests/symbol: {len(TESTS)}")
    print("=" * 80)

    for sym in SYMBOLS:
        print(f"\n{'='*80}\n  SYMBOL: {sym}\n{'='*80}")
        for report, kwargs in TESTS:
            run_test(sym, report, kwargs)

    print("\n" + "=" * 80)
    print("  DONE — Đếm số dòng '✅' để quyết định:")
    print("    Nếu MAS có data cho KDC/CCC → thêm MAS fallback vào fetch_one")
    print("    Nếu MAS cũng empty → accept data gap, chuyển plan A+B+C")
    print("=" * 80)


if __name__ == "__main__":
    main()
