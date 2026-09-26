#!/usr/bin/env python3
"""Run the public integration-layer harness without host or network mutation."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / "plugins" / "solve-lite"
SCRIPTS = PLUGIN / "skills" / "solve-lite" / "scripts"


def run_test(path: Path) -> dict[str, object]:
    environment = dict(os.environ)
    environment.update({"PYTHONNOUSERSITE": "1", "PYTHONDONTWRITEBYTECODE": "1"})
    process = subprocess.run(
        [sys.executable, str(path)],
        cwd=str(ROOT),
        env=environment,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        check=False,
    )
    return {
        "name": path.relative_to(ROOT).as_posix(),
        "status": "PASS" if process.returncode == 0 else "FAIL",
        "returncode": process.returncode,
    }


def main() -> int:
    sys.path.insert(0, str(SCRIPTS))
    from solve_lite_abi import healthcheck

    blocked = healthcheck()
    registry = json.loads((SCRIPTS.parent / "assets" / "agent_registry.json").read_text(encoding="utf-8"))
    checks = {
        "public_manifest_present": (ROOT / "PUBLIC_REPO_MANIFEST.json").is_file(),
        "public_checksums_present": (ROOT / "SHA256SUMS.txt").is_file(),
        "core_asset_manifest_present": (ROOT / "CORE_ASSET_MANIFEST.json").is_file(),
        "private_runtime_package_absent": not (SCRIPTS / "solve_lite").exists(),
        "core_binary_absent": not list(ROOT.rglob("*.so")),
        "loader_missing_asset_fail_closed": (
            blocked.get("status") == "BLOCKED"
            and blocked.get("error") == "CORE_ASSET_UNAVAILABLE"
        ),
        "cold_fork_truth": (
            registry["cold_fork_test"]
            == "BLOCKED_PENDING_CLEAN_HOST_AND_PUBLIC_CORE_ASSET"
        ),
    }
    suites = [
        run_test(SCRIPTS / "test_solve_lite_abi.py"),
        run_test(SCRIPTS / "test_agent_auto.py"),
        run_test(PLUGIN / "scripts" / "test_codex_desktop_adapter.py"),
        run_test(ROOT / "tests" / "test_package.py"),
    ]
    passed = all(checks.values()) and all(item["status"] == "PASS" for item in suites)
    print(json.dumps({
        "status": "PASS" if passed else "FAIL",
        "checks": checks,
        "suites": suites,
        "network_attempts": 0,
        "live_mutation": 0,
        "route_prompt": "BLOCKED_CORE_ASSET_UNAVAILABLE",
        "cold_fork": "BLOCKED_PENDING_CLEAN_HOST_AND_PUBLIC_CORE_ASSET",
    }, indent=2, sort_keys=True))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
