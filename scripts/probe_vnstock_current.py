"""Read-only probe for the existing VCI production snapshot and runtime metadata."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any


def package_version(name: str) -> str:
    try:
        return version(name)
    except PackageNotFoundError:
        return "unknown"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    rows: Any = json.loads(Path(args.input).read_text(encoding="utf-8"))
    if not isinstance(rows, list) or not all(isinstance(row, dict) for row in rows):
        raise ValueError("Current production industry snapshot must be a list of objects")

    symbols = sorted({str(row.get("symbol", "")).strip().upper() for row in rows if str(row.get("symbol", "")).strip()})
    exchanges = sorted({str(row.get("exchange", "")).strip().upper() for row in rows if str(row.get("exchange", "")).strip()})
    columns = sorted({str(key) for row in rows for key in row})
    payload = {
        "schema_version": 1,
        "status": "ok",
        "generation": "current",
        "source": "VCI",
        "data_origin": "production-snapshot",
        "package": "vnstock_data",
        "package_version": package_version("vnstock_data"),
        "observed_at": datetime.now(timezone.utc).isoformat(),
        "reference": {
            "rows": len(rows),
            "symbols": symbols,
            "exchanges": exchanges,
            "columns": columns,
            "fpt_present": "FPT" in symbols,
        },
    }
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Current VCI production snapshot: {len(symbols)} unique symbols")


if __name__ == "__main__":
    main()
