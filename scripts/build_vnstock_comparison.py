"""Merge probe artifacts into public, secret-free comparison and dashboard snapshots."""

from __future__ import annotations

import argparse
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def load_probe(path: str, expected_generation: str) -> dict[str, Any]:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if value.get("schema_version") != 1 or value.get("generation") != expected_generation:
        raise ValueError(f"Unexpected probe schema or generation in {path}")
    reference = value.get("reference")
    if not isinstance(reference, dict) or not isinstance(reference.get("symbols"), list):
        raise ValueError(f"Probe reference is invalid in {path}")
    return value


def public_probe(probe: dict[str, Any]) -> dict[str, Any]:
    reference = probe["reference"]
    return {
        key: value for key, value in probe.items() if key != "reference"
    } | {
        "reference": {
            "rows": reference["rows"],
            "unique_symbols": len(set(reference["symbols"])),
            "exchanges": reference["exchanges"],
            "columns": reference["columns"],
            "fpt_present": reference["fpt_present"],
        }
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--current", required=True)
    parser.add_argument("--preview", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--dashboard-output", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--run-url", required=True)
    args = parser.parse_args()

    current = load_probe(args.current, "current")
    preview = load_probe(args.preview, "6-preview")
    current_symbols = set(current["reference"]["symbols"])
    preview_symbols = set(preview["reference"]["symbols"])
    invalid_symbols = sorted(
        symbol for symbol in preview_symbols
        if not re.fullmatch(r"[A-Z0-9]{1,10}", symbol)
    )
    if invalid_symbols:
        raise ValueError(
            f"Generation-6 reference contains invalid symbols: {invalid_symbols[:5]}"
        )

    union = current_symbols | preview_symbols
    overlap = current_symbols & preview_symbols
    generated_at = datetime.now(timezone.utc).isoformat()
    payload = {
        "schema_version": 1,
        "generated_at": generated_at,
        "run": {"id": args.run_id, "url": args.run_url, "status": "success"},
        "current": public_probe(current),
        "preview": public_probe(preview),
        "comparison": {
            "overlap_symbols": len(overlap),
            "union_symbols": len(union),
            "jaccard_percent": round(100 * len(overlap) / len(union), 2) if union else 0,
            "only_current_count": len(current_symbols - preview_symbols),
            "only_preview_count": len(preview_symbols - current_symbols),
            "only_current_sample": sorted(current_symbols - preview_symbols)[:10],
            "only_preview_sample": sorted(preview_symbols - current_symbols)[:10],
        },
        "notes": [
            "The current and generation-6 probes run in separate Python environments.",
            "The current side reads the production VCI snapshot; generation 6 calls SSI Open API live.",
            "This snapshot compares reference universes and does not claim native generation-6 scoring.",
            "Source differences can contribute to differences observed between the two generations.",
        ],
    }
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    dashboard = {
        "schema_version": 1,
        "mode": "bridge",
        "generated_at": generated_at,
        "source": "SSI",
        "package_version": preview["package_version"],
        "oapi_version": preview["oapi_version"],
        "upstream": "github",
        "symbols": sorted(preview_symbols),
        "capabilities": {
            "metadata": "bridge",
            "today": "bridge",
            "buy": "bridge",
            "history": "bridge",
            "history_detail": "bridge",
            "analysis": "bridge",
            "ic": "bridge",
            "chart": "bridge",
        },
        "flow": {
            "run_id": args.run_id,
            "run_url": args.run_url,
            "stages": [
                {"name": "authenticate", "status": "success", "mode": "native"},
                {"name": "reference", "status": "success", "mode": "native"},
                {"name": "market_ingest", "status": "pending", "mode": "native"},
                {"name": "scoring", "status": "pending", "mode": "native"},
                {"name": "serving", "status": "success", "mode": "bridge"},
            ],
        },
    }
    dashboard_output = Path(args.dashboard_output)
    dashboard_output.parent.mkdir(parents=True, exist_ok=True)
    dashboard_output.write_text(
        json.dumps(dashboard, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"Comparison snapshot: {len(overlap)}/{len(union)} overlapping symbols")
    print(f"Generation-6 dashboard bridge: {len(preview_symbols)} SSI symbols")


if __name__ == "__main__":
    main()