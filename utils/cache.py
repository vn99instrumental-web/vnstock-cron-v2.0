import os
import json
import logging
from datetime import datetime
from config import ICT, OUTPUT_DIR

log = logging.getLogger(__name__)

os.makedirs(OUTPUT_DIR, exist_ok=True)

def save_json(filename: str, data):
    """Lưu data ra output/filename.json"""
    path = os.path.join(OUTPUT_DIR, filename)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2, default=str)
    log.info(f"  💾 Saved: {path}")

def load_json(filename: str) -> dict | list | None:
    """Đọc output/filename.json"""
    path = os.path.join(OUTPUT_DIR, filename)
    if not os.path.exists(path):
        log.warning(f"  ⚠️ Not found: {path}")
        return None
    with open(path, encoding="utf-8") as f:
        return json.load(f)

def save_csv(filename: str, df):
    """Lưu DataFrame ra output/filename.csv"""
    import pandas as pd
    path = os.path.join(OUTPUT_DIR, filename)
    df.to_csv(path, index=False, encoding="utf-8-sig")
    log.info(f"  💾 Saved: {path}")
