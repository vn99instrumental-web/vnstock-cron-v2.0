"""Read-only, secret-free capability probe for the pinned generation-6 SSI runtime."""

from __future__ import annotations

import argparse
import json
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Callable

from vnstock import Market, Reference


def frame_summary(call: Callable[[], Any]) -> dict[str, Any]:
    try:
        frame = call()
        return {
            "status": "success",
            "rows": int(len(frame)),
            "columns": sorted(str(column) for column in frame.columns),
            "schema_changes": list(frame.attrs.get("schema_changes", [])),
        }
    except Exception as exc:  # typed vnstock errors vary by available route/tier
        return {
            "status": "unsupported",
            "error_type": type(exc).__name__,
            "error_code": getattr(exc, "code", None),
            "error_action": getattr(exc, "action", None),
        }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    start = (date.today() - timedelta(days=45)).isoformat()
    payload = {
        "schema_version": 1,
        "source": "SSI",
        "calls": {
            "reference.equity.list": frame_summary(lambda: Reference("ssi").equity.list()),
            "market.equity.ohlcv": frame_summary(
                lambda: Market("ssi").equity("FPT").ohlcv(start=start)
            ),
        },
    }
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
