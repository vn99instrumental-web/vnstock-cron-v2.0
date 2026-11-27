"""Collect and verify immutable provider-raw releases from SSI and FHSC.

This module is deliberately calculator-neutral.  It publishes provider rows and
transport metadata only: no ratios, indicators, factors, signals or scores.
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import math
import os
import re
import shutil
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Protocol


ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "config" / "shared_raw_ssi_fhsc.json"
RAW_ROOT = ROOT / "output" / "shared-raw" / "ssi-fhsc"
UTC = timezone.utc
RELEASE_RE = re.compile(r"^[0-9]{8}T[0-9]{6}Z-[0-9a-f]{8}$")
GIT_BLOB_SAFETY_BYTES = 95 * 1024 * 1024

ENDPOINTS = {
    "reference": ("SSI", "reference/equity-list.jsonl"),
    "index_ohlcv": ("SSI", "market/vnindex-ohlcv.jsonl"),
    "ohlcv": ("SSI", "market/equity-ohlcv.jsonl"),
    "ohlcv_intraday": ("SSI", "market/equity-ohlcv-intraday.jsonl"),
    "foreign_flow": ("SSI", "market/foreign-flow.jsonl"),
    "foreign_flow_fhsc": ("FHSC", "market/foreign-flow-fhsc.jsonl"),
    "session_stats": ("SSI", "market/session-stats.jsonl"),
    "active_session": ("FHSC", "market/active-session.jsonl"),
    "balance_sheet": ("FHSC", "fundamental/balance-sheet.jsonl.gz"),
    "income_statement": ("FHSC", "fundamental/income-statement.jsonl.gz"),
    "cash_flow": ("FHSC", "fundamental/cash-flow.jsonl.gz"),
    "order_book": ("FHSC", "market/order-book.jsonl"),
    "proprietary_flow": ("FHSC", "market/proprietary-flow.jsonl"),
    "insider_deal": ("FHSC", "market/insider-deal.jsonl"),
}


class RawTransport(Protocol):
    def fetch(self, endpoint: str, source: str, symbol: str | None, parameters: dict[str, Any]) -> Any: ...


def _json_safe(value: Any) -> Any:
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    item = getattr(value, "item", None)
    if callable(item):
        try:
            return _json_safe(item())
        except (TypeError, ValueError):
            pass
    isoformat = getattr(value, "isoformat", None)
    if callable(isoformat):
        try:
            return isoformat()
        except (TypeError, ValueError):
            pass
    return str(value)


def _records(value: Any) -> list[dict[str, Any]]:
    if value is None:
        return []
    if hasattr(value, "reset_index") and hasattr(value, "to_dict"):
        value = value.reset_index().to_dict("records")
    elif isinstance(value, dict):
        value = [value]
    elif not isinstance(value, list):
        value = list(value) if isinstance(value, Iterable) and not isinstance(value, (str, bytes)) else []
    return [_json_safe(row) for row in value if isinstance(row, dict)]


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(_json_safe(value), ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def content_hash(value: Any) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def _error(exc: Exception) -> dict[str, Any]:
    return {
        "type": type(exc).__name__,
        "code": _json_safe(getattr(exc, "code", None)),
        "action": _json_safe(getattr(exc, "action", None)),
    }


class VnstockTransport:
    """Thin transport adapter; every call names its approved source explicitly."""

    def __init__(self) -> None:
        from vnstock import Fundamental, Market, Reference

        self.Fundamental = Fundamental
        self.Market = Market
        self.Reference = Reference

    def fetch(self, endpoint: str, source: str, symbol: str | None, parameters: dict[str, Any]) -> Any:
        source_name = source.lower()
        if endpoint == "reference":
            return self.Reference(source_name).equity.list()
        if endpoint == "index_ohlcv":
            return self.Market(source_name).index("VNINDEX").ohlcv(**parameters, compat="v6", columns="all")
        if endpoint in {"balance_sheet", "income_statement", "cash_flow"}:
            equity = self.Fundamental(source_name).equity(str(symbol))
            return getattr(equity, endpoint)(**parameters, compat="v6", columns="all")
        equity = self.Market(source_name).equity(str(symbol))
        if endpoint in {"ohlcv", "ohlcv_intraday"}:
            return equity.ohlcv(**parameters, compat="v6", columns="all")
        if endpoint in {"foreign_flow", "foreign_flow_fhsc"}:
            return equity.foreign_flow(**parameters, compat="v6", columns="all")
        if endpoint == "session_stats":
            return equity.session_stats(**parameters, compat="v6", columns="all")
        if endpoint == "active_session":
            return equity.active_session(**parameters, compat="v6", columns="all")
        if endpoint in {"order_book", "insider_deal"}:
            return getattr(equity, endpoint)(compat="v6", columns="all")
        if endpoint == "proprietary_flow":
            return equity.proprietary_flow(**parameters, compat="v6", columns="all")
        raise ValueError(f"UNSUPPORTED_RAW_ENDPOINT:{endpoint}")


def _envelope(
    transport: RawTransport,
    endpoint: str,
    source: str,
    symbol: str | None,
    parameters: dict[str, Any],
    fetched_at: str,
) -> dict[str, Any]:
    try:
        rows = _records(transport.fetch(endpoint, source, symbol, parameters))
        return {
            "schema_version": 1,
            "source": source,
            "endpoint": endpoint,
            "symbol": symbol,
            "parameters": parameters,
            "fetched_at": fetched_at,
            "status": "success" if rows else "empty",
            "row_count": len(rows),
            "raw_sha256": content_hash(rows),
            "rows": rows,
            "error": None,
        }
    except Exception as exc:
        return {
            "schema_version": 1,
            "source": source,
            "endpoint": endpoint,
            "symbol": symbol,
            "parameters": parameters,
            "fetched_at": fetched_at,
            "status": "error",
            "row_count": 0,
            "raw_sha256": content_hash([]),
            "rows": [],
            "error": _error(exc),
        }


def _write_jsonl(path: Path, values: list[dict[str, Any]]) -> dict[str, Any]:
    path.parent.mkdir(parents=True, exist_ok=True)
    raw_body = b"".join(canonical_bytes(value) + b"\n" for value in values)
    body = gzip.compress(raw_body, compresslevel=9, mtime=0) if path.suffix == ".gz" else raw_body
    if len(body) > GIT_BLOB_SAFETY_BYTES:
        raise RuntimeError(f"SHARED_RAW_DATASET_EXCEEDS_GIT_BLOB_SAFETY_LIMIT:{path.name}:{len(body)}")
    path.write_bytes(body)
    return {
        "path": path.as_posix(),
        "sha256": hashlib.sha256(body).hexdigest(),
        "bytes": len(body),
        "records": len(values),
        "successful": sum(value["status"] == "success" for value in values),
        "empty": sum(value["status"] == "empty" for value in values),
        "errors": sum(value["status"] == "error" for value in values),
    }


def _release_id(created_at: datetime, signal_date: date, symbols: list[str], cadence: str) -> str:
    seed = content_hash({"date": signal_date.isoformat(), "symbols": symbols, "cadence": cadence, "created_at": created_at.isoformat()})[:8]
    return f"{created_at.strftime('%Y%m%dT%H%M%SZ')}-{seed}"


def _call_specs(config: dict[str, Any], signal_date: date, cadence: str) -> dict[str, list[tuple[str | None, dict[str, Any]]]]:
    market_start = (signal_date - timedelta(days=int(config["market_history_calendar_days"]))).isoformat()
    flow_start = (signal_date - timedelta(days=int(config["flow_history_calendar_days"]))).isoformat()
    end = signal_date.isoformat()
    symbols = [str(symbol).upper() for symbol in config["universe"]]
    specs: dict[str, list[tuple[str | None, dict[str, Any]]]] = {
        "reference": [(None, {})],
        "index_ohlcv": [("VNINDEX", {"start": market_start, "end": end, "interval": "1D"})],
        "ohlcv": [(symbol, {"start": market_start, "end": end, "interval": "1D"}) for symbol in symbols],
        "foreign_flow": [(symbol, {"start": flow_start, "end": end, "interval": "1D"}) for symbol in symbols],
        "foreign_flow_fhsc": [(symbol, {"start": flow_start, "end": end, "interval": "1D"}) for symbol in symbols],
        "session_stats": [(symbol, {"start": end, "end": end}) for symbol in symbols],
        "active_session": [(symbol, {}) for symbol in symbols],
    }
    if cadence == "intraday":
        specs.update({
            "ohlcv_intraday": [(symbol, {"start": end, "end": end, "interval": "5m"}) for symbol in symbols],
            "order_book": [(symbol, {}) for symbol in symbols],
        })
    if cadence in {"daily", "weekly"}:
        specs.update({
            "balance_sheet": [(symbol, {"period": "quarter", "format": "long"}) for symbol in symbols],
            "income_statement": [(symbol, {"period": "quarter", "format": "long"}) for symbol in symbols],
            "cash_flow": [(symbol, {"period": "quarter", "format": "long"}) for symbol in symbols],
            "proprietary_flow": [(symbol, {"start": flow_start, "end": end}) for symbol in symbols],
            "insider_deal": [(symbol, {}) for symbol in symbols],
        })
    if cadence == "weekly":
        specs["order_book"] = [(symbol, {}) for symbol in symbols]
    return specs


def collect_release(
    config: dict[str, Any],
    transport: RawTransport,
    output_root: Path = RAW_ROOT,
    *,
    cadence: str = "weekly",
    mode: str | None = None,
    signal_date: date | None = None,
    created_at: datetime | None = None,
    release_id: str | None = None,
) -> dict[str, Any]:
    if mode is not None:
        cadence = {"market": "intraday", "full": "weekly"}.get(mode, mode)
    if cadence not in {"intraday", "daily", "weekly"}:
        raise ValueError("RAW_CADENCE_MUST_BE_INTRADAY_DAILY_OR_WEEKLY")
    created_at = (created_at or datetime.now(UTC)).astimezone(UTC)
    signal_date = signal_date or created_at.date()
    symbols = sorted({str(symbol).upper() for symbol in config["universe"]})
    if not symbols or any(not re.fullmatch(r"[A-Z0-9]{2,5}", symbol) for symbol in symbols):
        raise ValueError("INVALID_SHARED_RAW_UNIVERSE")
    release_id = release_id or _release_id(created_at, signal_date, symbols, cadence)
    if not RELEASE_RE.fullmatch(release_id):
        raise ValueError("INVALID_SHARED_RAW_RELEASE_ID")
    releases = output_root / "releases"
    final = releases / release_id
    staging = output_root / f".staging-{release_id}"
    if final.exists() or staging.exists():
        raise FileExistsError(f"IMMUTABLE_SHARED_RAW_RELEASE_EXISTS:{release_id}")
    staging.mkdir(parents=True, exist_ok=False)
    fetched_at = created_at.isoformat()
    datasets: list[dict[str, Any]] = []
    try:
        for endpoint, calls in _call_specs({**config, "universe": symbols}, signal_date, cadence).items():
            source, relative = ENDPOINTS[endpoint]
            values: list[dict[str, Any]] = []
            with ThreadPoolExecutor(max_workers=max(1, int(config.get("max_workers", 4)))) as pool:
                futures = {
                    pool.submit(_envelope, transport, endpoint, source, symbol, parameters, fetched_at): symbol
                    for symbol, parameters in calls
                }
                for future in as_completed(futures):
                    values.append(future.result())
            values.sort(key=lambda value: str(value.get("symbol") or ""))
            metadata = _write_jsonl(staging / relative, values)
            metadata["path"] = relative
            datasets.append(metadata)

        lookup = {item["path"]: item for item in datasets}
        ohlcv = lookup[ENDPOINTS["ohlcv"][1]]
        index = lookup[ENDPOINTS["index_ohlcv"][1]]
        minimum = min(len(symbols), int(config["minimum_ohlcv_symbols"]))
        checks = {
            "ohlcv_successful": ohlcv["successful"],
            "ohlcv_minimum": minimum,
            "index_ohlcv_successful": index["successful"],
            "manifest_has_no_calculated_datasets": True,
        }
        if ohlcv["successful"] < minimum:
            raise RuntimeError(f"SHARED_RAW_OHLCV_COVERAGE_BELOW_MINIMUM:{ohlcv['successful']}:{minimum}")
        if index["successful"] != 1:
            raise RuntimeError("SHARED_RAW_VNINDEX_MISSING")
        manifest = {
            "schema_version": 1,
            "namespace": config["namespace"],
            "release_id": release_id,
            "created_at": fetched_at,
            "signal_date": signal_date.isoformat(),
            "cadence": cadence,
            "mode": "market" if cadence == "intraday" else "full",
            "sources": {"market": "SSI", "fundamental": "FHSC"},
            "universe": symbols,
            "datasets": datasets,
            "qc": {"status": "passed", "checks": checks},
            "contract": {
                "payload": "provider_rows_only",
                "calculated_fields": [],
                "immutable": True,
                "gen6_dependency": False,
            },
        }
        manifest_path = staging / "manifest.json"
        manifest_path.write_bytes(json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2).encode("utf-8") + b"\n")
        releases.mkdir(parents=True, exist_ok=True)
        staging.rename(final)
        verify_release(final)
        pointer = {
            "schema_version": 1,
            "namespace": config["namespace"],
            "release_id": release_id,
            "path": f"releases/{release_id}/manifest.json",
            "published_at": fetched_at,
        }
        pointer_tmp = output_root / ".current.json.tmp"
        pointer_tmp.write_bytes(json.dumps(pointer, ensure_ascii=False, sort_keys=True, indent=2).encode("utf-8") + b"\n")
        os.replace(pointer_tmp, output_root / "current.json")
        return manifest
    except Exception:
        if staging.exists():
            shutil.rmtree(staging)
        raise


def verify_release(release_dir: Path) -> dict[str, Any]:
    manifest_path = release_dir / "manifest.json"
    if not manifest_path.exists():
        raise FileNotFoundError("SHARED_RAW_MANIFEST_MISSING")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("schema_version") != 1 or manifest.get("namespace") != "ssi-fhsc-raw":
        raise ValueError("SHARED_RAW_CONTRACT_MISMATCH")
    if manifest.get("cadence") not in {"intraday", "daily", "weekly"}:
        raise ValueError("SHARED_RAW_CADENCE_INVALID")
    if release_dir.name != manifest.get("release_id") or not RELEASE_RE.fullmatch(release_dir.name):
        raise ValueError("SHARED_RAW_RELEASE_ID_MISMATCH")
    if manifest.get("qc", {}).get("status") != "passed":
        raise ValueError("SHARED_RAW_QC_NOT_PASSED")
    if manifest.get("contract", {}).get("calculated_fields") != []:
        raise ValueError("SHARED_RAW_CALCULATED_FIELDS_FORBIDDEN")
    for dataset in manifest.get("datasets", []):
        relative = str(dataset["path"])
        if Path(relative).is_absolute() or ".." in Path(relative).parts:
            raise ValueError("SHARED_RAW_UNSAFE_DATASET_PATH")
        dataset_path = release_dir / relative
        body = dataset_path.read_bytes()
        if len(body) != int(dataset["bytes"]):
            raise ValueError(f"SHARED_RAW_SIZE_MISMATCH:{relative}")
        if hashlib.sha256(body).hexdigest() != dataset["sha256"]:
            raise ValueError(f"SHARED_RAW_HASH_MISMATCH:{relative}")
        try:
            payload = gzip.decompress(body) if dataset_path.suffix == ".gz" else body
        except (OSError, EOFError) as exc:
            raise ValueError(f"SHARED_RAW_GZIP_INVALID:{relative}") from exc
        for line in payload.splitlines():
            envelope = json.loads(line)
            if envelope.get("source") not in {"SSI", "FHSC"}:
                raise ValueError(f"SHARED_RAW_SOURCE_INVALID:{relative}")
            if envelope.get("raw_sha256") != content_hash(envelope.get("rows", [])):
                raise ValueError(f"SHARED_RAW_ENVELOPE_HASH_MISMATCH:{relative}")
    return manifest


def load_current_manifest(output_root: Path = RAW_ROOT) -> tuple[Path, dict[str, Any]]:
    pointer = json.loads((output_root / "current.json").read_text(encoding="utf-8"))
    release_id = str(pointer.get("release_id") or "")
    if not RELEASE_RE.fullmatch(release_id):
        raise ValueError("SHARED_RAW_CURRENT_RELEASE_ID_INVALID")
    release_dir = output_root / "releases" / release_id
    return release_dir, verify_release(release_dir)


def read_dataset(release_dir: Path, relative: str) -> list[dict[str, Any]]:
    path = release_dir / relative
    body = path.read_bytes()
    payload = gzip.decompress(body) if path.suffix == ".gz" else body
    return [json.loads(line) for line in payload.splitlines() if line.strip()]


def main() -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    collect = sub.add_parser("collect")
    collect.add_argument("--cadence", choices=("intraday", "daily", "weekly"), default="weekly")
    collect.add_argument("--mode", choices=("market", "full"), help=argparse.SUPPRESS)
    collect.add_argument("--signal-date")
    collect.add_argument("--output-root", type=Path, default=RAW_ROOT)
    verify = sub.add_parser("verify")
    verify.add_argument("--release-dir", type=Path)
    verify.add_argument("--output-root", type=Path, default=RAW_ROOT)
    args = parser.parse_args()
    if args.command == "collect":
        config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        manifest = collect_release(
            config,
            VnstockTransport(),
            args.output_root,
            cadence=args.cadence,
            mode=args.mode,
            signal_date=date.fromisoformat(args.signal_date) if args.signal_date else None,
        )
    else:
        if args.release_dir:
            manifest = verify_release(args.release_dir)
        else:
            _, manifest = load_current_manifest(args.output_root)
    print(json.dumps({
        "release_id": manifest["release_id"],
        "cadence": manifest.get("cadence"),
        "mode": manifest["mode"],
        "signal_date": manifest["signal_date"],
        "qc": manifest["qc"]["status"],
        "datasets": len(manifest["datasets"]),
    }, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
