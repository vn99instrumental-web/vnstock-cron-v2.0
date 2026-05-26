"""
scripts/debug_show_api.py
==========================
Dump introspection từ vnstock_data để confirm:
  1. show_api() — có in cây thư mục API không?
  2. show_doc(target) — output format có gì, có cover được signature/params không?
  3. Fallback: inspect.signature + __doc__ + dir() — đề phòng (1)(2) thiếu

Mục đích cuối: xem có thể commit output này thành docs/vnstock_api_tree.md
làm reference, đỡ phải đoán signature mỗi lần code mới.

Cách chạy:
  - Trigger .github/workflows/debug.yml manually
    với input: scripts/debug_show_api.py
  - Hoặc local: source /opt/vnstock/.venv/bin/activate
                python scripts/debug_show_api.py 2>&1 | tee show_api.log
"""
import os
import sys
import io
import traceback
from contextlib import redirect_stdout

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

os.environ["VNSTOCK_INTERACTIVE"] = "0"
os.environ["VNSTOCK_LANGUAGE"]    = "en"
os.environ["MPLCONFIGDIR"]        = "/home/runner/.config/matplotlib"
os.makedirs("/home/runner/.vnstock",           exist_ok=True)
os.makedirs("/home/runner/.config/matplotlib", exist_ok=True)


# ──────────────────────────────────────────────────────────────────────
# Version banner
# ──────────────────────────────────────────────────────────────────────
print("=" * 75)
print("  vnstock_data introspection diagnostic")
print("=" * 75)

try:
    import vnstock_data
    version = (getattr(vnstock_data, "__version__", None) or
               getattr(vnstock_data, "VERSION", None) or "unknown")
    print(f"  vnstock_data version: {version}")
    print(f"  vnstock_data path:    {vnstock_data.__file__}")
except Exception as e:
    print(f"  Could not detect vnstock_data: {e}")
    sys.exit(1)


# ──────────────────────────────────────────────────────────────────────
# Section 1: show_api()
# ──────────────────────────────────────────────────────────────────────
print("\n" + "=" * 75)
print("  SECTION 1 — show_api()")
print("=" * 75)

try:
    from vnstock_data import show_api
    print(f"  show_api signature: ", end="")
    import inspect
    try:
        print(inspect.signature(show_api))
    except (ValueError, TypeError):
        print("(unable to inspect)")

    print(f"  show_api __doc__:\n{(show_api.__doc__ or '(no docstring)')[:500]}")
    print()

    # Try calling with no args
    print("  --- Calling show_api() with no args ---")
    buf = io.StringIO()
    rv = None
    try:
        with redirect_stdout(buf):
            rv = show_api()
        out = buf.getvalue()
        print(out if out.strip() else "(no stdout output)")
        print(f"\n  [meta] return value type: {type(rv).__name__}")
        if rv is not None and not isinstance(rv, type(None)):
            print(f"  [meta] return value preview: {str(rv)[:500]}")
        print(f"  [meta] stdout length: {len(out)} chars, "
              f"{len(out.splitlines())} lines")
    except Exception as e:
        print(f"  ERROR calling show_api(): {type(e).__name__}: {e}")
        traceback.print_exc()

except ImportError as e:
    print(f"  ❌ show_api not importable: {e}")


# ──────────────────────────────────────────────────────────────────────
# Section 2: show_doc(target)
# ──────────────────────────────────────────────────────────────────────
print("\n" + "=" * 75)
print("  SECTION 2 — show_doc(target)")
print("=" * 75)

try:
    from vnstock_data import show_doc
    import inspect

    print(f"  show_doc signature: ", end="")
    try:
        print(inspect.signature(show_doc))
    except (ValueError, TypeError):
        print("(unable to inspect)")

    print(f"  show_doc __doc__:\n{(show_doc.__doc__ or '(no docstring)')[:500]}")
    print()

    # Targets to probe — covers tất cả API pipeline đang dùng
    string_targets = [
        # Quote
        "Quote", "Quote.history", "Quote.intraday", "Quote.price_depth",
        # Trading
        "Trading", "Trading.foreign_trade", "Trading.insider_deal",
        "Trading.prop_trade",
        # Finance
        "Finance", "Finance.ratio", "Finance.income_statement",
        "Finance.balance_sheet", "Finance.cash_flow",
        # Listing & Reference
        "Listing", "Listing.symbols_by_exchange",
        "Reference", "Reference.industry", "Reference.industry.list",
        # Analytics & TopStock
        "Analytics", "Analytics.valuation",
        "TopStock", "TopStock.gainer", "TopStock.loser",
    ]

    print(f"  --- Testing {len(string_targets)} string targets ---")
    for name in string_targets:
        print(f"\n  >>> show_doc({name!r})")
        try:
            buf = io.StringIO()
            rv  = None
            with redirect_stdout(buf):
                rv = show_doc(name)
            out = buf.getvalue().strip()
            if out:
                # Truncate dài quá
                print(out[:2000] + ("\n  ...(truncated)" if len(out) > 2000 else ""))
            else:
                print("  (no stdout)")
            if rv is not None:
                print(f"  [return] {type(rv).__name__}: {str(rv)[:300]}")
        except Exception as e:
            print(f"  ERROR: {type(e).__name__}: {e}")

    # Also try passing actual class/method objects (in case string parsing fails)
    print("\n  --- Testing object targets (truyền object thay vì string) ---")
    try:
        from vnstock_data import Quote, Finance, Trading, Reference
        object_targets = [
            ("Quote", Quote),
            ("Quote.history", Quote.history),
            ("Finance", Finance),
            ("Finance.cash_flow", Finance.cash_flow),
            ("Trading.foreign_trade", Trading.foreign_trade),
        ]
        for label, obj in object_targets:
            print(f"\n  >>> show_doc({label}) [object]")
            try:
                buf = io.StringIO()
                with redirect_stdout(buf):
                    show_doc(obj)
                out = buf.getvalue().strip()
                print(out[:1500] if out else "  (no stdout)")
            except Exception as e:
                print(f"  ERROR: {type(e).__name__}: {e}")
    except Exception as e:
        print(f"  Cannot import classes for object test: {e}")

