"""Normalize Pandas/NumPy market data to strict JSON-safe Python primitives.

Missing/invalid numeric observations become null; no scoring signal is invented.
Unknown object types raise TypeError instead of being silently stringified.
"""

from __future__ import annotations

import json
import math
from collections.abc import Mapping
from datetime import date, datetime, time, timedelta
from typing import Any

import numpy as np
import pandas as pd


def to_json_safe(value: Any) -> Any:
    """Recursively convert external data into strict-JSON-safe values."""
    if value is None or value is pd.NA or value is pd.NaT:
        return None

    if isinstance(value, np.datetime64):
        return None if np.isnat(value) else pd.Timestamp(value).isoformat()
    if isinstance(value, np.timedelta64):
        return None if np.isnat(value) else pd.Timedelta(value).isoformat()
    if isinstance(value, (pd.Timestamp, datetime, date, time)):
        return value.isoformat()
    if isinstance(value, (pd.Timedelta, timedelta)):
        return pd.Timedelta(value).isoformat()

    if isinstance(value, Mapping):
        return {str(key): to_json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [to_json_safe(item) for item in value]
    if isinstance(value, np.ndarray):
        return to_json_safe(value[()]) if value.ndim == 0 else [to_json_safe(item) for item in value]
    if isinstance(value, (pd.Series, pd.Index)):
        return [to_json_safe(item) for item in value]

    if isinstance(value, np.generic):
        return to_json_safe(value.item())
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, str):
        return value
    raise TypeError(f"Unsupported JSON value type: {type(value).__name__}")


def dumps_json(value: Any, **kwargs: Any) -> str:
    """Serialize vendor payloads using strict JSON (never NaN/Infinity)."""
    return json.dumps(to_json_safe(value), allow_nan=False, **kwargs)
