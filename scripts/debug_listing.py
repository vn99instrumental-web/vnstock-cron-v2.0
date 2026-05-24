"""
scripts/debug_listing.py
========================
Chạy 1 lần để xác nhận columns của Listing.symbols_by_exchange()
và Reference.industry.list() — để biết cách join symbol → icb_name.

Usage:
  python scripts/debug_listing.py
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
os.environ["VNSTOCK_INTERACTIVE"] = "0"
os.environ["VNSTOCK_LANGUAGE"]    = "en"

try:
    from vnstock_data import Listing, Reference
except ImportError:
    print("vnstock_data not available")
    sys.exit(0)

print("=== Listing.symbols_by_exchange(exchange='HSX') ===")
try:
    df = Listing(source="VCI").symbols_by_exchange(exchange="HSX")
    print(f"Shape: {df.shape}")
    print(f"Columns: {list(df.columns)}")
    print(f"First 3 rows:\n{df.head(3).to_string()}")
except Exception as e:
    print(f"ERROR: {e}")

print()
print("=== Reference().industry.list() ===")
try:
    df2 = Reference().industry.list()
    print(f"Shape: {df2.shape}")
    print(f"Columns: {list(df2.columns)}")
    print(f"First 5 rows:\n{df2.head(5).to_string()}")
except Exception as e:
    print(f"ERROR: {e}")

print()
print("=== Listing.symbols_by_exchange() — no exchange param ===")
try:
    df3 = Listing(source="VCI").symbols_by_exchange()
    print(f"Shape: {df3.shape}")
    print(f"Columns: {list(df3.columns)}")
    print(f"First 3:\n{df3.head(3).to_string()}")
except Exception as e:
    print(f"ERROR: {e}")
