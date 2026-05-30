"""
scripts/debug_ta_api.py
========================
Xac dinh vnstock_ta Indicator tra ve Series hay scalar.
Quyet dinh cach tinh TA cho backtest (vectorized vs loop).
Trigger qua debug.yml: scripts/debug_ta_api.py
"""
import os, sys
os.environ["VNSTOCK_INTERACTIVE"] = "0"
os.environ["VNSTOCK_LANGUAGE"] = "en"

import pandas as pd
from vnstock_data import Quote
from vnstock_ta import Indicator

print("=" * 60)
print("  vnstock_ta Indicator API probe")
print("=" * 60)

df = Quote(source="VCI", symbol="HPG").history(length="12M", interval="1D")
print(f"\nOHLCV shape: {df.shape}, cols: {list(df.columns)}")
print(f"df index type: {type(df.index)}")

ta = Indicator(data=df)

def probe(name, fn):
    try:
        result = fn()
        rtype = type(result).__name__
        if isinstance(result, pd.Series):
            print(f"  {name:30s} -> Series len={len(result)} | last={result.iloc[-1]:.2f}")
        elif isinstance(result, pd.DataFrame):
            print(f"  {name:30s} -> DataFrame {result.shape} | cols={list(result.columns)}")
        elif isinstance(result, (int, float)):
            print(f"  {name:30s} -> scalar {result:.2f}")
        else:
            print(f"  {name:30s} -> {rtype}: {str(result)[:60]}")
    except Exception as e:
        print(f"  {name:30s} -> ERROR {type(e).__name__}: {e}")

print("\n-- Trend --")
probe("trend.ema(20)",        lambda: ta.trend.ema(length=20))
probe("trend.adx(14)",        lambda: ta.trend.adx(length=14))
probe("trend.supertrend",     lambda: ta.trend.supertrend(length=10, multiplier=3.0))

print("\n-- Momentum --")
probe("momentum.rsi(14)",     lambda: ta.momentum.rsi(length=14))
probe("momentum.macd",        lambda: ta.momentum.macd(fast=12, slow=26, signal=9))
probe("momentum.stoch",       lambda: ta.momentum.stoch(k=14, d=3, smooth_k=3))

print("\n-- Volatility --")
probe("volatility.bbands",    lambda: ta.volatility.bbands(length=20, std=2.0))
probe("volatility.atr(14)",   lambda: ta.volatility.atr(length=14))

print("\n-- Volume --")
probe("volume.obv()",         lambda: ta.volume.obv())
probe("volume.cmf(20)",       lambda: ta.volume.cmf(length=20))
probe("volume.mfi(14)",       lambda: ta.volume.mfi(length=14))

# Quan trong: thu pass df nho hon xem ema co tinh lai khong
print("\n-- Incremental test (df[:100]) --")
ta_small = Indicator(data=df.iloc[:100].copy())
probe("ema(20) on df[:100]",  lambda: ta_small.trend.ema(length=20))

print("\n" + "=" * 60)
print("  KET LUAN:")
print("  - Neu Series len=full -> vectorized (nhanh)")
print("  - Neu scalar -> phai loop tung ngay (cham)")
print("=" * 60)
