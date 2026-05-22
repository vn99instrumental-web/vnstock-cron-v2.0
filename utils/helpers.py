import os
import logging
import traceback
import pandas as pd
from datetime import datetime, timedelta
from config import ICT, MARKET_OPEN, MARKET_CLOSE, HOSE_CODE

log = logging.getLogger(__name__)

def now_ict() -> datetime:
    return datetime.now(ICT)

def is_market_open() -> bool:
    now = now_ict()
    if now.weekday() >= 5:
        return False
    open_t  = now.replace(
        hour=MARKET_OPEN[0], minute=MARKET_OPEN[1], second=0)
    close_t = now.replace(
        hour=MARKET_CLOSE[0], minute=MARKET_CLOSE[1], second=0)
    return open_t <= now <= close_t

def last_trading_date() -> str:
    d = now_ict().date()
    while d.weekday() >= 5:
        d -= timedelta(days=1)
    return d.strftime("%Y-%m-%d")

def today_str() -> str:
    return now_ict().strftime("%Y-%m-%d")

def start_str(days: int) -> str:
    return (now_ict() - timedelta(days=days)).strftime("%Y-%m-%d")

def safe_val(x, col=0):
    if x is None or (hasattr(x, "empty") and x.empty):
        return None
    try:
        val = x.iloc[-1, col] if isinstance(x, pd.DataFrame) \
              else x.iloc[-1]
        return round(float(val), 2)
    except Exception:
        return None

def safe_run(label: str, fn):
    try:
        result = fn()
        log.info(f"  ✅ {label}")
        return result
    except Exception as e:
        log.error(f"  ❌ {label}: {e}")
        traceback.print_exc()
        return None

def to_float(val) -> float | None:
    if val is None:
        return None
    try:
        f = float(val)
        return round(f, 2) if not pd.isna(f) else None
    except Exception:
        return None

# =====================================================
# Exchange map
# =====================================================
_exchange_map: dict = {}

def load_exchange_map():
    global _exchange_map
    from vnstock_data import Listing
    df = safe_run("symbols_by_exchange",
         lambda: Listing(source="VCI").symbols_by_exchange())
    if df is not None and not df.empty:
        _exchange_map = dict(zip(df["symbol"], df["exchange"]))
        log.info(f"  HSX={sum(1 for v in _exchange_map.values() if v=='HSX')}")

def get_exchange(symbol: str) -> str:
    return _exchange_map.get(symbol, "UNKNOWN")

def is_hsx(symbol: str) -> bool:
    return get_exchange(symbol) == HOSE_CODE
