"""Validate the secret-free VNStock generation-6 dashboard contract."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

SAFE_SYMBOL = re.compile(r"^[A-Z0-9]{1,10}$")
CAPABILITIES = {
    "metadata", "today", "buy", "history", "history_detail", "analysis", "ic", "chart"
}
FORBIDDEN_KEYS = {"api_key", "api_secret", "secret", "token", "password"}


def walk_keys(value: Any) -> set[str]:
    if isinstance(value, dict):
        keys = {str(key).lower() for key in value}
        for item in value.values():
            keys.update(walk_keys(item))
        return keys
    if isinstance(value, list):
        keys: set[str] = set()
        for item in value:
            keys.update(walk_keys(item))
        return keys
    return set()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--serving-root", required=True)
    args = parser.parse_args()

    manifest = json.loads(Path(args.manifest).read_text(encoding="utf-8"))
    if manifest.get("schema_version") != 1:
        raise ValueError("Unsupported VNStock 6 dashboard schema")
    if manifest.get("mode") != "bridge" or manifest.get("upstream") != "github":
        raise ValueError("Preview must declare the explicit GitHub bridge")
    if manifest.get("source") != "SSI":
        raise ValueError("VNStock 6 dashboard source must be SSI")

    symbols = manifest.get("symbols")
    if not isinstance(symbols, list) or not symbols or symbols != sorted(set(symbols)):
        raise ValueError("SSI symbol universe must be a non-empty sorted unique list")
    invalid = [symbol for symbol in symbols if not isinstance(symbol, str) or not SAFE_SYMBOL.fullmatch(symbol)]
    if invalid:
        raise ValueError(f"Invalid symbols in VNStock 6 dashboard manifest: {invalid[:5]}")

    capabilities = manifest.get("capabilities")
    if not isinstance(capabilities, dict) or set(capabilities) != CAPABILITIES:
        raise ValueError("VNStock 6 capability matrix is incomplete")
    if set(capabilities.values()) != {"bridge"}:
        raise ValueError("Preview capabilities must be explicit bridge values")

    forbidden = walk_keys(manifest) & FORBIDDEN_KEYS
    if forbidden:
        raise ValueError(f"Secret-like fields are forbidden in public manifest: {sorted(forbidden)}")

    serving_root = Path(args.serving_root)
    required = [serving_root / "metadata.json", serving_root / "ic.json"]
    required.extend(serving_root / section for section in ("today", "buy", "history", "analysis", "charts"))
    missing = [str(path) for path in required if not path.exists()]
    if missing:
        raise ValueError(f"Bridge upstream serving contract is incomplete: {missing}")

    print(
        f"VNStock 6 dashboard contract PASS: {len(symbols)} SSI symbols, "
        f"{len(capabilities)} dashboard capabilities"
    )


if __name__ == "__main__":
    main()