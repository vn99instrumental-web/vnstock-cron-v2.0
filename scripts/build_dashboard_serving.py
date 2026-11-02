#!/usr/bin/env python3
"""Build read-only dashboard snapshots from Supabase for GitHub/Vercel shadow serving.

This command is intentionally independent from every scoring/cron workflow. It only
reads the existing Supabase serving tables/views and atomically replaces
``output/serving/current`` after all validation checks pass.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import shutil
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

try:
    import requests
except ModuleNotFoundError:
    import urllib.error
    import urllib.parse
    import urllib.request

    class _UrllibResponse:
        def __init__(self, status_code: int, body: bytes):
            self.status_code = status_code
            self.text = body.decode("utf-8", errors="replace")

        def json(self):
            return json.loads(self.text)

    class _UrllibRequests:
        RequestException = urllib.error.URLError

        @staticmethod
        def get(url, *, params, headers, timeout):
            target = url + "?" + urllib.parse.urlencode(params)
            request = urllib.request.Request(target, headers=headers, method="GET")
            try:
                with urllib.request.urlopen(request, timeout=timeout) as response:
                    return _UrllibResponse(response.status, response.read())
            except urllib.error.HTTPError as exc:
                return _UrllibResponse(exc.code, exc.read())

    requests = _UrllibRequests()

ROOT = Path(__file__).resolve().parent.parent
SERVING_ROOT = ROOT / "output" / "serving"
REVIEW_CONFIG = ROOT / "config" / "scoring" / "review_versions.json"
ICT = timezone(timedelta(hours=7))
PAGE_SIZE = 1000
MAX_FILE_BYTES = 20 * 1024 * 1024
BUY_DECISIONS = {"BUY", "STRONG BUY"}

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("dashboard_serving")


def _compact_json(path: Path, value: Any) -> dict[str, Any]:
    path.parent.mkdir(parents=True, exist_ok=True)
    body = json.dumps(value, ensure_ascii=False, separators=(",", ":"), default=str).encode("utf-8")
    if len(body) > MAX_FILE_BYTES:
        raise RuntimeError(f"Serving file exceeds {MAX_FILE_BYTES // 1024 // 1024} MiB: {path} ({len(body)} bytes)")
    path.write_bytes(body)
    return {
        "path": path.as_posix(),
        "bytes": len(body),
        "sha256": hashlib.sha256(body).hexdigest(),
    }


class SupabaseReader:
    def __init__(self, url: str, key: str):
        if requests is None:
            raise RuntimeError("Missing requests dependency")
        self.rest = url.rstrip("/") + "/rest/v1"
        self.headers = {"apikey": key, "Authorization": f"Bearer {key}"}

    def rows(
        self,
        table: str,
        *,
        select: str = "*",
        filters: dict[str, str] | None = None,
        order: str | None = None,
        limit: int | None = None,
        paginate: bool = True,
    ) -> list[dict[str, Any]]:
        params: dict[str, str] = {"select": select}
        params.update(filters or {})
        if order:
            params["order"] = order
        output: list[dict[str, Any]] = []
        offset = 0
        while True:
            chunk_limit = min(PAGE_SIZE, limit - len(output)) if limit is not None else PAGE_SIZE
            if chunk_limit <= 0:
                break
            page_params = {**params, "limit": str(chunk_limit), "offset": str(offset)}
            response = None
            for attempt in range(1, 5):
                try:
                    response = requests.get(
                        f"{self.rest}/{table}", params=page_params, headers=self.headers, timeout=120,
                    )
                except requests.RequestException as exc:
                    if attempt == 4:
                        raise RuntimeError(f"GET {table} failed: {type(exc).__name__}") from exc
                    time.sleep(2**attempt)
                    continue
                if response.status_code < 300:
                    break
                if response.status_code < 500 and response.status_code != 429:
                    raise RuntimeError(f"GET {table} HTTP {response.status_code}: {response.text[:300]}")
                if attempt == 4:
                    raise RuntimeError(f"GET {table} HTTP {response.status_code}: {response.text[:300]}")
                time.sleep(2**attempt)
            assert response is not None
            page = response.json()
            if not isinstance(page, list):
                raise RuntimeError(f"GET {table} returned a non-list payload")
            output.extend(page)
            if not paginate or len(page) < chunk_limit or (limit is not None and len(output) >= limit):
                break
            offset += len(page)
        return output

    def one(self, table: str, **kwargs: Any) -> dict[str, Any] | None:
        rows = self.rows(table, limit=1, paginate=False, **kwargs)
        return rows[0] if rows else None


def _safe_rows(reader: SupabaseReader, table: str, **kwargs: Any) -> list[dict[str, Any]]:
    try:
        return reader.rows(table, **kwargs)
    except RuntimeError as exc:
        log.warning("Optional dataset %s unavailable: %s", table, exc)
        return []


def _safe_one(reader: SupabaseReader, table: str, **kwargs: Any) -> dict[str, Any] | None:
    rows = _safe_rows(reader, table, limit=1, paginate=False, **kwargs)
    return rows[0] if rows else None


def _review_versions(requested: list[str] | None) -> list[str]:
    configured = json.loads(REVIEW_CONFIG.read_text(encoding="utf-8"))["versions"]
    if not requested:
        return list(configured)
    requested = [item for value in requested for item in value.replace(",", " ").split()]
    unknown = sorted(set(requested) - set(configured))
    if unknown:
        raise ValueError(f"Unknown review versions: {', '.join(unknown)}")
    return [version for version in configured if version in requested]


def _latest_runs(reader: SupabaseReader, versions: list[str]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for version in versions:
        row = reader.one(
            "v4_runs",
            select="run_id,started_at,scoring_version,gate_version,universe_size,n_buy,health",
            filters={"scoring_version": f"eq.{version}"},
            order="started_at.desc",
        )
        if row:
            result[version] = row
    return result


def _project_today_signal(row: dict[str, Any]) -> dict[str, Any]:
    breakdown = row.get("breakdown") or {}
    return {
        "symbol": row.get("symbol"), "scoring_version": row.get("scoring_version"),
        "signal_date": row.get("signal_date"), "decision": row.get("decision"),
        "score_trade": row.get("score_trade"), "snap_time": row.get("snap_time"),
        "price": breakdown.get("price"), "confidence": breakdown.get("confidence"),
        "ff_intra_net": breakdown.get("ff_intra_net"), "ff_intra_ratio": breakdown.get("ff_intra_ratio"),
        "n_aligned": breakdown.get("n_supergroups_aligned"), "ff_score": breakdown.get("ff_score"),
        "fundamental_score": breakdown.get("fundamental_score"), "entry": breakdown.get("entry"),
        "stop": breakdown.get("stop", breakdown.get("stop_loss")), "tp1": breakdown.get("tp1"),
        "breakdown": breakdown,
    }


def _build_ic(reader: SupabaseReader, versions: list[str]) -> dict[str, Any]:
    metrics = reader.rows("v4_ic_metrics", order="config_version.desc,factor.asc,horizon.asc")
    indicators = _safe_rows(reader, "v4_ic_by_indicator")
    factor_versions: list[dict[str, Any]] = []
    marginal: list[dict[str, Any]] = []
    for version in versions:
        factor_versions.extend(_safe_rows(reader, "v4_ic_by_factor_ver", filters={"version": f"eq.{version}"}))
        marginal.extend(_safe_rows(reader, "v4_marginal_ic", filters={"version": f"eq.{version}"}))
    batch = reader.one(
        "v4_ic_industry_batch", filters={"status": "eq.ready"}, order="computed_at.desc",
    )
    industry: list[dict[str, Any]] = []
    errors: dict[str, str | None] = {version: None for version in versions}
    if batch:
        for version in versions:
            industry.extend(_safe_rows(reader,
                "v4_ic_industry_metrics",
                filters={"batch_id": f"eq.{batch['batch_id']}", "version": f"eq.{version}"},
                order="factor.asc,industry.asc,horizon.asc",
            ))
    return {
        "schema_version": 1, "release_id": None, "generated_at": None, "source": "github",
        "metrics": metrics, "indicators": indicators, "factor_versions": factor_versions,
        "marginal": marginal, "industry": industry, "industry_errors": errors,
    }


def _build_today(
    reader: SupabaseReader, version: str, run: dict[str, Any],
) -> dict[str, Any]:
    signal_date = str(run["run_id"]).split("_")[0]
    signals = reader.rows(
        "v4_signals",
        filters={"scoring_version": f"eq.{version}", "signal_date": f"eq.{signal_date}"},
        order="score_trade.desc",
    )
    ohlc = _safe_one(reader, "v4_ohlc", select="date,synced_at", order="date.desc")
    outcome = _safe_one(reader,
        "v4_outcomes", select="signal_date,eval_date,synced_at",
        filters={"scoring_version": f"eq.{version}"}, order="eval_date.desc",
    )
    ic = _safe_one(reader,
        "v4_ic_metrics", select="computed_at",
        filters={"config_version": f"eq.{version}"}, order="computed_at.desc",
    )
    return {
        "version": version, "signal_date": signal_date, "run": run,
        "signals": [_project_today_signal(row) for row in signals],
        "status": {"ohlc": ohlc, "outcome": outcome, "ic": ic},
    }


def _build_buy(reader: SupabaseReader, version: str) -> dict[str, Any]:
    latest = reader.one(
        "v4_signals", select="run_id,signal_date,snap_time",
        filters={"decision": "in.(BUY,STRONG BUY)", "scoring_version": f"eq.{version}"},
        order="signal_date.desc,snap_time.desc",
    )
    newest_run = reader.one(
        "v4_runs", select="run_id", filters={"scoring_version": f"eq.{version}"}, order="started_at.desc",
    )
    signals: list[dict[str, Any]] = []
    run_row = None
    if latest:
        signals = reader.rows(
            "v4_signals", select="id,symbol,decision,score_trade,signal_date,breakdown",
            filters={"run_id": f"eq.{latest['run_id']}", "scoring_version": f"eq.{version}",
                     "decision": "in.(BUY,STRONG BUY)"}, order="score_trade.desc",
        )
        run_row = reader.one(
            "v4_runs", select="started_at",
            filters={"run_id": f"eq.{latest['run_id']}", "scoring_version": f"eq.{version}"},
        )
        if signals:
            signal_date = latest["signal_date"]
            since = (datetime.fromisoformat(signal_date) - timedelta(days=14)).date().isoformat()
            symbols = ",".join(row["symbol"] for row in signals)
            ohlc = reader.rows(
                "v4_ohlc", select="symbol,date,close",
                filters={"symbol": f"in.({symbols})", "date": f"gte.{since}", "and": f"(date.lt.{signal_date})"},
                order="date.desc",
            )
            previous: dict[str, float] = {}
            for row in ohlc:
                previous.setdefault(row["symbol"], float(row["close"]))
            for signal in signals:
                price = (signal.get("breakdown") or {}).get("price")
                prev = previous.get(signal["symbol"])
                signal["changePct"] = ((float(price) - prev) / prev * 100) if price is not None and prev else None
    expectancy = _safe_rows(reader, "v4_buy_expectancy", filters={"scoring_version": f"eq.{version}"})
    robustness = _safe_rows(reader, "v4_buy_robustness", filters={"scoring_version": f"eq.{version}"})
    industry_batch = reader.one("v4_ic_industry_batch", filters={"status": "eq.ready"}, order="computed_at.desc")
    industry_rows = _safe_rows(reader, "v4_ic_industry_metrics", select="industry,ic,n", filters={"batch_id": f"eq.{industry_batch['batch_id']}", "version": f"eq.{version}", "factor": "eq.score_trade", "horizon": "eq.5"}) if industry_batch else []
    industry_ic = {
        row["industry"]: {"ic": float(row["ic"]) if row.get("ic") is not None else None, "n": int(row["n"])}
        for row in industry_rows
    }
    return {
        "version": version, "latestBuy": latest, "newestRun": newest_run,
        "signals": signals, "runRow": run_row, "expectancy": expectancy,
        "robustness": robustness, "industryIC": industry_ic,
    }


def _build_analysis(reader: SupabaseReader, version: str) -> dict[str, Any]:
    result_columns = (
        "pred_id,scoring_version,symbol,signal_date,snap_time,decision,score_trade,confidence,t0_close,"
        "ret_1d,ret_3d,ret_5d,ret_10d,mfe_pct,mae_pct,own_entry,own_tp1,own_tp2,own_stop,"
        "std_outcome,std_days,std3_outcome,own_outcome,own_days"
    )
    diagnostics = _safe_rows(reader, "v4_analysis_diagnostics_snapshot", filters={"scoring_version": f"eq.{version}"})
    corr = [{"factor": r.get("factor"), "grp": r.get("grp"), "n": r.get("n"), "corr_ret5": r.get("corr_ret5"), "corr_win": r.get("corr_win")} for r in diagnostics if r.get("kind") == "factor"]
    pairs = [{"fa": r.get("factor"), "fb": r.get("factor_b"), "n": r.get("n"), "corr": r.get("corr")} for r in diagnostics if r.get("kind") == "pair" and r.get("factor_b")]
    split = [{"dim": r.get("dim"), "bucket": r.get("bucket"), "factor": r.get("factor"), "grp": r.get("grp"), "n": r.get("n"), "corr_ret5": r.get("corr_ret5"), "corr_win": r.get("corr_win")} for r in diagnostics if r.get("kind") == "split"]
    return {
        "version": version,
        "results": reader.rows("v4_signal_analysis_dashboard", select=result_columns, filters={"scoring_version": f"eq.{version}"}, order="signal_date.desc,symbol.asc", limit=2000),
        "corr": corr, "pairs": pairs, "split": split,
    }

def _build_history(reader: SupabaseReader, version: str) -> dict[str, Any]:
    rows = reader.rows(
        "v4_signals",
        select="id,symbol,decision,score_trade,regime,signal_date,snap_time,scoring_version,breakdown",
        filters={"scoring_version": f"eq.{version}"}, order="signal_date.desc,snap_time.desc",
    )
    compact = []
    for row in rows:
        breakdown = row.get("breakdown") or {}
        row["breakdown"] = {
            key: breakdown.get(key) for key in ("price", "confidence", "pred_id") if breakdown.get(key) is not None
        }
        compact.append(row)
    return {"version": version, "rows": compact, "count": len(compact)}


def _build_charts(reader: SupabaseReader, versions: list[str]) -> dict[str, dict[str, Any]]:
    ohlc = reader.rows("v4_ohlc", select="symbol,date,open,high,low,close", order="symbol.asc,date.asc")
    by_symbol: dict[str, list[dict[str, Any]]] = {}
    for row in ohlc:
        by_symbol.setdefault(row["symbol"], []).append(row)
    result: dict[str, dict[str, Any]] = {}
    for version in versions:
        signals = reader.rows(
            "v4_signals", select="symbol,signal_date,snap_time,decision,breakdown",
            filters={"scoring_version": f"eq.{version}"}, order="signal_date.asc,snap_time.asc",
        )
        by_signal: dict[str, list[dict[str, Any]]] = {}
        for row in signals:
            breakdown = row.get("breakdown") or {}
            by_signal.setdefault(row["symbol"], []).append({
                "signal_date": row.get("signal_date"), "snap_time": row.get("snap_time"),
                "decision": row.get("decision"), "price": breakdown.get("price"),
            })
        result[version] = {
            symbol: {"ohlc": by_symbol.get(symbol, []), "signals": signal_rows}
            for symbol, signal_rows in by_signal.items()
        }
    return result


def build(reader: SupabaseReader, versions: list[str], dry_run: bool) -> Path:
    now = datetime.now(timezone.utc)
    release_id = now.strftime("%Y%m%dT%H%M%SZ")
    staging = SERVING_ROOT / f".staging-{release_id}"
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir(parents=True)
    datasets: list[dict[str, Any]] = []

    runs = _latest_runs(reader, versions)
    if not runs:
        raise RuntimeError("No review-version runs found; refusing to publish an empty release")
    metadata = {"schema_version": 1, "release_id": release_id, "generated_at": now.isoformat(), "runs": runs}
    datasets.append(_compact_json(staging / "metadata.json", metadata))

    ic = _build_ic(reader, versions)
    ic.update({"release_id": release_id, "generated_at": now.isoformat()})
    datasets.append(_compact_json(staging / "ic.json", ic))

    for version in versions:
        run = runs.get(version)
        if not run:
            log.warning("No run for %s; skipping tab snapshots", version)
            continue
        datasets.append(_compact_json(staging / "today" / f"{version}.json", _build_today(reader, version, run)))
        datasets.append(_compact_json(staging / "buy" / f"{version}.json", _build_buy(reader, version)))
        datasets.append(_compact_json(staging / "analysis" / f"{version}.json", _build_analysis(reader, version)))
        datasets.append(_compact_json(staging / "history" / f"{version}.json", _build_history(reader, version)))

    charts = _build_charts(reader, [version for version in versions if version in runs])
    for version, symbols in charts.items():
        for symbol, payload in symbols.items():
            datasets.append(_compact_json(staging / "charts" / version / f"{symbol}.json", payload))

    for item in datasets:
        item["path"] = str(Path(item["path"]).relative_to(staging)).replace("\\", "/")
    manifest = {
        "schema_version": 1, "release_id": release_id, "generated_at_utc": now.isoformat(),
        "asof_ict": now.astimezone(ICT).isoformat(), "quality": {"status": "PASS", "checks": [
            "non_empty_runs", "json_serializable", "sha256", "max_file_20_mib",
        ]},
        "datasets": datasets,
    }
    _compact_json(staging / "manifest.json", manifest)

    total = sum(item["bytes"] for item in datasets)
    log.info("Built release %s: %d datasets, %.2f MiB", release_id, len(datasets), total / 1024 / 1024)
    if dry_run:
        log.info("Dry-run: keeping staging output at %s", staging)
        return staging

    current = SERVING_ROOT / "current"
    previous = SERVING_ROOT / "previous"
    if previous.exists():
        shutil.rmtree(previous)
    if current.exists():
        current.rename(previous)
    staging.rename(current)
    latest = {"schema_version": 1, "release_id": release_id, "path": "current/manifest.json"}
    _compact_json(SERVING_ROOT / "latest.json", latest)
    log.info("Published %s atomically; previous release retained", current)
    return current


def main() -> int:
    parser = argparse.ArgumentParser(description="Build GitHub/Vercel dashboard serving snapshots")
    parser.add_argument("--versions", nargs="*", help="Subset of configured review versions")
    parser.add_argument("--dry-run", action="store_true", help="Build staging files without replacing current")
    args = parser.parse_args()
    try:
        versions = _review_versions(args.versions)
        url = os.environ.get("SUPABASE_URL") or os.environ.get("NEXT_PUBLIC_SUPABASE_URL")
        key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY") or os.environ.get("NEXT_PUBLIC_SUPABASE_ANON_KEY")
        if not url or not key:
            raise RuntimeError("Missing SUPABASE_URL/NEXT_PUBLIC_SUPABASE_URL or a server-side read key")
        build(SupabaseReader(url, key), versions, args.dry_run)
        return 0
    except Exception as exc:
        log.error("Serving build failed: %s", exc)
        return 1


if __name__ == "__main__":
    sys.exit(main())
