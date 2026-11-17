"""Validate a local Gen6 candidate and emit only a compact, secret-free summary."""

from __future__ import annotations

import argparse
import json
import math
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def finite(value: object) -> float | None:
    try:
        number = float(value)
        return number if math.isfinite(number) else None
    except (TypeError, ValueError):
        return None


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--run-url", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    config = json.loads((ROOT / "config/vnstock6.json").read_text(encoding="utf-8"))
    status = json.loads((ROOT / "output/vnstock6/native-status.json").read_text(encoding="utf-8"))
    version = config["scoring_version"]
    versions = config.get("scoring_versions") or [version]
    serving = ROOT / "output/serving/vnstock6/current"
    required = [serving / "metadata.json"] + [
        serving / section / f"{profile}.json"
        for profile in versions
        for section in ("today", "buy", "history", "analysis")
    ] + [serving / "charts" / profile for profile in versions]
    missing = [path.relative_to(ROOT).as_posix() for path in required if not path.exists()]
    if missing:
        raise RuntimeError(f"Native candidate is incomplete: {missing}")
    rows_by_version = {
        profile: json.loads((serving / "today" / f"{profile}.json").read_text(encoding="utf-8")).get("signals", [])
        for profile in versions
    }
    low_coverage = {
        profile: len(profile_rows)
        for profile, profile_rows in rows_by_version.items()
        if len(profile_rows) < int(config["minimum_coverage"])
    }
    if low_coverage:
        raise RuntimeError(f"Serving coverage is too low: {low_coverage}")
    rows = [row for profile_rows in rows_by_version.values() for row in profile_rows]
    invalid = [row for row in rows if row.get("market_source") != "SSI" or row.get("pipeline_generation") != 6]
    if invalid:
        raise RuntimeError("Candidate contains rows without native SSI generation provenance")
    invalid_scoring = [row for row in rows if row.get("missing_data_policy") != "exclude_and_renormalize" or not isinstance(row.get("factor_status"), dict) or not isinstance(row.get("excluded_factors"), list) or not row.get("included_factors")]
    invalid_quant = [row for row in rows if row.get("calculation_engine") != "vnstock_quant+gen6_v4_profiles" or row.get("calculation_version") != "1.1.0"]
    if invalid_quant:
        raise RuntimeError("Candidate contains rows not calculated by pinned vnstock_quant")
    if invalid_scoring:
        raise RuntimeError("Candidate contains rows without availability-aware scoring provenance")
    fundamental_scored = sum(row.get("fundamental_status") == "scored" for row in rows)
    growth_scored = sum(bool((row.get("factor_status") or {}).get("growth", {}).get("included")) for row in rows)
    refresh_path = ROOT / "output/vnstock6/fundamental-status.json"
    refresh_status = json.loads(refresh_path.read_text(encoding="utf-8")) if refresh_path.exists() else {}
    refresh_counts = refresh_status.get("counts", {})
    degraded = fundamental_scored == 0 or growth_scored == 0
    refresh_state = "not_recorded" if not refresh_status else ("degraded" if degraded else "success")
    if degraded:
        unsafe = [
            row for row in rows
            if (row.get("factor_status") or {}).get("fundamental", {}).get("included")
            or (row.get("factor_status") or {}).get("growth", {}).get("included")
        ]
        if unsafe:
            raise RuntimeError("Unavailable fundamentals were included in candidate scoring")
    indicator_coverage = {
        key: sum(row.get(key) is not None for row in rows)
        for key in ("adx", "supertrend", "s_trend_st", "s_ff_net", "s_of_phasefix", "s_prop_5d", "s_insider", "s_depth_wall", "s_cf_core")
    }
    if indicator_coverage["adx"] < int(config["minimum_coverage"]) * len(versions) or indicator_coverage["supertrend"] < int(config["minimum_coverage"]) * len(versions):
        raise RuntimeError(f"Derived technical indicator coverage is too low: {indicator_coverage}")
    if indicator_coverage["s_cf_core"] < int(config["minimum_coverage"]) * len(versions):
        raise RuntimeError(f"Cash-flow overlay coverage is too low: {indicator_coverage}")
    quality_fields = (
        "price", "adtv_bil", "adtv_20d_bil", "ff_intra_net", "ff_intra_ratio",
        "rsi_14", "position_52w", "s_depth_wall",
    )
    field_coverage = {
        key: sum(finite(row.get(key)) is not None for row in rows) for key in quality_fields
    }
    minimum_rows = int(config["minimum_coverage"]) * len(versions)
    required_coverage = ("price", "adtv_bil", "adtv_20d_bil", "ff_intra_net", "s_depth_wall")
    low_quality_coverage = {
        key: field_coverage[key] for key in required_coverage if field_coverage[key] < minimum_rows
    }
    invalid_values: list[dict[str, object]] = []
    for row in rows:
        checks = {
            "price": (finite(row.get("price")), 0, None),
            "adtv_bil": (finite(row.get("adtv_bil")), 0, None),
            "adtv_20d_bil": (finite(row.get("adtv_20d_bil")), 0, None),
            "ff_intra_ratio": (finite(row.get("ff_intra_ratio")), -1, 1),
            "rsi_14": (finite(row.get("rsi_14")), 0, 100),
            "position_52w": (finite(row.get("position_52w")), 0, 1),
            "s_depth_wall": (finite(row.get("s_depth_wall")), -3, 3),
        }
        for key, (value, low, high) in checks.items():
            if value is not None and (value < low or (high is not None and value > high)):
                invalid_values.append({"symbol": row.get("symbol"), "version": row.get("scoring_version"), "field": key, "value": value})
    quality = {
        "schema_version": 1, "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": "FAIL" if low_quality_coverage or invalid_values else "PASS",
        "rows": len(rows), "minimum_required_rows": minimum_rows,
        "field_coverage": field_coverage, "low_coverage": low_quality_coverage,
        "invalid_values": invalid_values[:100],
        "contracts": {
            "adtv_bil": "current_or_last_session_turnover_bil_vnd",
            "adtv_20d_bil": "mean_20_session_turnover_bil_vnd",
            "ff_intra_net": "latest_session_foreign_net_vnd",
        },
    }
    quality_path = ROOT / "output/vnstock6/data-quality.json"
    quality_path.parent.mkdir(parents=True, exist_ok=True)
    quality_path.write_text(json.dumps(quality, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if low_quality_coverage or invalid_values:
        raise RuntimeError(f"Dashboard data-quality gate failed: coverage={low_quality_coverage}, invalid={len(invalid_values)}")
    excluded_counts = {}
    for row in rows:
        for factor in row.get("excluded_factors", []):
            excluded_counts[factor] = excluded_counts.get(factor, 0) + 1
    summary = {
        "schema_version": 1, "candidate_status": "PASS_DEGRADED" if degraded else "PASS", "generated_at": datetime.now(timezone.utc).isoformat(),
        "run": {"id": args.run_id, "url": args.run_url}, "sources": status["sources"], "scoring_version": version,
        "scoring_versions": versions,
        "cutover_date": config["cutover_date"], "universe_size": status["universe_size"],
        "successful_symbols": status["successful_symbols"], "serving_rows": len(rows),
        "serving_rows_by_version": {profile: len(profile_rows) for profile, profile_rows in rows_by_version.items()},
        "failed_symbol_count": len(status["failed_symbols"]), "excluded_factor_counts": excluded_counts,
        "fundamental_scored_rows": fundamental_scored,
        "growth_scored_rows": growth_scored,
        "indicator_coverage": indicator_coverage,
        "data_quality": quality,
        "fundamental_refresh": {"status": refresh_state, "counts": refresh_counts},
        "stages": {name: "success" for name in ("authenticate", "reference", "market_ingest", "scoring", "serving")},
    }
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False))


if __name__ == "__main__":
    main()
