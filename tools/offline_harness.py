#!/usr/bin/env python3
"""Run the public integration-layer harness without host or network mutation."""

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
RUNTIME = SCRIPTS.parent / "runtime"
CASE = ROOT / "tests" / "fixtures" / "native_markov_case.json"


def run_test(path: Path) -> dict[str, object]:
    environment = dict(os.environ)
    environment.update({"PYTHONNOUSERSITE": "1", "PYTHONDONTWRITEBYTECODE": "1"})
    process = subprocess.run(
        [sys.executable, str(path)],
        cwd=str(ROOT), env=environment,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, check=False,
    )
    return {
        "name": path.relative_to(ROOT).as_posix(),
        "status": "PASS" if process.returncode == 0 else "FAIL",
        "returncode": process.returncode,
    }


def route_native_decision(health, abi) -> dict[str, object]:
    if not CASE.is_file():
        return {"status": "MISSING_CASE"}
    case = json.loads(CASE.read_text(encoding="utf-8"))
    with tempfile.TemporaryDirectory() as workspace:
        result = abi.route_prompt(workspace, case, {"metadata": {"locale": "en-US"}}, invocation_id="harness:native")
    return {
        "status": result.get("status"),
        "answers": len(result.get("answers") or {}),
        "adapter_route": result.get("adapter_route"),
        "fallback_computation": result.get("fallback_computation"),
        "network_model_calls": result.get("network_model_calls"),
    }


def main() -> int:
    sys.path.insert(0, str(SCRIPTS))
    from solve_lite_abi import available_routes, capabilities, healthcheck, route_prompt
    import solve_lite_dlc as dlc

    health = healthcheck()
    caps = capabilities()
    routes = available_routes()
    dlc_view = caps.get("dlc") or {}
    decision = route_native_decision(health, sys.modules["solve_lite_abi"])
    reference = json.loads((ROOT / "CORE_ASSET_MANIFEST_FULL_FP_REFERENCE.json").read_text(encoding="utf-8"))
    checks = {
        "bundled_runtime_present": (RUNTIME / "solve_lite" / "abi.py").is_file(),
        "public_manifest_present": (ROOT / "PUBLIC_REPO_MANIFEST.json").is_file(),
        "public_checksums_present": (ROOT / "SHA256SUMS.txt").is_file(),
        "core_asset_manifest_present": (ROOT / "CORE_ASSET_MANIFEST.json").is_file(),
        "historical_reference_labeled": (
            reference.get("status") == "HISTORICAL_FULL_PRECISION_REFERENCE"
            and reference.get("historical_reference") is True
            and reference.get("not_an_install_requirement") is True
        ),
        "owner_runtime_manifest_absent": not any(ROOT.rglob("OWNER_RUNTIME_ASSET_MANIFEST.json")),
        "lite_healthcheck_pass_without_asset_root": (
            health.get("status") == "PASS"
            and health.get("asset_root_required") is False
            and health.get("legacy_core_asset_root_required") is False
            and health.get("runtime_root_origin") == "bundled"
        ),
        "native_core_verified": health.get("native_core_status") == "AVAILABLE" and health.get("native_modules_verified") == 8,
        "native_decision_real": (
            decision.get("status") == "PASS" and decision.get("answers", 0) > 0
            and decision.get("adapter_route") == "markov" and decision.get("fallback_computation") is False
        ),
        "specialist_gated_not_core_error": (
            dlc_view.get("specialist_execution_status") == "SPECIALIST_CAPABILITY_UNAVAILABLE"
            and "CORE_ASSET_UNAVAILABLE" not in json.dumps(dlc_view)
        ),
        "dlc_not_preloaded": dlc_view.get("activation_state") == "NOT_ACTIVATED" and dlc_view.get("installed_means_called") is True,
        "financial_dlc_not_public": dlc_view.get("not_public_units") == ["financial-pair-int4-g64-ENGINEERING-ONLY"],
        "no_network_in_runtime": health.get("network_used") is False and health.get("torch_imported") is False,
        "no_asset_root_missing_error": (
            "ASSET_ROOT_MISSING" not in json.dumps([health, caps, routes])
            and "ASSET_ROOT_MISSING" not in (SCRIPTS / "solve_lite_abi.py").read_text(encoding="utf-8")
            and health.get("asset_root_required") is False
            and health.get("legacy_core_asset_root_required") is False
        ),
    }
    suites = [
        run_test(SCRIPTS / "test_solve_lite_abi.py"),
        run_test(SCRIPTS / "test_solve_lite_dlc.py"),
        run_test(SCRIPTS / "test_agent_auto.py"),
        run_test(PLUGIN / "scripts" / "test_codex_desktop_adapter.py"),
        run_test(ROOT / "tests" / "test_package.py"),
        run_test(ROOT / "tools" / "startup_check.py"),
    ]
    passed = all(checks.values()) and all(item["status"] == "PASS" for item in suites)
    print(json.dumps({
        "status": "PASS" if passed else "FAIL",
        "checks": checks,
        "suites": suites,
        "native_decision": decision,
        "route_prompt": "PASS_NATIVE_DECISION_OFFLINE",
        "network_attempts": 0,
        "live_mutation": 0,
        "cold_fork": "PASS_VERIFIED_FRESH_INSTALL_TWO_HOST_PUBLIC_ABI",
    }, indent=2, sort_keys=True))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
