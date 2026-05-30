"""
scripts/debug_vci_pe_outlier.py — Verify tiny-PE values from VCI fallback
==========================================================================
Nghi vấn: VCI ratio_summary trả PE < 1 (VNX=0.0165, VKP=-0.084, VSP=-0.018)
→ scoring chấm như "siêu rẻ" +10đ. Cần xác định:

  1. PE tiny ở MỌI period hay chỉ period mới nhất? (→ lỗi chọn row?)
  2. Có cột nào = 1/pe không? (→ VCI lưu earnings_yield thay vì PE?)
  3. ps/pb có tiny cùng không? (→ scaling issue toàn bộ?)
  4. EPS trong row là bao nhiêu? (→ pe tiny do EPS bịa khổng lồ?)
  5. So với giá hiện tại (Quote) → PE thật ≈ bao nhiêu?

Symbols:
  Nghi vấn  : VNX, VKP, VSP, VHI (VHI=676 lớn, control loại A)
  Bình thường: VPW (14.10), VPR (8.06) — VCI fallback nhưng PE hợp lý
  Reference : HPG — known good, xem ratio_summary chuẩn trông thế nào

Cách dùng:
  Chạy qua debug.yml, script = scripts/debug_vci_pe_outlier.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

os.environ["VNSTOCK_INTERACTIVE"] = "0"
os.environ["VNSTOCK_LANGUAGE"]    = "en"
os.environ["MPLCONFIGDIR"]        = "/home/runner/.config/matplotlib"
os.makedirs("/home/runner/.vnstock",           exist_ok=True)
os.makedirs("/home/runner/.config/matplotlib", exist_ok=True)

import pandas as pd

try:
    from vnstock_data import Company, Quote
except ImportError:
    print("vnstock_data not available")
    sys.exit(0)

pd.set_option("display.max_rows",     100)
pd.set_option("display.width",        200)
pd.set_option("display.max_colwidth", 40)
pd.set_option("display.float_format", lambda x: f"{x:.6f}")

SUSPECTS = ["VNX", "VKP", "VSP", "VHI"]
NORMALS  = ["VPW", "VPR"]
REFS     = ["HPG"]
ALL_SYMS = SUSPECTS + NORMALS + REFS

# Cột quan tâm (subset của 61 cols) — để in gọn
KEY_COLS_PRIORITY = [
    "year", "quarter", "ratio_type", "period",
    "pe", "pb", "ps", "ev_to_ebitda",
    "eps", "earning_per_share", "bvps", "book_value_per_share",
    "earning_yield", "earnings_yield", "dividend_yield",
    "roe", "roa", "market_cap", "issue_share", "outstanding_share",
    "after_tax_profit_margin", "gross_margin",
]


def get_last_close(symbol: str) -> float | None:
    """Giá đóng cửa gần nhất từ VCI Quote."""
    try:
        df = Quote(source="VCI", symbol=symbol).history(length="1M", interval="1D")
        if df is None or df.empty:
            return None
        close_col = "close" if "close" in df.columns else None
        if not close_col:
            for c in df.columns:
                if "close" in str(c).lower():
                    close_col = c
                    break
        if close_col:
            return float(df[close_col].dropna().iloc[-1])
    except Exception as e:
        print(f"      (price fetch failed: {e})")
    return None


def inspect(symbol: str):
    print(f"\n{'='*80}\n  {symbol}\n{'='*80}")

    # 1) Last close price
    price = get_last_close(symbol)
    print(f"  Last close (VCI Quote): {price}")

    # 2) ratio_summary full
    try:
        df = Company(source="VCI", symbol=symbol).ratio_summary()
    except Exception as e:
        print(f"  ❌ ratio_summary failed: {type(e).__name__}: {e}")
        return

    if df is None or df.empty:
        print("  ratio_summary: empty")
        return

    print(f"  Shape: {df.shape[0]}r × {df.shape[1]}c")

    # Cột nào thực sự tồn tại
    cols_present = [c for c in KEY_COLS_PRIORITY if c in df.columns]
    print(f"  Key cols present: {cols_present}")

    # 3) ratio_type values (xem có RATIO_TTM không)
    if "ratio_type" in df.columns:
        print(f"  ratio_type values: {df['ratio_type'].unique().tolist()}")

    # 4) Dump pe/pb/ps across ALL periods (xem tiny ở mọi kỳ hay 1 kỳ)
    show_cols = [c for c in ("year", "quarter", "ratio_type",
                             "pe", "pb", "ps", "eps", "earning_per_share",
                             "earning_yield", "earnings_yield", "roe")
                 if c in df.columns]
    print(f"\n  All periods [{', '.join(show_cols)}]:")
    try:
        # Sort latest first nếu có year/quarter
        sort_cols = [c for c in ("year", "quarter") if c in df.columns]
        df_show = df.sort_values(sort_cols, ascending=False) if sort_cols else df
        print(df_show[show_cols].head(12).to_string(index=False))
    except Exception as e:
        print(f"    (display error: {e})")
        print(df[show_cols].head(12).to_string(index=False))

    # 5) Latest row — full transposed (tất cả cols)
    print(f"\n  --- Latest row (full, transposed) ---")
    sort_cols = [c for c in ("year", "quarter") if c in df.columns]
    latest = (df.sort_values(sort_cols, ascending=False).iloc[0]
              if sort_cols else df.iloc[-1])
    for col in df.columns:
        v = latest[col]
        if pd.notna(v):
            print(f"    {col:42s} = {v}")

    # 6) Sanity check: PE thật từ price & eps
    pe_reported = latest.get("pe") if "pe" in df.columns else None
    eps = None
    for ec in ("eps", "earning_per_share"):
        if ec in df.columns and pd.notna(latest.get(ec)):
            eps = float(latest[ec])
            break
    print(f"\n  SANITY:")
    print(f"    pe reported   = {pe_reported}")
    print(f"    eps in row    = {eps}")
    if price and eps and eps != 0:
        pe_computed = price / eps
        print(f"    pe computed (price/eps) = {price}/{eps} = {pe_computed:.3f}")
        if pe_reported and abs(pe_reported) > 0:
            ratio = pe_computed / pe_reported
            print(f"    pe_computed / pe_reported = {ratio:.2f}  "
                  f"(≈1 → pe đúng | ≈ giá trị lớn → pe có thể là 1/PE)")
    # Earnings yield check
    if pe_reported and 0 < abs(pe_reported) < 1:
        print(f"    ⚠️ |pe| < 1 → nếu là earnings_yield thì PE thật ≈ {1/pe_reported:.1f}")


def main():
    print("=" * 80)
    print("  VCI ratio_summary PE outlier verification")
    print(f"  Suspects: {SUSPECTS}")
    print(f"  Normals:  {NORMALS}  |  Refs: {REFS}")
    print("=" * 80)

    for sym in ALL_SYMS:
        inspect(sym)

    print("\n" + "=" * 80)
    print("  DONE — Đối chiếu:")
    print("    - Nếu pe tiny ở MỌI period → field pe của VCI sai/khác nghĩa")
    print("    - Nếu pe_computed/pe_reported ≈ 60 và 1/pe ≈ 60 → pe là earnings_yield")
    print("    - Nếu chỉ period mới nhất tiny → lỗi chọn row (dùng period cũ hơn)")
    print("=" * 80)


if __name__ == "__main__":
    main()