except ImportError as e:
    print(f"  ❌ show_doc not importable: {e}")


# ──────────────────────────────────────────────────────────────────────
# Section 3: Fallback introspection bằng inspect + dir
# ──────────────────────────────────────────────────────────────────────
print("\n" + "=" * 75)
print("  SECTION 3 — Fallback: inspect.signature + __doc__")
print("  (đề phòng show_api/show_doc không đủ chi tiết)")
print("=" * 75)

import inspect
import vnstock_data

# List tất cả top-level public attrs của vnstock_data
public_attrs = [a for a in dir(vnstock_data) if not a.startswith("_")]
print(f"\n  vnstock_data public attrs ({len(public_attrs)}):")
for a in public_attrs:
    obj = getattr(vnstock_data, a)
    kind = type(obj).__name__
    print(f"    {a:30s} ({kind})")

# Deep-dive vào các class chính
CLASSES_TO_INSPECT = [
    "Quote", "Trading", "Finance", "Listing",
    "Reference", "Analytics", "TopStock",
]

for cls_name in CLASSES_TO_INSPECT:
    cls = getattr(vnstock_data, cls_name, None)
    if cls is None:
        print(f"\n  ⚠️  {cls_name} NOT FOUND in vnstock_data top-level")
        continue

    print(f"\n  === {cls_name} ===")
    print(f"    type: {type(cls).__name__}")

    # __init__ signature
    try:
        sig = inspect.signature(cls.__init__)
        print(f"    __init__{sig}")
    except (ValueError, TypeError) as e:
        print(f"    __init__: (cannot inspect: {e})")

    # __doc__
    doc = (cls.__doc__ or "").strip()
    if doc:
        first_line = doc.split("\n")[0]
        print(f"    __doc__ first line: {first_line[:120]}")

    # Public methods
    methods = []
    for m in dir(cls):
        if m.startswith("_"):
            continue
        attr = getattr(cls, m, None)
        if attr is None:
            continue
        kind = "method" if callable(attr) else type(attr).__name__
        methods.append((m, kind))

    print(f"    public members ({len(methods)}):")
    for m, kind in methods:
        # Try to get signature for methods
        sig_str = ""
        if kind == "method":
            try:
                sig_str = str(inspect.signature(getattr(cls, m)))
            except (ValueError, TypeError):
                sig_str = "(...)"
        print(f"      {m:30s} {kind:10s} {sig_str}")


# ──────────────────────────────────────────────────────────────────────
# Section 4: Reference.industry — nested namespace probe
# ──────────────────────────────────────────────────────────────────────
print("\n" + "=" * 75)
print("  SECTION 4 — Nested namespace: Reference().industry")
print("=" * 75)

try:
    from vnstock_data import Reference
    ref = Reference()
    industry = getattr(ref, "industry", None)
    if industry is None:
        print("  ⚠️  Reference().industry NOT FOUND")
    else:
        print(f"  Reference().industry type: {type(industry).__name__}")
        ind_members = [m for m in dir(industry) if not m.startswith("_")]
        print(f"  Members: {ind_members}")
        for m in ind_members:
            attr = getattr(industry, m)
            if callable(attr):
                try:
                    sig = inspect.signature(attr)
                    print(f"    .{m}{sig}")
                except (ValueError, TypeError):
                    print(f"    .{m}(...)")
except Exception as e:
    print(f"  ERROR: {e}")


print("\n" + "=" * 75)
print("  DONE — Copy output này về để confirm show_api/show_doc usefulness")
print("=" * 75)
