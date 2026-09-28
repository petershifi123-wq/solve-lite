#!/usr/bin/env python3
"""Read-only health report for the current shared CoreML runtime."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "plugins" / "solve-lite" / "skills" / "solve-lite"
SCRIPTS = SKILL / "scripts"
AGENT_REGISTRY = SKILL / "assets" / "agent_registry.json"


def _load():
    if str(SCRIPTS) not in sys.path:
        sys.path.insert(0, str(SCRIPTS))
    import compact_runtime
    import shared_runtime
    import solve_lite_abi

    return solve_lite_abi, compact_runtime, shared_runtime


def _host_registry_view() -> dict:
    payload = json.loads(AGENT_REGISTRY.read_text(encoding="utf-8"))
    return {
        "schema_version": payload.get("schema_version"),
        "current_install_target": payload.get("current_install_target"),
        "hosts": [entry.get("host_id") for entry in payload.get("hosts", [])],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--runtime-root", type=Path, default=None)
    parser.add_argument("--case", type=Path, default=None)
    parser.add_argument("--workspace", type=Path, default=None)
    args = parser.parse_args()

    abi, compact, shared = _load()
    runtime = Path(args.runtime_root or shared.resolve(SKILL)).expanduser().resolve()
    health = abi.healthcheck(runtime)
    caps = abi.capabilities(runtime)
    routes = abi.available_routes(runtime)
    asset = compact.status(runtime)
    report = {
        "status": "PASS" if health.get("status") == "PASS" and asset.get("status") == "PASS" else "FAIL",
        "version": "v0.1.11",
        "runtime_root": str(runtime),
        "healthcheck": health,
        "capabilities": caps,
        "routes": routes,
        "compact_runtime": asset,
        "host_registry": _host_registry_view(),
        "network_used": False,
        "torch_runtime": False,
        "transformers_runtime": False,
    }
    if args.case:
        workspace = args.workspace or (ROOT / ".solve-lite-workspace")
        workspace.mkdir(parents=True, exist_ok=True)
        case = json.loads(args.case.read_text(encoding="utf-8"))
        report["case_route"] = abi.route_prompt(workspace, case, session={"metadata": {"locale": "en-US"}}, asset_root=runtime)
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False))
    else:
        print(f"status           {report['status']}")
        print(f"runtime root     {runtime}")
        print(f"native core      {health.get('native_core_status')}")
        print(f"shared CoreML    {asset.get('status')}")
        print(f"routes           {', '.join(routes.get('installed_routes') or [])}")
        print(f"host registry    {report['host_registry'].get('schema_version')}")
    return 0 if report["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
