"""
debug_orderbook.py — Test TẤT CẢ khả năng lấy lệnh chờ (bid/ask order book)
Chạy 1 lần để biết nguồn nào trả về order book thật.

LƯU Ý: chạy TRONG GIỜ GD (9:00-15:00) — price_depth raise ValueError pre-market.
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
os.environ["VNSTOCK_INTERACTIVE"] = "0"
os.environ["VNSTOCK_LANGUAGE"]    = "en"

import pandas as pd
pd.set_option("display.max_columns", None)
pd.set_option("display.width", 200)

SYM = "BSR"

def show(label, fn):
    print("\n" + "="*70)
    print(f"### {label}")
    print("="*70)
    try:
        df = fn()
        if df is None:
            print("  → None")
        elif isinstance(df, pd.DataFrame):
            if df.empty:
                print("  → EMPTY DataFrame")
            else:
                print(f"  → columns: {list(df.columns)}")
                print(f"  → shape: {df.shape}")
                print(df.head(8).to_string())
        else:
            print(f"  → type={type(df).__name__}: {str(df)[:300]}")
    except Exception as e:
        print(f"  → ERROR {type(e).__name__}: {str(e)[:200]}")

# ─────────────────────────────────────────────────────────────
# CASE 1: VCI price_depth (đã biết — volume theo giá, KHÔNG phải order book)
# ─────────────────────────────────────────────────────────────
def c1():
    from vnstock_data import Quote
    return Quote(source="VCI", symbol=SYM).price_depth()
show("1. vnstock_data Quote(VCI).price_depth()", c1)

# ─────────────────────────────────────────────────────────────
# CASE 2: VCI price_depth với levels param
# ─────────────────────────────────────────────────────────────
def c2():
    from vnstock_data import Quote
    return Quote(source="VCI", symbol=SYM).price_depth(levels=5)
show("2. Quote(VCI).price_depth(levels=5)", c2)

# ─────────────────────────────────────────────────────────────
# CASE 3: TCBS price_depth (docs nói TCBS có real-time order book)
# ─────────────────────────────────────────────────────────────
def c3():
    from vnstock_data import Quote
    return Quote(source="TCBS", symbol=SYM).price_depth()
show("3. Quote(TCBS).price_depth()", c3)

# ─────────────────────────────────────────────────────────────
# CASE 4: public vnstock (PyPI) thay vì vnstock_data — VCI
# ─────────────────────────────────────────────────────────────
def c4():
    from vnstock import Quote as PubQuote
    return PubQuote(source="vci", symbol=SYM).price_depth()
show("4. vnstock(public) Quote(vci).price_depth()", c4)

# ─────────────────────────────────────────────────────────────
# CASE 5: public vnstock — TCBS
# ─────────────────────────────────────────────────────────────
def c5():
    from vnstock import Quote as PubQuote
    return PubQuote(source="tcbs", symbol=SYM).price_depth()
show("5. vnstock(public) Quote(tcbs).price_depth()", c5)

# ─────────────────────────────────────────────────────────────
# CASE 6: Trading.price_board (bảng giá — thường có dư mua/dư bán 3 mức)
# ─────────────────────────────────────────────────────────────
def c6():
    from vnstock_data import Trading
    return Trading(source="VCI").price_board([SYM])
show("6. vnstock_data Trading(VCI).price_board([SYM])", c6)

# ─────────────────────────────────────────────────────────────
# CASE 7: public vnstock Trading.price_board (đã biết bị RetryError với VCI?)
# ─────────────────────────────────────────────────────────────
def c7():
    from vnstock import Trading as PubTrading
    return PubTrading(source="vci").price_board([SYM])
show("7. vnstock(public) Trading(vci).price_board([SYM])", c7)

# ─────────────────────────────────────────────────────────────
# CASE 8: TCBS Trading price_board
# ─────────────────────────────────────────────────────────────
def c8():
    from vnstock import Trading as PubTrading
    return PubTrading(source="tcbs").price_board([SYM])
show("8. vnstock(public) Trading(tcbs).price_board([SYM])", c8)

# ─────────────────────────────────────────────────────────────
# CASE 9: liệt kê methods của Quote để xem còn hàm nào liên quan order book
# ─────────────────────────────────────────────────────────────
print("\n" + "="*70)
print("### 9. Methods của Quote(VCI) — tìm hàm order book khác")
print("="*70)
try:
    from vnstock_data import Quote
    q = Quote(source="VCI", symbol=SYM)
    methods = [m for m in dir(q) if not m.startswith("_") and callable(getattr(q, m))]
    print("  Quote methods:", methods)
except Exception as e:
    print(f"  ERROR: {e}")

# ─────────────────────────────────────────────────────────────
# CASE 10: methods của Trading
# ─────────────────────────────────────────────────────────────
print("\n" + "="*70)
print("### 10. Methods của Trading(VCI)")
print("="*70)
try:
    from vnstock_data import Trading
    t = Trading(source="VCI")
    methods = [m for m in dir(t) if not m.startswith("_") and callable(getattr(t, m))]
    print("  Trading methods:", methods)
except Exception as e:
    print(f"  ERROR: {e}")

print("\n=== DONE — tìm case nào có cột bid_price/ask_price hoặc dư mua/dư bán ===")
