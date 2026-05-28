"""
scripts/debug_vci_full.py — Comprehensive VCI capability check
================================================================
3 phần:

  Part 1 — VCI Finance universality:
    Test Finance(VCI) cho HPG, VCB (large caps control) + KDC, CCC.
    → Đóng câu hỏi "VCI Finance ALL empty" — đúng cho toàn thị trường
      hay chỉ với mid/small cap?

  Part 2 — Method discovery:
    dir() từng VCI class (Company, Listing, Analytics, Trading, Finance)
    để phát hiện method ẩn có thể chứa PE/financial data.

  Part 3 — Alternative modules for missing symbols:
    Gọi các method có vẻ promising cho KDC + CCC (representative).
    → Nếu bất kỳ method nào trả PE → có fallback bypass Finance hoàn toàn.

Cách dùng:
  Chạy qua debug.yml, script = scripts/debug_vci_full.py
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

pd.set_option("display.max_rows",     50)
pd.set_option("display.width",        220)
pd.set_option("display.max_colwidth", 60)

# ─── Import tất cả VCI class có thể ─────────────────────────────────────
AVAILABLE_CLASSES = {}
for class_name in ("Finance", "Company", "Listing", "Analytics",
                   "Trading", "Quote", "Reference", "TopStock"):
    try:
        cls = __import__("vnstock_data", fromlist=[class_name])
        AVAILABLE_CLASSES[class_name] = getattr(cls, class_name)
    except (ImportError, AttributeError) as e:
        AVAILABLE_CLASSES[class_name] = None

print("=" * 80)
print("  Imported classes:")
for name, cls in AVAILABLE_CLASSES.items():
    print(f"    {name:12s}: {'✅' if cls else '❌ not available'}")
print("=" * 80)


def safe_call(label: str, fn, *args, **kwargs):
    """Call any function, print structured result."""
    print(f"\n  → {label}")
    try:
        result = fn(*args, **kwargs)
        if result is None:
            print(f"      Result: None")
            return None
        if isinstance(result, pd.DataFrame):
            if result.empty:
                print(f"      Result: empty DataFrame")
                return None
            print(f"      ✅ DataFrame {result.shape[0]}r×{result.shape[1]}c")
            print(f"      Cols: {result.columns.tolist()[:15]}")
            print(f"      First row:")
            print(result.head(1).to_string()[:1200])
            return result
        if isinstance(result, dict):
            print(f"      ✅ dict, {len(result)} keys: {list(result.keys())[:15]}")
            for k, v in list(result.items())[:8]:
                v_repr = str(v)[:80]
                print(f"        {k}: {v_repr}")
            return result
        if isinstance(result, (list, tuple)):
            print(f"      ✅ {type(result).__name__}, len={len(result)}")
            if result:
                print(f"        First: {str(result[0])[:200]}")
            return result
        # Scalar / other
        print(f"      ✅ {type(result).__name__}: {str(result)[:200]}")
        return result
    except Exception as e:
        print(f"      ❌ {type(e).__name__}: {str(e)[:160]}")
        return None


# ════════════════════════════════════════════════════════════════════════
# PART 1 — VCI Finance universality
# ════════════════════════════════════════════════════════════════════════
print("\n" + "█" * 80)
print("  PART 1 — VCI Finance universality (HPG, VCB control + KDC, CCC missing)")
print("█" * 80)

Finance = AVAILABLE_CLASSES.get("Finance")
if Finance:
    for sym in ("HPG", "VCB", "KDC", "CCC"):
        print(f"\n{'─'*80}\n  Finance(VCI, {sym})\n{'─'*80}")
        for report in ("ratio", "cash_flow", "income_statement", "balance_sheet"):
            for kw in ({"period": "quarter", "limit": 1},
                       {"period": "year",    "limit": 1}):
                safe_call(
                    f"{report:18s} {kw}",
                    getattr(Finance(source="VCI", symbol=sym), report),
                    **kw
                )
else:
    print("  Finance class not available — skip Part 1")


# ════════════════════════════════════════════════════════════════════════
# PART 2 — Method discovery
# ════════════════════════════════════════════════════════════════════════
print("\n" + "█" * 80)
print("  PART 2 — Method discovery (dir() each VCI class)")
print("█" * 80)

def dump_methods(class_name: str, instance):
    if instance is None:
        return
    methods = [m for m in dir(instance) if not m.startswith("_")]
    # Filter callables
    callable_methods = []
    for m in methods:
        try:
            attr = getattr(instance, m)
            if callable(attr):
                callable_methods.append(m)
        except Exception:
            pass
    print(f"\n  {class_name}({instance.__class__.__name__}) methods ({len(callable_methods)}):")
    # Print 5 per line
    for i in range(0, len(callable_methods), 5):
        print(f"    {', '.join(callable_methods[i:i+5])}")

# Instantiate each class with HPG / VCI
for class_name in ("Finance", "Company", "Listing", "Analytics", "Trading"):
    cls = AVAILABLE_CLASSES.get(class_name)
    if not cls:
        continue
    try:
        # Some classes need symbol, some don't
        if class_name in ("Finance", "Company", "Trading", "Quote"):
            instance = cls(source="VCI", symbol="HPG")
        else:
            instance = cls(source="VCI")
        dump_methods(class_name, instance)
    except Exception as e:
        print(f"  {class_name}: ❌ instantiation failed — {e}")


# ════════════════════════════════════════════════════════════════════════
# PART 3 — Try alternative modules for KDC + CCC
# ════════════════════════════════════════════════════════════════════════
print("\n" + "█" * 80)
print("  PART 3 — Alternative VCI modules for KDC + CCC")
print("█" * 80)

# Methods nghi có PE / financial summary
ALTERNATIVE_TESTS = [
    # (class_name, method_name, args_dict, needs_symbol)
    ("Company",   "overview",          {}, True),
    ("Company",   "profile",           {}, True),
    ("Company",   "ratio_summary",     {}, True),
    ("Company",   "financial_ratio",   {}, True),
    ("Company",   "shareholders",      {}, True),
    ("Listing",   "financial_info",    {}, False),
    ("Listing",   "industries_icb",    {}, False),
    ("Analytics", "valuation",         {"symbol": "KDC"}, False),
    ("Trading",   "stock_summary",     {}, True),
]

for sym in ("KDC", "CCC"):
    print(f"\n{'─'*80}\n  Symbol: {sym}\n{'─'*80}")
    for class_name, method_name, kwargs, needs_symbol in ALTERNATIVE_TESTS:
        cls = AVAILABLE_CLASSES.get(class_name)
        if not cls:
            continue
        try:
            if needs_symbol:
                instance = cls(source="VCI", symbol=sym)
            else:
                instance = cls(source="VCI")

            if not hasattr(instance, method_name):
                print(f"\n  → {class_name}.{method_name}() — ⊘ method not exist")
                continue

            # Update symbol arg if Analytics.valuation
            if method_name == "valuation":
                kwargs = {"symbol": sym}

            safe_call(
                f"{class_name}.{method_name}({kwargs})",
                getattr(instance, method_name),
                **kwargs
            )
        except Exception as e:
            print(f"\n  → {class_name}.{method_name}() — ❌ {type(e).__name__}: {e}")


print("\n" + "=" * 80)
print("  DONE")
print("=" * 80)
print()
print("  Đọc kết quả theo thứ tự:")
print("    1. Part 1: HPG/VCB có '✅' không → VCI Finance còn sống không?")
print("    2. Part 2: tìm method nào nghe giống ratio/overview/financial")
print("    3. Part 3: tìm dòng '✅' có PE / financial value cho KDC/CCC")
