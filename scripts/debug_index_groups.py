"""
scripts/debug_index_groups.py — Test index group names for VN100, HNX30
========================================================================
Mục đích trước khi code patch:
  Xác nhận chính xác tên group cần dùng cho:
    - HSX VN100  (100 large/mid-cap HSX)
    - HNX30     (30 top HNX)
    - VN30      (fallback, để compare)

  Test cả 2 method có thể work:
    A. Listing.symbols_by_group(group=...) — kỳ vọng cách chính
    B. Listing.indices_by_group(group=...) — fallback nếu A miss
    C. Listing.all_indices()                — discovery, xem có những index nào

  Test nhiều tên group khả dĩ vì vnstock có thể dùng convention khác:
    VN30 / VN100 / VN-30 / HNX30 / HNXIndex / VN30Index / ...

Cách dùng:
  Chạy qua debug.yml, script = scripts/debug_index_groups.py
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
    from vnstock_data import Listing
except ImportError:
    print("vnstock_data not available")
    sys.exit(0)

pd.set_option("display.max_rows",     200)
pd.set_option("display.width",        180)
pd.set_option("display.max_colwidth", 80)

# Tên group khả dĩ — test all
GROUP_NAMES = [
    # VN30 family
    "VN30",
    "VN-30",
    "VN30INDEX",
    "VNINDEX",
    "HOSE",
    # VN100 family
    "VN100",
    "VN-100",
    "VN100INDEX",
    "VNX100",
    "VNXINDEX",
    "VNXALLSHARE",
    "VNX-ALLSHARE",
    "VNAllShare",
    # HNX
    "HNX",
    "HNX30",
    "HNX-30",
    "HNX30INDEX",
    "HNXINDEX",
    # Other common
    "UPCOM",
    "UPCOM-PREMIUM",
    "FU-INDEX",
    "MARGIN",
]


def show_result(label: str, df, max_show: int = 15):
    """Pretty print result."""
    if df is None:
        print(f"  {label} → None")
        return 0
    if isinstance(df, pd.DataFrame):
        if df.empty:
            print(f"  {label} → empty DataFrame")
            return 0
        print(f"  {label} → ✅ DataFrame {df.shape[0]}r × {df.shape[1]}c")
        print(f"      Cols: {df.columns.tolist()}")
        # Show first N symbols if 'symbol' column present
        if "symbol" in df.columns:
            symbols = df["symbol"].dropna().astype(str).unique().tolist()
            print(f"      Symbols ({len(symbols)}): {symbols[:max_show]}"
                  + (" ..." if len(symbols) > max_show else ""))
        else:
            print(f"      First row: {df.iloc[0].to_dict()}")
        return df.shape[0]
    if isinstance(df, list):
        print(f"  {label} → ✅ list len={len(df)}: {df[:max_show]}"
              + (" ..." if len(df) > max_show else ""))
        return len(df)
    print(f"  {label} → {type(df).__name__}: {str(df)[:200]}")
    return 0


# ════════════════════════════════════════════════════════════════════════
# PART C — Discovery: all_indices()
# ════════════════════════════════════════════════════════════════════════
print("=" * 80)
print("  PART C — Discovery via Listing.all_indices()")
print("=" * 80)
try:
    listing = Listing(source="VCI")
    if hasattr(listing, "all_indices"):
        df = listing.all_indices()
        show_result("all_indices()", df, max_show=50)
    else:
        print("  ⊘ all_indices() not available")
except Exception as e:
    print(f"  ❌ {type(e).__name__}: {e}")

print()
try:
    listing = Listing(source="VCI")
    if hasattr(listing, "indices_by_group"):
        df = listing.indices_by_group()
        show_result("indices_by_group()", df, max_show=50)
    else:
        print("  ⊘ indices_by_group() not available")
except Exception as e:
    print(f"  ❌ {type(e).__name__}: {e}")


# ════════════════════════════════════════════════════════════════════════
# PART A — symbols_by_group with each candidate group name
# ════════════════════════════════════════════════════════════════════════
print("\n" + "=" * 80)
print("  PART A — Listing.symbols_by_group(group=...)")
print("=" * 80)

found_groups: dict[str, int] = {}

for group in GROUP_NAMES:
    try:
        listing = Listing(source="VCI")
        df = listing.symbols_by_group(group=group)
        count = show_result(f"symbols_by_group(group={group!r})", df, max_show=15)
        if count > 0:
            found_groups[group] = count
    except Exception as e:
        msg = str(e)[:100]
        print(f"  symbols_by_group(group={group!r}) → ❌ {type(e).__name__}: {msg}")


# ════════════════════════════════════════════════════════════════════════
# PART B — symbols_by_group without group param (defaults?)
# ════════════════════════════════════════════════════════════════════════
print("\n" + "=" * 80)
print("  PART B — symbols_by_group() no arg + via indices_by_group(group)")
print("=" * 80)

# B.1 — no arg
try:
    listing = Listing(source="VCI")
    df = listing.symbols_by_group()
    show_result("symbols_by_group() no arg", df, max_show=15)
except Exception as e:
    print(f"  symbols_by_group() → ❌ {type(e).__name__}: {str(e)[:120]}")

# B.2 — Loop indices_by_group with each name
print()
for group in ("VN30", "VN100", "HNX30", "HOSE", "HNX"):
    try:
        listing = Listing(source="VCI")
        df = listing.indices_by_group(group=group)
        show_result(f"indices_by_group(group={group!r})", df, max_show=15)
    except Exception as e:
        print(f"  indices_by_group(group={group!r}) → ❌ {type(e).__name__}: {str(e)[:120]}")


# ════════════════════════════════════════════════════════════════════════
# SUMMARY
# ════════════════════════════════════════════════════════════════════════
print("\n" + "=" * 80)
print("  SUMMARY — groups returning data")
print("=" * 80)
if not found_groups:
    print("  ⚠️ No working group name found via symbols_by_group")
    print("  → Need to find alternative method (e.g. parse VN100 from all_indices)")
else:
    for g, n in sorted(found_groups.items(), key=lambda x: -x[1]):
        print(f"    {g}: {n} symbols")
    print()
    print("  → Dùng các group này trong get_scan_universe()")

print()
print("=" * 80)
print("  DONE")
print("=" * 80)
