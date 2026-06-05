"""Debug: xem cấu trúc thật của price_depth() API"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
os.environ["VNSTOCK_INTERACTIVE"] = "0"
os.environ["VNSTOCK_LANGUAGE"] = "en"

from vnstock_data import Quote
from utils.helpers import safe_run

for sym in ["BSR", "LPB", "VCB"]:
    df = safe_run(f"depth_{sym}", lambda s=sym: Quote(source="VCI", symbol=s).price_depth())
    if df is not None and not df.empty:
        print(f"\n{sym} — columns: {list(df.columns)}")
        print(df.to_string())
    else:
        print(f"\n{sym}: empty / None")
