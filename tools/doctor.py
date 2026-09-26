#!/usr/bin/env python3
"""Fresh-install doctor: is this clone usable, and what is it capable of?

Read-only and offline unless --network-check is passed.  Never mutates the
install and never downloads anything.

  python3 tools/doctor.py            # human summary
  python3 tools/doctor.py --json     # machine readable
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "plugins" / "solve-lite" / "skills" / "solve-lite" / "scripts"


def _load():
    if str(SCRIPTS) not in sys.path:
        sys.path.insert(0, str(SCRIPTS))
    import solve_lite_abi
    import solve_lite_dlc

    return solve_lite_abi, solve_lite_dlc


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--asset-root", default=None, help="override the runtime/asset root")
    parser.add_argument("--case", type=Path, default=None, help="also route this case file through the core")
    parser.add_argument("--workspace", type=Path, default=None)
    args = parser.parse_args()

    abi, dlc = _load()
    health = abi.healthcheck(args.asset_root)
    caps = abi.capabilities(args.asset_root)
    routes = abi.available_routes(args.asset_root)
    dlc_state = dlc.capability_view(dlc.default_runtime_root())
    report = {
        "status": health.get("status"),
        "healthcheck": health,
        "capabilities": caps,
        "routes": routes,
        "dlc": dlc_state,
        "network_used": False,
    }
    if args.case:
        workspace = args.workspace or (ROOT / ".solve-lite-workspace")
        workspace.mkdir(parents=True, exist_ok=True)
        case = json.loads(args.case.read_text(encoding="utf-8"))
        report["case_route"] = abi.route_prompt(workspace, case, session={"metadata": {"locale": "en-US"}})
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False))
        return 0 if report["status"] == "PASS" else 2
    print(f"healthcheck      {health.get('status')}  ({health.get('runtime_root_origin')})")
    if health.get("status") != "PASS":
        print(f"  why            {health.get('error')}: {health.get('reason')}")
        return 2
    print(f"runtime root     {health.get('runtime_root')}")
    print(f"native core      {health.get('native_core_status')} ({health.get('native_modules_verified')} modules verified)")
    print(f"native routes    {', '.join(routes.get('native_routes') or [])}")
    print(f"specialist       {routes.get('specialist_status')} / {routes.get('specialist_reason')}")
    print(f"dlc installed    {', '.join(dlc_state.get('installed_units') or []) or 'none'}")
    print(f"dlc execution    {dlc_state.get('specialist_execution_status')} ({dlc_state.get('specialist_execution_reason')})")
    print(f"asset root env   required={health.get('asset_root_required')} legacy_required={health.get('legacy_core_asset_root_required')}")
    if "case_route" in report:
        print(f"case route       {report['case_route'].get('status')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
