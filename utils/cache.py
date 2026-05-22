import os
import json
import logging
import pandas as pd
from config import OUTPUT_DIR

log = logging.getLogger(__name__)
os.makedirs(OUTPUT_DIR, exist_ok=True)

def save_json(filename: str, data):
    path = os.path.join(OUTPUT_DIR, filename)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2, default=str)
    log.info(f"  💾 {path}")

def load_json(filename: str):
    path = os.path.join(OUTPUT_DIR, filename)
    if not os.path.exists(path):
        log.warning(f"  ⚠️ Not found: {path}")
        return None
    with open(path, encoding="utf-8") as f:
        return json.load(f)

def save_csv(filename: str, df: pd.DataFrame):
    path = os.path.join(OUTPUT_DIR, filename)
    df.to_csv(path, index=False, encoding="utf-8-sig")
    log.info(f"  💾 {path}")

def save_display_csv(filename: str, df: pd.DataFrame, meta: dict):
    """
    Lưu CSV với 4 dòng header:
      Row 1: field name (tên cột)
      Row 2: description
      Row 3: formula
      Row 4: baseline
    Sau đó data rows
    """
    path = os.path.join(OUTPUT_DIR, filename)
    cols = list(df.columns)

    # Build 4 header rows
    header_rows = [
        # Row 1: field names — dùng làm label cột
        ["field"] + cols,
        # Row 2: description
        ["description"] + [meta.get(c, {}).get("desc", "") for c in cols],
        # Row 3: formula
        ["formula"] + [meta.get(c, {}).get("formula", "") for c in cols],
        # Row 4: baseline
        ["baseline"] + [meta.get(c, {}).get("baseline", "") for c in cols],
    ]

    # Build data rows
    data_rows = []
    for _, row in df.iterrows():
        data_rows.append(
            [row.get("symbol", "")] + [row.get(c, "") for c in cols]
        )

    # Ghi thẳng ra file — không dùng pd.concat
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        import csv
        writer = csv.writer(f)
        for header_row in header_rows:
            writer.writerow(header_row)
        for data_row in data_rows:
            writer.writerow(data_row)

    log.info(f"  💾 {path}")
