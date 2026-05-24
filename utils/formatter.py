"""
formatter.py
============
Fix: KBS trả về đơn vị TRIỆU ĐỒNG cho income/balance/cashflow.
     fmt_money_bil phải chia 1e3 (triệu → tỷ), không phải 1e9 (đồng → tỷ).

     Các cols từ API khác (ff_*, market_cap, deal_value_avg_5d)
     vẫn là đơn vị ĐỒNG → chia 1e9.
"""
import pandas as pd
from datetime import datetime, timezone, timedelta

ICT = timezone(timedelta(hours=7))

# ─── ĐỒNG → tỷ (chia 1e9) ─────────────────────────────────────────────────
# FF values từ CafeF/VCI: đơn vị VND (đồng)
MONEY_COLS_VND = [
    "ff_buy_val_5d", "ff_sell_val_5d",
    "ff_net_val_5d", "ff_net_val_20d", "ff_room",
    "net_value", "accumulated_value",
    "market_cap",
    "deal_value_avg_5d",
]

# ─── TRIỆU ĐỒNG → tỷ (chia 1e3) ──────────────────────────────────────────
# KBS Finance: đơn vị triệu VND
MONEY_COLS_MIL = [
    "is_revenue", "is_gross_profit",
    "is_net_profit", "is_operating_profit", "is_ebitda",
    "bs_total_assets", "bs_equity",
    "bs_total_liab", "bs_short_debt", "bs_long_debt",
    "cf_operating", "cf_investing",
    "cf_financing", "cf_free",
]

# Union cho backward compat (ai check `col in MONEY_COLS`)
MONEY_COLS = MONEY_COLS_VND + MONEY_COLS_MIL

PCT_COLS = [
    "price_change_pct_1d", "volume_spike_20d_pct",
    "is_net_margin", "is_rev_growth", "is_profit_growth",
    "r_roe", "r_roa", "r_div_yield", "r_gross_margin",
    "r_net_margin", "r_ebit_margin",
    "depth_buy_ratio", "intra_buy_ratio",
    "pe_percentile_5y", "pb_percentile_5y",
    "ema_cross_pct", "price_vs_ema20_pct",
    "ff_consistency",
    "atr_pct",
]

RATIO_COLS = [
    "r_pe", "r_pb", "r_eps", "r_bvps",
    "r_beta", "r_quick_ratio", "r_interest_cov",
    "r_ev_ebitda", "r_current_ratio", "r_debt_equity",
    "pe_vs_industry", "pb_vs_industry",
    "cf_quality_ratio", "bb_position", "ff_trend",
]


def fmt_money_vnd(val):
    """VND (đồng) → tỷ đồng."""
    if val is None or val == "":
        return ""
    try:
        f = float(val)
        return round(f / 1e9, 2) if not pd.isna(f) else ""
    except Exception:
        return ""


def fmt_money_mil(val):
    """Triệu VND → tỷ đồng."""
    if val is None or val == "":
        return ""
    try:
        f = float(val)
        return round(f / 1e3, 2) if not pd.isna(f) else ""
    except Exception:
        return ""


# Alias giữ backward compat
def fmt_money_bil(val):
    """Legacy alias — assumes VND input → tỷ."""
    return fmt_money_vnd(val)


def fmt_num(val, decimals=2):
    if val is None or val == "":
        return ""
    try:
        f = float(val)
        return round(f, decimals) if not pd.isna(f) else ""
    except Exception:
        return ""


def clean_for_export(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    for col in df.columns:
        if col in MONEY_COLS_MIL:
            df[col] = df[col].apply(fmt_money_mil)   # triệu → tỷ
        elif col in MONEY_COLS_VND:
            df[col] = df[col].apply(fmt_money_vnd)   # đồng → tỷ
        elif col in PCT_COLS:
            df[col] = df[col].apply(lambda x: fmt_num(x, 2))
        elif col in RATIO_COLS:
            df[col] = df[col].apply(lambda x: fmt_num(x, 2))
        elif df[col].dtype in ["float64", "float32"]:
            df[col] = df[col].apply(lambda x: fmt_num(x, 2))
    df["updated_at"] = datetime.now(ICT).strftime("%Y-%m-%d %H:%M")
    df = df.fillna("").replace({float("nan"): ""})
    return df
