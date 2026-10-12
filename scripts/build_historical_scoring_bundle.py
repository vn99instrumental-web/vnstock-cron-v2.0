#!/usr/bin/env python3
"""Rebuild the pinned v4.1-v4.17 scoring source bundle from Git history."""
from __future__ import annotations

import io
import json
import subprocess
import tarfile
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
MANIFEST = ROOT / "config" / "scoring" / "historical_versions.json"
TEMP_ROOT = ROOT / ".tmp"
ARCHIVE_PATHS = (
    "config.py",
    "steps/v2f_step_scoring_v3.py",
    "steps/v2f_step_scoring_v4.py",
    "utils",
)


def _safe_extract(archive: tarfile.TarFile, destination: Path) -> None:
    base = destination.resolve()
    for member in archive.getmembers():
        target = (destination / member.name).resolve()
        if base not in target.parents and target != base:
            raise RuntimeError(f"unsafe archive member: {member.name}")
        if member.issym() or member.islnk():
            raise RuntimeError(f"links are not allowed in scoring bundle: {member.name}")
    archive.extractall(destination)


def main() -> None:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    output = ROOT / manifest["archive"]
    output.parent.mkdir(parents=True, exist_ok=True)

    TEMP_ROOT.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="scoring-bundle-", dir=TEMP_ROOT) as tmp_name:
        staging = Path(tmp_name)
        for version, commit in manifest["versions"].items():
            payload = subprocess.run(
                ["git", "archive", "--format=tar", commit, *ARCHIVE_PATHS],
                cwd=ROOT,
                check=True,
                stdout=subprocess.PIPE,
            ).stdout
            version_dir = staging / version
            version_dir.mkdir()
            with tarfile.open(fileobj=io.BytesIO(payload), mode="r:") as archive:
                _safe_extract(archive, version_dir)

        with tarfile.open(output, "w:gz", compresslevel=9) as bundle:
            for path in sorted(staging.rglob("*")):
                bundle.add(path, arcname=path.relative_to(staging))

    print(f"Built {output.relative_to(ROOT)} ({output.stat().st_size:,} bytes)")


if __name__ == "__main__":
    main()
