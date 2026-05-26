"""
scripts/debug_show_api.py
=========================
Dump vnstock_data introspection để confirm show_api/show_doc
trả về cái gì — có cây thư mục + field listing không.
"""
import os, sys, io
from contextlib import redirect_stdout

os.environ["VNSTOCK_INTERACTIVE"] = "0"
os.environ["VNSTOCK_LANGUAGE"]    = "en"

from vnstock_data import show_api, show_doc

# ── 1) show_api() — capture full output ─────────────────
print("=" * 70)
print("show_api() — FULL OUTPUT")
print("=" * 70)
buf = io.StringIO()
with redirect_stdout(buf):
    show_api()
out = buf.getvalue()
print(out)
print(f"\n[meta] show_api output length: {len(out)} chars, "
      f"{len(out.splitlines())} lines")

# ── 2) show_doc — thử với các tên API đang dùng ────────
print("\n" + "=" * 70)
print("show_doc() — test với các API trong pipeline")
print("=" * 70)

targets = [
    "Quote", "Quote.history", "Quote.intraday", "Quote.price_depth",
    "Trading", "Trading.foreign_trade", "Trading.insider_deal",
    "Finance", "Finance.ratio", "Finance.income_statement",
    "Finance.balance_sheet", "Finance.cash_flow",
    "Listing", "Listing.symbols_by_exchange",
    "Reference", "Reference.industry.list",
    "Analytics", "Analytics.valuation",
    "TopStock", "TopStock.gainer", "TopStock.loser",
]

for name in targets:
    print(f"\n--- show_doc({name!r}) ---")
    try:
        buf = io.StringIO()
        with redirect_stdout(buf):
            show_doc(name)
        out = buf.getvalue()
        print(out if out.strip() else "(empty output)")
    except Exception as e:
        print(f"ERROR: {type(e).__name__}: {e}")

# ── 3) Bonus: introspect bằng Python built-in ─────────────
# Đề phòng show_api/show_doc không đủ chi tiết
print("\n" + "=" * 70)
print("Fallback: inspect.signature + __doc__ cho từng class")
print("=" * 70)
import inspect, vnstock_data

for name in ("Quote", "Trading", "Finance", "Listing",
             "Reference", "Analytics", "TopStock"):
    cls = getattr(vnstock_data, name, None)
    if cls is None:
        print(f"\n{name}: NOT FOUND in vnstock_data")
        continue
    print(f"\n=== {name} ===")
    try:
        print(f"  __init__: {inspect.signature(cls.__init__)}")
    except (ValueError, TypeError):
        pass
    methods = [m for m in dir(cls)
               if not m.startswith("_") and callable(getattr(cls, m, None))]
    print(f"  methods: {methods}")
