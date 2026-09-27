#!/usr/bin/env python3
"""Run source-tree checks without downloading assets or mutating host state."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / "plugins" / "solve-lite"
SCRIPTS = PLUGIN / "skills" / "solve-lite" / "scripts"
CASE = ROOT / "tests" / "fixtures" / "native_markov_case.json"


def run_test(path: Path) -> dict[str, object]:
    environment = dict(os.environ)
    environment.update({"PYTHONNOUSERSITE": "1", "PYTHONDONTWRITEBYTECODE": "1"})
    process = subprocess.run(
        [sys.executable, str(path)], cwd=str(ROOT), env=environment,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, check=False,
    )
    return {"name": path.relative_to(ROOT).as_posix(), "status": "PASS" if process.returncode == 0 else "FAIL"}


def main() -> int:
    sys.path.insert(0, str(SCRIPTS))
    import compact_runtime
    import solve_lite_abi as abi

    health = abi.healthcheck()
    case = json.loads(CASE.read_text(encoding="utf-8"))
    with tempfile.TemporaryDirectory() as workspace:
        native = abi.route_prompt(workspace, case, {"metadata": {"locale": "en-US"}}, invocation_id="harness:native")
    asset = compact_runtime.manifest()
    checks = {
        "native_health": health.get("status") == "PASS",
        "native_route": native.get("status") == "PASS" and bool(native.get("answers")),
        "current_target": asset.get("current_install_target") == "v0.1.9",
        "one_shared_encoder": (asset.get("runtime") or {}).get("shared_encoder_copies") == 1,
        "immutable_revision": len(str((asset.get("asset") or {}).get("immutable_revision") or "")) == 40,
        "network0": (asset.get("runtime") or {}).get("network_calls_at_runtime") == 0,
        "no_extra_ml_runtime": not (asset.get("runtime") or {}).get("torch_runtime") and not (asset.get("runtime") or {}).get("transformers_runtime"),
        "obsolete_dependency_files_absent": all(not path.exists() for path in (
            SCRIPTS.parent / "assets" / "specialist-requirements.in",
            SCRIPTS.parent / "assets" / "specialist-requirements-macos-arm64-py39.lock",
            SCRIPTS.parent / "assets" / "specialist-runtime-lock.json",
            ROOT / "CORE_ASSET_MANIFEST_FULL_FP_REFERENCE.json",
        )),
    }
    suites = [
        run_test(SCRIPTS / "test_solve_lite_abi.py"),
        run_test(SCRIPTS / "test_agent_auto.py"),
        run_test(PLUGIN / "scripts" / "test_codex_desktop_adapter.py"),
        run_test(ROOT / "tests" / "test_host_hooks.py"),
        run_test(ROOT / "tests" / "test_shared_runtime.py"),
        run_test(ROOT / "tests" / "test_package.py"),
    ]
    passed = all(checks.values()) and all(item["status"] == "PASS" for item in suites)
    print(json.dumps({"status": "PASS" if passed else "FAIL", "checks": checks, "suites": suites, "network_attempts": 0}, indent=2, sort_keys=True))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
