"""Debug VCI prop_trade column names"""
import sys
sys.path.insert(0, '/opt/vnstock/.venv/lib/python3.12/site-packages')
from vnstock_data import Trading
from utils.helpers import start_str, today_str

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
