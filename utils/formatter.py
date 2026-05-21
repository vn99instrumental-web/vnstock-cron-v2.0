import pandas as pd
from datetime import datetime, timezone, timedelta

ICT = timezone(timedelta(hours=7))

def _to_float(val):
    if val is None:
        return ""
    try:
        f = float(val)
        return "" if pd.isna(f) else f
    except:
        return ""

def fmt_money_bil(val) -> float | str:
    """Đổi VND → tỷ đồng"""
    if val is None or val == "":
        return ""
    try:
        f = float(val)
        return round(f / 1e9, 2) if not pd.isna(f) else ""
    except:
        return ""

def fmt_num(val, decimals=2):
    if val is None or val == "":
        return ""
    try:
        f = float(val)
        return round(f, decimals) if not pd.isna(f) else ""
    except:
        return ""

# Các cột tiền (VND) → tỷ đồng
MONEY_COLS = [
    # Foreign flow
    "ff_buy_val_5d", "ff_sell_val_5d",
    "ff_net_val_5d", "ff_net_val_20d", "ff_room",
    # Income statement
    "is_revenue", "is_gross_profit",
    "is_net_profit", "is_ebitda",
    # Balance sheet
    "bs_total_assets", "bs_total_equity",
    "bs_short_debt", "bs_long_debt",
    # Foreign flow ranking
    "net_value", "accumulated_value",
]

# Các cột % → giữ nguyên, chỉ round
PCT_COLS = [
    "price_change_pct_1d", "volume_spike_20d_pct",
    "is_net_margin", "is_rev_growth", "is_profit_growth",
    "r_roe", "r_roa", "r_div_yield",
    "depth_buy_ratio", "intra_buy_ratio",
    "pe_percentile_5y", "pb_percentile_5y",
]

# Các cột ratio → round 2 chữ số
RATIO_COLS = [
    "r_pe", "r_pb", "r_eps", "r_bvps",
    "r_beta", "r_current_ratio",
    "r_quick_ratio", "r_debt_equity",
]

def clean_for_export(df: pd.DataFrame) -> pd.DataFrame:
    """
    Chuẩn hóa DataFrame trước khi export:
    - Cột tiền → tỷ đồng (đơn vị: tỷ VND)
    - Cột % → round 2
    - Cột ratio → round 2
    - NaN/None → ""
    - Thêm updated_at
    """
    df = df.copy()

    for col in df.columns:
        if col in MONEY_COLS:
            df[col] = df[col].apply(fmt_money_bil)
        elif col in PCT_COLS:
            df[col] = df[col].apply(lambda x: fmt_num(x, 2))
        elif col in RATIO_COLS:
            df[col] = df[col].apply(lambda x: fmt_num(x, 2))

    # Thêm updated_at
    df["updated_at"] = datetime.now(ICT).strftime("%Y-%m-%d %H:%M")

    # Fill NaN/None → ""
    df = df.fillna("").replace({float("nan"): ""})

    return df
