"""Fail closed when the SSI runtime regains a Gen6 calculated-data dependency."""
from __future__ import annotations

import json
from pathlib import Path

from scripts.shared_raw_collector import load_current_manifest


ROOT = Path(__file__).resolve().parents[1]
RUNTIME_FILES = (
    ROOT / "scripts" / "ssi_independent_pipeline.py",
    ROOT / "scripts" / "ssi_raw_features.py",
    ROOT / ".github" / "workflows" / "ssi_independent_production.yml",
)
FORBIDDEN = ("vnstock6", "output/serving/vnstock6", "output/history/vnstock6", "output/ohlc")


def validate(*, require_release: bool = True) -> dict:
    violations = []
    for path in RUNTIME_FILES:
        text = path.read_text(encoding="utf-8").lower().replace("\\", "/")
        for token in FORBIDDEN:
            if token in text:
                violations.append(f"{path.relative_to(ROOT).as_posix()}:{token}")
    config = json.loads((ROOT / "config" / "ssi_independent.json").read_text(encoding="utf-8"))
    if config.get("input_layer") != "shared_raw" or config.get("feature_engine") != "ssi":
        violations.append("config:ssi_input_boundary")
    release_id = None
    if require_release:
        _, manifest = load_current_manifest()
        release_id = manifest["release_id"]
        if manifest.get("contract", {}).get("gen6_dependency") is not False:
            violations.append("raw_manifest:gen6_dependency")
    if violations:
        raise RuntimeError("SSI_STANDALONE_BOUNDARY_VIOLATION:" + ",".join(violations))
    return {"status": "passed", "release_id": release_id, "runtime_files": len(RUNTIME_FILES)}


if __name__ == "__main__":
    print(json.dumps(validate(), sort_keys=True))
