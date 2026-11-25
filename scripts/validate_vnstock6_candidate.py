"""Validate a local Gen6 candidate and emit only a compact, secret-free summary."""

from __future__ import annotations

import argparse
import json
import math
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

QUALITY_FIELDS = (
    "price", "adtv_bil", "adtv_20d_bil", "ff_intra_net", "ff_intra_ratio",
    "ema20", "ema50", "ema200", "rsi_14", "atr_14", "obv",
    "position_52w", "s_depth_wall", "depth_average_trade_size",
    "order_book_bid_price", "order_book_bid_volume",
    "order_book_ask_price", "order_book_ask_volume", "growth_input_count",
)

# Source-backed same-session fields may legitimately be unavailable during an
# intraday snapshot. They remain visible in coverage and are validated for
# exact-date alignment whenever present, but missing values follow the
# pipeline's exclude-and-renormalize policy instead of blocking the release.
REQUIRED_QUALITY_COVERAGE = (
    "price", "adtv_bil", "adtv_20d_bil", "s_depth_wall",
    "depth_average_trade_size", "order_book_bid_price", "order_book_bid_volume",
    "order_book_ask_price", "order_book_ask_volume", "growth_input_count",
    "ema20", "ema50", "ema200", "rsi_14", "atr_14", "obv",
)
OPTIONAL_SOURCE_COVERAGE = ("ff_intra_net", "ff_intra_ratio")


def finite(value: object) -> float | None:
    try:
        number = float(value)
        return number if math.isfinite(number) else None
    except (TypeError, ValueError):
        return None


def dashboard_value(row: dict[str, object], key: str) -> object:
    value = row.get(key)
    if value is not None:
        return value
    breakdown = row.get("breakdown")
    return breakdown.get(key) if isinstance(breakdown, dict) else None

def source_lag_days(as_of: object, signal_date: object) -> int | None:
    try:
        source = datetime.fromisoformat(str(as_of)[:10]).date()
        signal = datetime.fromisoformat(str(signal_date)[:10]).date()
        return (signal - source).days
    except (TypeError, ValueError):
        return None


def github_command_escape(value: object) -> str:
    """Escape a value for a single-line GitHub workflow command."""
    return str(value).replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")


def write_failure_summary(
    output: Path, run_id: str, run_url: str, message: str, quality: dict[str, object],
) -> None:
    """Persist a secret-free failure artifact and surface the reason in check annotations."""
    payload = {
        "schema_version": 1, "candidate_status": "FAIL",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "run": {"id": run_id, "url": run_url},
        "error": message, "data_quality": quality,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"::error title=VNStock6 data-quality gate::{github_command_escape(message)}")


