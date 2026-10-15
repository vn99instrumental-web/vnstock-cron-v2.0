#!/usr/bin/env python3
"""Run every pinned historical V4 scorer against the current VN100 snapshot.

The production v4.18 scorer still runs normally. This script replays the exact
source snapshots of v4.1-v4.17 in isolated temporary directories, gives every
version its own hysteresis state, and emits one combined file for the recorder.
No market API is called and the production signal/state files are not mutated.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
REVIEW_PATH = ROOT / "config" / "scoring" / "review_versions.json"
OUTPUT = ROOT / "output"
MANIFEST_PATH = ROOT / "config" / "scoring" / "historical_versions.json"
COMBINED_PATH = OUTPUT / "v2f_signals_v4_all.json"
# Isolated, strictly version-pinned feed for the Zalo BUY visual.
ZALO_SIGNALS_PATH = OUTPUT / "v2f_signals_v4_17.json"
STATE_DIR = OUTPUT / "scoring_states"
TEMP_ROOT = ROOT / ".tmp"
INPUT_FILES = (
    "v2f_signals.json",
    "context.json",
    "v2f_signals_v3.json",
    "vnindex_live.json",
)


def _version_key(version: str) -> tuple[int, ...]:
    return tuple(int(part) for part in version.removeprefix("v").split("."))


def _load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json_atomic(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    os.replace(temp, path)


def _safe_extract(archive: tarfile.TarFile, destination: Path) -> None:
    base = destination.resolve()
    for member in archive.getmembers():
        target = (destination / member.name).resolve()
        if base not in target.parents and target != base:
            raise RuntimeError(f"unsafe archive member: {member.name}")
        if member.issym() or member.islnk():
            raise RuntimeError(f"links are not allowed in scoring bundle: {member.name}")
    archive.extractall(destination)


def _validate_rows(rows, expected_version: str) -> list[dict]:
    if not isinstance(rows, list) or not rows:
        raise RuntimeError(f"{expected_version}: scorer returned no rows")
    wrong = {str(row.get("scoring_version")) for row in rows if row.get("scoring_version") != expected_version}
    if wrong:
        raise RuntimeError(f"{expected_version}: output contains wrong versions {sorted(wrong)}")
    if any(not row.get("symbol") for row in rows):
        raise RuntimeError(f"{expected_version}: output contains a row without symbol")
    return rows


def _run_version(version: str, source_root: Path, timeout: int) -> list[dict]:
    run_output = source_root / "output"
    run_output.mkdir(exist_ok=True)
    for filename in INPUT_FILES:
        source = OUTPUT / filename
        if source.exists():
            shutil.copy2(source, run_output / filename)

    persisted_state = STATE_DIR / f"{version}.json"
    runtime_state = run_output / "v2f_v4_regime_state.json"
    if persisted_state.exists():
        shutil.copy2(persisted_state, runtime_state)

    env = os.environ.copy()
    env["PYTHONUTF8"] = "1"
    proc = subprocess.run(
        [sys.executable, "steps/v2f_step_scoring_v4.py"],
        cwd=source_root,
        env=env,
        text=True,
        encoding="utf-8",
        errors="replace",
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=timeout,
    )
    signal_path = run_output / "v2f_signals_v4.json"
    if proc.returncode != 0 or not signal_path.exists():
        tail = "\n".join(proc.stdout.splitlines()[-40:])
        raise RuntimeError(f"{version}: scorer failed (exit {proc.returncode})\n{tail}")

    rows = _validate_rows(_load_json(signal_path), version)
    if runtime_state.exists():
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        shutil.copy2(runtime_state, persisted_state)
    print(f"{version}: {len(rows)} rows")
    return rows


def main() -> None:
    COMBINED_PATH.unlink(missing_ok=True)
    # Never publish a stale v4.17 snapshot after a failed historical replay.
    ZALO_SIGNALS_PATH.unlink(missing_ok=True)
    parser = argparse.ArgumentParser()
    parser.add_argument("--versions", nargs="*", help="Optional subset for diagnostics")
    parser.add_argument("--timeout", type=int, default=120, help="Timeout per historical scorer")
    args = parser.parse_args()

    manifest = _load_json(MANIFEST_PATH)
    production_version = manifest["production_version"]
    production_path = OUTPUT / "v2f_signals_v4.json"
    production_rows = _validate_rows(_load_json(production_path), production_version)

    configured = sorted(manifest["versions"], key=_version_key)
    review_config = _load_json(REVIEW_PATH)
    selected = args.versions or review_config["historical_scorers"]
    unknown = sorted(set(selected) - set(configured))
    if unknown:
        raise SystemExit(f"Unknown historical versions: {', '.join(unknown)}")

    archive_path = ROOT / manifest["archive"]
    if not archive_path.exists():
        raise SystemExit(f"Missing pinned scoring archive: {archive_path}")

    combined = list(production_rows)
    failures: list[str] = []
    TEMP_ROOT.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="historical-scoring-", dir=TEMP_ROOT) as tmp_name:
        extracted = Path(tmp_name)
        with tarfile.open(archive_path, "r:gz") as archive:
            _safe_extract(archive, extracted)
        for version in sorted(selected, key=_version_key):
            try:
                rows = _run_version(version, extracted / version, args.timeout)
                if version == "v4.17":
                    production_symbols = {r["symbol"] for r in production_rows}
                    selected_symbols = {r["symbol"] for r in rows}
                    if len(selected_symbols) != len(rows) or selected_symbols != production_symbols:
                        raise RuntimeError("v4.17: symbol coverage differs from production snapshot")
                    # Publish independently; other historical scorers must not block Zalo.
                    _write_json_atomic(ZALO_SIGNALS_PATH, rows)
                combined.extend(rows)
            except Exception as exc:
                failures.append(str(exc))

    if failures:
        COMBINED_PATH.unlink(missing_ok=True)
        raise SystemExit("Historical scoring incomplete:\n- " + "\n- ".join(failures))

    expected_versions = {production_version, *selected}
    actual_versions = {row["scoring_version"] for row in combined}
    if actual_versions != expected_versions:
        raise SystemExit(f"Version coverage mismatch: expected {sorted(expected_versions)}, got {sorted(actual_versions)}")
    _write_json_atomic(COMBINED_PATH, combined)
    print(f"Combined {len(combined)} rows / {len(actual_versions)} versions -> {COMBINED_PATH}")


if __name__ == "__main__":
    main()
