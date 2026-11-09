"""Read-only probe for vnstock generation 6 with SSI Open API."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from importlib.metadata import version
from pathlib import Path

from vnstock import Reference


def find_column(columns: list[str], candidates: tuple[str, ...]) -> str | None:
    normalized = {column.lower(): column for column in columns}
    return next((normalized[name] for name in candidates if name in normalized), None)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    frame = Reference("ssi").equity.list()
    columns = [str(column) for column in frame.columns]
    symbol_column = find_column(columns, ("symbol", "ticker", "code", "stocksymbol"))
    exchange_column = find_column(columns, ("exchange", "market", "comgroupcode", "exchangeid"))
    if not symbol_column:
        raise RuntimeError(f"Generation-6 SSI listing has no symbol column: {columns}")

    symbols = sorted({str(value).strip().upper() for value in frame[symbol_column].dropna() if str(value).strip()})
    exchanges = (
        sorted({str(value).strip().upper() for value in frame[exchange_column].dropna() if str(value).strip()})
        if exchange_column
        else []
    )
    payload = {
        "schema_version": 1,
        "status": "ok",
        "generation": "6-preview",
        "source": "SSI",
        "package": "vnstock",
        "package_version": version("vnstock"),
        "oapi_version": version("vnstock-oapi"),
        "observed_at": datetime.now(timezone.utc).isoformat(),
        "reference": {
            "rows": int(len(frame)),
            "symbols": symbols,
            "exchanges": exchanges,
            "columns": sorted(columns),
            "fpt_present": "FPT" in symbols,
        },
    }
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Generation 6 SSI reference: {len(symbols)} unique symbols")


if __name__ == "__main__":
    main()
