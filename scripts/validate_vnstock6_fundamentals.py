"""Validate the committed Gen 6 fundamental cache without exposing credentials."""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CACHE = ROOT / "output" / "vnstock6" / "fundamental-factors.json"
STATUS = ROOT / "output" / "vnstock6" / "fundamental-status.json"


def has_forbidden_key(value: object, forbidden: tuple[str, ...]) -> bool:
    if isinstance(value, dict):
        return any(
            any(part in str(key).lower() for part in forbidden)
            or has_forbidden_key(item, forbidden)
            for key, item in value.items()
        )
    if isinstance(value, list):
        return any(has_forbidden_key(item, forbidden) for item in value)
    return False


def main() -> None:
    cache = json.loads(CACHE.read_text(encoding="utf-8"))
    status = json.loads(STATUS.read_text(encoding="utf-8"))
    if cache.get("source") != "FHSC" or cache.get("calculation_engine") != "vnstock_quant":
        raise ValueError("Unexpected fundamental cache provenance")
    symbols = cache.get("symbols") or {}
    if not symbols:
        raise ValueError("Fundamental cache is empty")
    if int(status.get("cache_symbols", 0)) != len(symbols):
        raise ValueError("Fundamental cache/status symbol count mismatch")
    forbidden = ("api_key", "api_secret", "token", "password", "authorization")
    if has_forbidden_key({"cache": cache, "status": status}, forbidden):
        raise ValueError("Fundamental artifacts contain a forbidden secret field")
    print(f"VNStock6 fundamental cache valid: {len(symbols)} symbols")


if __name__ == "__main__":
    main()
