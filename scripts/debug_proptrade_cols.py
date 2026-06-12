"""Debug VCI prop_trade column names"""
import sys, os
sys.path.insert(0, '/opt/vnstock/.venv/lib/python3.12/site-packages')
# Thêm repo root vào path để import utils
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from vnstock_data import Trading
from datetime import datetime, timedelta

def start_str(days):
    return (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
def today_str():
    return datetime.now().strftime("%Y-%m-%d")

# Test với symbol thành công và thất bại
for sym in ["VHM", "DBD", "C32"]:
    try:
        df = Trading(symbol=sym, source="VCI").prop_trade(
            start=start_str(5), end=today_str())
        if df is not None and not df.empty:
            print(f"{sym}: columns = {df.columns.tolist()}")
            print(f"  sample row: {df.iloc[-1].to_dict()}")
        else:
            print(f"{sym}: empty DataFrame")
    except Exception as e:
        print(f"{sym}: ERROR {e}")
