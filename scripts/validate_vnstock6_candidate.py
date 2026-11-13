"""Validate a local Gen6 candidate and emit only a compact, secret-free summary."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--run-url", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    config = json.loads((ROOT / "config/vnstock6.json").read_text(encoding="utf-8"))
    status = json.loads((ROOT / "output/vnstock6/native-status.json").read_text(encoding="utf-8"))
    version = config["scoring_version"]
    serving = ROOT / "output/serving/vnstock6/current"
    required = [serving / "metadata.json", serving / "today" / f"{version}.json", serving / "buy" / f"{version}.json", serving / "history" / f"{version}.json", serving / "analysis" / f"{version}.json", serving / "charts" / version]
    missing = [path.relative_to(ROOT).as_posix() for path in required if not path.exists()]
    if missing:
        raise RuntimeError(f"Native candidate is incomplete: {missing}")
    today = json.loads((serving / "today" / f"{version}.json").read_text(encoding="utf-8"))
    rows = today.get("signals", [])
    if len(rows) < int(config["minimum_coverage"]):
        raise RuntimeError(f"Serving coverage is too low: {len(rows)}")
    invalid = [row for row in rows if row.get("market_source") not in {"SSI", "FHSC"} or row.get("pipeline_generation") != 6]
    if invalid:
        raise RuntimeError("Candidate contains rows without native SSI generation provenance")
    invalid_scoring = [row for row in rows if row.get("missing_data_policy") != "exclude_and_renormalize" or not isinstance(row.get("factor_status"), dict) or not isinstance(row.get("excluded_factors"), list) or not row.get("included_factors")]
    invalid_quant = [row for row in rows if row.get("calculation_engine") != "vnstock_quant" or row.get("calculation_version") != "1.0.0"]
    if invalid_quant:
        raise RuntimeError("Candidate contains rows not calculated by pinned vnstock_quant")
    if invalid_scoring:
        raise RuntimeError("Candidate contains rows without availability-aware scoring provenance")
    fundamental_scored = sum(row.get("fundamental_status") == "scored" for row in rows)
    growth_scored = sum(bool((row.get("factor_status") or {}).get("growth", {}).get("included")) for row in rows)
    refresh_path = ROOT / "output/vnstock6/fundamental-status.json"
    refresh_status = json.loads(refresh_path.read_text(encoding="utf-8")) if refresh_path.exists() else {}
    refresh_counts = refresh_status.get("counts", {})
    refresh_success = int(refresh_counts.get("success", 0))
    degraded = refresh_success == 0 or fundamental_scored == 0 or growth_scored == 0
    if degraded:
        unsafe = [
            row for row in rows
            if (row.get("factor_status") or {}).get("fundamental", {}).get("included")
            or (row.get("factor_status") or {}).get("growth", {}).get("included")
        ]
        if unsafe:
            raise RuntimeError("Unavailable fundamentals were included in candidate scoring")
    excluded_counts = {}
    for row in rows:
        for factor in row.get("excluded_factors", []):
            excluded_counts[factor] = excluded_counts.get(factor, 0) + 1
    summary = {
        "schema_version": 1, "candidate_status": "PASS_DEGRADED" if degraded else "PASS", "generated_at": datetime.now(timezone.utc).isoformat(),
        "run": {"id": args.run_id, "url": args.run_url}, "sources": status["sources"], "scoring_version": version,
        "cutover_date": config["cutover_date"], "universe_size": status["universe_size"],
        "successful_symbols": status["successful_symbols"], "serving_rows": len(rows),
        "failed_symbol_count": len(status["failed_symbols"]), "excluded_factor_counts": excluded_counts,
        "fundamental_scored_rows": fundamental_scored,
        "growth_scored_rows": growth_scored,
        "fundamental_refresh": {"status": "degraded" if degraded else "success", "counts": refresh_counts},
        "stages": {name: "success" for name in ("authenticate", "reference", "market_ingest", "scoring", "serving")},
    }
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False))


if __name__ == "__main__":
    main()
