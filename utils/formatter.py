import pandas as pd

def fmt_money(val) -> float | str:
    """Đổi sang tỷ đồng, None → rỗng"""
    if val is None:
        return ""
    try:
        return round(float(val) / 1e9, 2)
    except:
        return ""

def fmt_num(val, decimals=2):
    if val is None:
        return ""
    try:
        return round(float(val), decimals)
    except:
        return ""

def clean_for_export(df: pd.DataFrame) -> pd.DataFrame:
    """
    Chuẩn hóa DataFrame trước khi export:
    - Cột tiền (value/val/revenue/profit) → tỷ đồng
    - NaN/None → ""
    - Thêm updated_at
    """
    from datetime import datetime, timezone, timedelta
    ICT = timezone(timedelta(hours=7))

    df = df.copy()

    # Cột tiền → tỷ đồng
    money_cols = [c for c in df.columns if any(
        x in c.lower() for x in
        ["val", "value", "revenue", "profit", "room"]
    )]
    for col in money_cols:
        df[col] = df[col].apply(fmt_money)

    # Thêm updated_at
    df["updated_at"] = datetime.now(ICT).strftime("%Y-%m-%d %H:%M")

    # Fill NaN
    df = df.fillna("").replace({float("nan"): ""})

    return df
