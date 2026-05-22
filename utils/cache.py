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

def save_display_csv(filename: str, df: pd.DataFrame,
                     meta: dict):
    """
    Lưu CSV với 4 dòng header:
      Row 1: field name
      Row 2: description
      Row 3: formula
      Row 4: baseline
    Sau đó data rows
    """
    path = os.path.join(OUTPUT_DIR, filename)
    cols = list(df.columns)

    desc_row     = {c: meta.get(c, {}).get("desc",     "") for c in cols}
    formula_row  = {c: meta.get(c, {}).get("formula",  "") for c in cols}
    baseline_row = {c: meta.get(c, {}).get("baseline", "") for c in cols}

    header_df = pd.DataFrame([
        desc_row,
        formula_row,
        baseline_row,
    ])
    header_df.insert(0, "field", ["description", "formula", "baseline"])

    data_df = df.copy()
    data_df.insert(0, "field", data_df["symbol"] \
                   if "symbol" in data_df.columns else "")

    combined = pd.concat(
        [header_df, data_df.rename(columns={"symbol": "field"})],
        ignore_index=True
    )
    combined.to_csv(path, index=False, encoding="utf-8-sig")
    log.info(f"  💾 {path}")