def fundamental_refresh_summary(
    refresh_status: dict[str, object], run_id: str, degraded: bool,
) -> dict[str, object]:
    empty_counts = {
        "updated": 0, "unchanged": 0, "failed": 0,
        "failed_preserved": 0, "material_changed": 0, "skipped_fresh": 0,
    }
    source_run_id = str(refresh_status.get("run_id") or "")
    belongs_to_run = bool(run_id) and source_run_id == str(run_id)
    if not refresh_status:
        state = "not_recorded"
    elif belongs_to_run:
        state = "degraded" if degraded else "success"
    else:
        state = "cache_reused"
    return {
        "status": state,
        "counts": dict(refresh_status.get("counts") or {}) if belongs_to_run else empty_counts,
        "update_detection": (
            refresh_status.get("update_detection") if belongs_to_run else "cache_reused"
        ),
        "source_run_id": source_run_id or None,
        "generated_at": refresh_status.get("generated_at"),
        "last_refresh_counts": dict(refresh_status.get("counts") or {}),
    }


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
    all_rows = [row for profile_rows in rows_by_version.values() for row in profile_rows]
    latest_rows_by_version = {}
    for profile, profile_rows in rows_by_version.items():
        latest_key = max(
            ((str(row.get("signal_date") or ""), str(row.get("snap_time") or "")) for row in profile_rows),
            default=("", ""),
        )
        latest_rows_by_version[profile] = [
            row for row in profile_rows
            if (str(row.get("signal_date") or ""), str(row.get("snap_time") or "")) == latest_key
        ]
    latest_low_coverage = {
        profile: len(profile_rows)
        for profile, profile_rows in latest_rows_by_version.items()
        if len(profile_rows) < int(config["minimum_coverage"])
    }
    if latest_low_coverage:
        raise RuntimeError(f"Latest snapshot coverage is too low: {latest_low_coverage}")
    rows = [row for profile_rows in latest_rows_by_version.values() for row in profile_rows]
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
    degraded = fundamental_scored == 0 or growth_scored == 0
    refresh_summary = fundamental_refresh_summary(refresh_status, args.run_id, degraded)
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
    field_coverage = {
        key: sum(finite(dashboard_value(row, key)) is not None for row in rows)
        for key in QUALITY_FIELDS
    }
    minimum_rows = int(config["minimum_coverage"]) * len(versions)
    low_quality_coverage = {
        key: field_coverage[key]
        for key in REQUIRED_QUALITY_COVERAGE
        if field_coverage[key] < minimum_rows
    }
    metadata_coverage = {
        key: sum(bool(str(dashboard_value(row, key) or "").strip()) for row in rows)
        for key in ("growth_period", "cash_flow_period")
    }
    low_quality_coverage.update({
        key: count for key, count in metadata_coverage.items() if count < minimum_rows
    })
    invalid_values: list[dict[str, object]] = []
    for row in rows:
        checks = {
            "price": (finite(dashboard_value(row, "price")), 0, None),
            "adtv_bil": (finite(dashboard_value(row, "adtv_bil")), 0, None),
            "adtv_20d_bil": (finite(dashboard_value(row, "adtv_20d_bil")), 0, None),
            "ff_intra_ratio": (finite(dashboard_value(row, "ff_intra_ratio")), -1, 1),
            "ema20": (finite(dashboard_value(row, "ema20")), 0, None),
            "ema50": (finite(dashboard_value(row, "ema50")), 0, None),
            "ema200": (finite(dashboard_value(row, "ema200")), 0, None),
            "rsi_14": (finite(dashboard_value(row, "rsi_14")), 0, 100),
            "atr_14": (finite(dashboard_value(row, "atr_14")), 0, None),
            "position_52w": (finite(dashboard_value(row, "position_52w")), 0, 1),
            "s_depth_wall": (finite(dashboard_value(row, "s_depth_wall")), -3, 3),
            "depth_average_trade_size": (finite(dashboard_value(row, "depth_average_trade_size")), 0, None),
            "order_book_bid_price": (finite(dashboard_value(row, "order_book_bid_price")), 0, None),
            "order_book_bid_volume": (finite(dashboard_value(row, "order_book_bid_volume")), 0, None),
            "order_book_ask_price": (finite(dashboard_value(row, "order_book_ask_price")), 0, None),
            "order_book_ask_volume": (finite(dashboard_value(row, "order_book_ask_volume")), 0, None),
        }
        for key, (value, low, high) in checks.items():
            if value is not None and (value < low or (high is not None and value > high)):
                invalid_values.append({"symbol": row.get("symbol"), "version": row.get("scoring_version"), "field": key, "value": value})
        growth_inputs = finite(dashboard_value(row, "growth_input_count"))
        if finite(dashboard_value(row, "s_growth_core")) is not None and (growth_inputs is None or not 1 <= growth_inputs <= 2):
            invalid_values.append({
                "symbol": row.get("symbol"), "version": row.get("scoring_version"),
                "field": "growth_input_count", "value": growth_inputs, "required": "1..2 when scored",
            })
        signal_date = str(row.get("signal_date") or "")
        foreign_as_of = str(dashboard_value(row, "foreign_as_of") or "")
        if finite(dashboard_value(row, "ff_intra_net")) is not None and foreign_as_of != signal_date:
            invalid_values.append({
                "symbol": row.get("symbol"), "version": row.get("scoring_version"),
                "field": "foreign_as_of", "value": foreign_as_of, "required": signal_date,
            })
        liquidity_source = str(dashboard_value(row, "liquidity_source") or "")
        turnover_as_of = str(dashboard_value(row, "turnover_as_of") or "")
        if liquidity_source == "SSI_SESSION_STATS" and turnover_as_of != signal_date:
            invalid_values.append({
                "symbol": row.get("symbol"), "version": row.get("scoring_version"),
                "field": "turnover_as_of", "value": turnover_as_of, "required": signal_date,
            })
        depth_date = str(dashboard_value(row, "depth_signal_date") or "")
        depth_score = finite(dashboard_value(row, "s_depth_wall"))
        depth_average = finite(dashboard_value(row, "depth_average_trade_size"))
        depth_status = str(dashboard_value(row, "depth_status") or "")
        depth_captured_at = str(dashboard_value(row, "depth_captured_at") or "")
        if depth_score is not None:
            if depth_date != signal_date:
                invalid_values.append({
                    "symbol": row.get("symbol"), "version": row.get("scoring_version"),
                    "field": "depth_signal_date", "value": depth_date, "required": signal_date,
                })
            if depth_average is None or depth_average <= 0 or depth_status not in {"live_scored", "same_session_cache"} or not depth_captured_at:
                invalid_values.append({
                    "symbol": row.get("symbol"), "version": row.get("scoring_version"),
                    "field": "depth_atomic_bundle", "value": {
                        "average_trade_size": depth_average, "status": depth_status,
                        "captured_at": depth_captured_at,
                    },
                })
    stale_proprietary = {
        str(row.get("symbol")) for row in rows
        if finite(dashboard_value(row, "s_prop_5d")) is not None
        and (source_lag_days(dashboard_value(row, "proprietary_as_of"), row.get("signal_date")) or 0) > 1
    }
    missing_insider_as_of = {
        str(row.get("symbol")) for row in rows
        if finite(dashboard_value(row, "s_insider")) is not None
        and not str(dashboard_value(row, "insider_as_of") or "").strip()
    }
    estimated_turnover = {
        str(row.get("symbol")) for row in rows
        if str(dashboard_value(row, "turnover_quality") or "") == "estimated"
    }
    partial_growth = {
        str(row.get("symbol")) for row in rows
        if finite(dashboard_value(row, "growth_input_count")) == 1
    }
    warnings = {
        "stale_proprietary_symbols": len(stale_proprietary),
        "missing_insider_as_of_symbols": len(missing_insider_as_of),
        "estimated_turnover_symbols": len(estimated_turnover),
        "single_input_growth_symbols": len(partial_growth),
    }
    quality = {
        "schema_version": 1, "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": "FAIL" if low_quality_coverage or invalid_values else "PASS",
        "rows": len(rows), "total_serving_rows": len(all_rows), "minimum_required_rows": minimum_rows,
        "field_coverage": field_coverage, "metadata_coverage": metadata_coverage,
        "low_coverage": low_quality_coverage, "warnings": warnings,
        "optional_source_coverage": {
            key: field_coverage[key] for key in OPTIONAL_SOURCE_COVERAGE
        },
        "invalid_values": invalid_values[:100],
        "contracts": {
            "adtv_bil": "current_or_last_session_turnover_bil_vnd",
            "adtv_20d_bil": "mean_20_session_turnover_bil_vnd",
            "ff_intra_net": "same_session_foreign_net_vnd",
            "temporal_alignment": "latest_snapshot_only_and_source_date_equals_signal_date",
            "optional_source_fields": "missing_is_null_and_excluded_from_scoring",
            "depth": "score_requires_atomic_same_session_book_and_average_trade_size",
            "fundamental_periods": "growth_and_cash_flow_period_required",
        },
    }
    quality_path = ROOT / "output/vnstock6/data-quality.json"
    quality_path.parent.mkdir(parents=True, exist_ok=True)
    quality_path.write_text(json.dumps(quality, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if low_quality_coverage or invalid_values:
        message = (
            f"Dashboard data-quality gate failed: coverage={low_quality_coverage}, "
            f"invalid={len(invalid_values)}"
        )
        write_failure_summary(Path(args.output), args.run_id, args.run_url, message, quality)
        raise RuntimeError(message)
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
        "fundamental_refresh": refresh_summary,
        "stages": {name: "success" for name in ("authenticate", "reference", "market_ingest", "scoring", "serving")},
    }
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False))


if __name__ == "__main__":
    main()
