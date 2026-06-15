"""
cache.py — I/O helpers
=======================
Thay đổi từ bản cũ:
  - save_json/load_json tự tạo subdirectory nếu cần
  - Hỗ trợ paths như "finance/cache.json", "news/today_index.json"
  - API không thay đổi — không break code hiện tại
  - save_json: sanitize NaN/Inf → null trước khi dump (JSON hợp lệ)
"""
import csv
import json
import logging
import math
import os

import pandas as pd

from config import OUTPUT_DIR

log = logging.getLogger(__name__)
os.makedirs(OUTPUT_DIR, exist_ok=True)


def _resolve(filename: str) -> str:
    """Resolve full path, tạo parent dirs nếu cần."""
    path = os.path.join(OUTPUT_DIR, filename)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    return path


# Per-file locks để tránh race condition khi concurrent writes
import threading
_file_locks: dict[str, threading.Lock] = {}
_locks_meta = threading.Lock()

def _get_lock(path: str) -> threading.Lock:
    with _locks_meta:
        if path not in _file_locks:
            _file_locks[path] = threading.Lock()
        return _file_locks[path]


def _json_safe(o):
    """
    Đệ quy thay NaN/Inf (kể cả numpy float) → None để JSON hợp lệ.
    json.dump(default=str) KHÔNG xử lý NaN — sẽ ghi literal `NaN` (invalid JSON).
    """
    if isinstance(o, dict):
        return {k: _json_safe(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_json_safe(v) for v in o]
    try:
        if o != o:            # NaN (đúng cho cả float lẫn numpy float)
            return None
    except Exception:
        pass
    try:
        if math.isinf(o):     # ±Inf
            return None
    except (TypeError, ValueError):
        pass
    return o


def save_json(filename: str, data) -> None:
    path = _resolve(filename)
    lock = _get_lock(path)
    with lock:
        # Atomic write: ghi ra .tmp trước, rename sau
        tmp_path = path + ".tmp"
        try:
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(_json_safe(data), f, ensure_ascii=False, indent=2, default=str)
            os.replace(tmp_path, path)  # atomic on same filesystem
        except Exception:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
            raise
    log.info(f"  💾 {path}")


def load_json(filename: str):
    path = _resolve(filename)
    if not os.path.exists(path):
        log.warning(f"  ⚠️ Not found: {path}")
        return None
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except json.JSONDecodeError as e:
        log.error(f"  ❌ Corrupt JSON {path}: {e} — deleting and returning None")
        try:
            os.remove(path)
        except Exception:
            pass
        return None


def save_csv(filename: str, df: pd.DataFrame) -> None:
    path = _resolve(filename)
    df.to_csv(path, index=False, encoding="utf-8-sig")
    log.info(f"  💾 {path}")


def save_display_csv(filename: str, df: pd.DataFrame, meta: dict) -> None:
    """
    Lưu CSV với 5 dòng header:
      Row 1: field name
      Row 2: description
      Row 3: formula
      Row 4: baseline
      Row 5: unit  ← derive từ formatter.MONEY_COLS + meta["unit"]
    Sau đó data rows.

    unit tự động đúng khi đổi source:
      - Money fields: derive từ formatter.MONEY_COLS_MIL / MONEY_COLS_VND
      - Còn lại: lấy từ meta["unit"] trong indicators_meta.py
    """
    from utils.indicators_meta import get_indicator_unit

    path = _resolve(filename)
    cols = list(df.columns)

    header_rows = [
        ["field"]       + cols,
        ["description"] + [meta.get(c, {}).get("desc",     "") for c in cols],
        ["formula"]     + [meta.get(c, {}).get("formula",  "") for c in cols],
        ["baseline"]    + [meta.get(c, {}).get("baseline", "") for c in cols],
        ["unit"]        + [get_indicator_unit(c)                for c in cols],
    ]

    data_rows = []
    for _, row in df.iterrows():
        data_rows.append(
            [row.get("symbol", "")] + [row.get(c, "") for c in cols]
        )

    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        for header_row in header_rows:
            writer.writerow(header_row)
        for data_row in data_rows:
            writer.writerow(data_row)

    log.info(f"  💾 {path}")
