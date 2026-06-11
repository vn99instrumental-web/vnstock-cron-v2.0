"""
debug_ff_room_vci.py — Tìm cột room % trong VCI Trading.foreign_trade()
Chạy qua debug.yml để xem tên cột chính xác.
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
os.environ["VNSTOCK_INTERACTIVE"] = "0"
os.environ["VNSTOCK_LANGUAGE"] = "en"

from vnstock_data import Trading
import pandas as pd

pd.set_option("display.max_columns", None)
pd.set_option("display.width", 200)

SYMBOLS = ["PNJ", "KBC", "GVR", "LDG"]

for sym in SYMBOLS:
    print(f"\n{'='*60}")
    print(f"  {sym} — VCI foreign_trade columns")
    print(f"{'='*60}")
    try:
        df = Trading(symbol=sym, source="VCI").foreign_trade(start="2026-06-01", end="2026-06-11")
        if df is None or df.empty:
            print(f"  EMPTY DataFrame")
            continue
        print(f"  Columns ({len(df.columns)}): {df.columns.tolist()}")
        room_cols = [c for c in df.columns if any(k in c.lower()
                     for k in ["room","pct","percent","ratio","remain","owned"])]
        print(f"  Room-related cols: {room_cols}")
        if room_cols:
            print(df[room_cols].tail(3).to_string())
        print(f"  Last 2 rows:")
        print(df.tail(2).to_string())
    except Exception as e:
        print(f"  ERROR: {e}")

print("\n=== DONE — Check output trên để tìm cột ff_room% ===")
