"""Merge two probe artifacts into the public, secret-free comparison snapshot."""

from __future__ import annotations

import argparse
import json
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
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--run-url", required=True)
    args = parser.parse_args()

    current = load_probe(args.current, "current")
    preview = load_probe(args.preview, "6-preview")
    current_symbols = set(current["reference"]["symbols"])
    preview_symbols = set(preview["reference"]["symbols"])
    union = current_symbols | preview_symbols
    overlap = current_symbols & preview_symbols

    payload = {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
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
            "Hai job chạy song song trong môi trường Python tách biệt.",
            "Đây là đối chiếu danh mục mã tham chiếu; không so sánh hay thay đổi scoring production.",
            "Nguồn hiện tại là VCI, bản Gen 6 preview dùng SSI Open API nên chênh lệch không chỉ do phiên bản thư viện.",
        ],
    }
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Comparison snapshot: {len(overlap)}/{len(union)} overlapping symbols")


if __name__ == "__main__":
    main()
