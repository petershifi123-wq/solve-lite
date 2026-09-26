#!/usr/bin/env python3
"""Install Solve Lite on a host - LITE base plus the public DLC components.

The base install is this repository: it carries the LITE native kernel and the
public ABI, works offline, and needs no asset root.  A plain run also installs
the three public DLC components from this repository's GitHub Release.

--skip-dlc installs base Lite only; --install-dlc UNIT installs selected
components.  Activating a component is separately opt-in and off by default:
SOLVE_LITE_INT4_DLC=1 (lazy, one resident model, DLCBusy).

  python3 tools/installer.py          # base Lite + the 3 public DLC components
  python3 tools/installer.py --skip-dlc
  python3 tools/installer.py --install-dlc review-sst2-distilbert-int4-g64
  python3 tools/installer.py --install-dlc --package-dir DIR   # offline mirror
  python3 tools/installer.py --check  # read-only status report
  python3 tools/installer.py --uninstall-dlc

Never touches the frozen kernel, never installs outside this repository.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "plugins" / "solve-lite" / "skills" / "solve-lite" / "scripts"
MB = 1_000_000


def _mb(value: int) -> str:
    return f"{value / MB:.2f} MB"


def _load(name: str):
    if str(SCRIPTS) not in sys.path:
        sys.path.insert(0, str(SCRIPTS))
    return __import__(name)


def disclosure(dlc, health: dict | None = None) -> dict:
    units = [spec for spec in dlc.DLC_UNITS if spec["public"]]
    blocked = [spec for spec in dlc.DLC_UNITS if not spec["public"]]
    base_bytes = dlc.base_install_bytes(ROOT)
    dlc_bytes = sum(int(spec["package_bytes"] or 0) for spec in units)
    return {
        "base_install_bytes": base_bytes,
        "base_healthcheck": (health or {}).get("status"),
        "dlc_total_download_bytes": dlc_bytes,
        "financial_dlc": "NOT_PUBLIC",
        "layers": [
            {
                "layer": "BASE_LITE",
                "what": "native kernel + public ABI + host integration",
                "installed_bytes": base_bytes,
                "installed_human": _mb(base_bytes),
                "requires_network": False,
                "requires_model_pack": False,
            },
            {
                "layer": "DLC_COMPONENTS",
                "what": "specialist capabilities, installed on request",
                "units": [
                    {
                        "unit_id": spec["unit_id"],
                        "capability": spec["capability"],
                        "download_bytes": spec["package_bytes"],
                        "download_human": _mb(spec["package_bytes"]),
                        "package": spec["package"],
                    }
                    for spec in units
                ],
                "download_bytes": sum(spec["package_bytes"] for spec in units),
                "download_human": _mb(sum(spec["package_bytes"] for spec in units)),
                "requires_network": True,
                "not_public": [
                    {"unit_id": spec["unit_id"], "license_class": spec["license_class"], "status": "NOT_PUBLIC"}
                    for spec in blocked
                ],
            },
        ],
        "base_only_install": _mb(base_bytes),
        "base_plus_public_dlc_install": _mb(base_bytes + sum(spec["package_bytes"] for spec in units)),
        "note": (
            "Lite alone is the numbers under BASE_LITE. The DLC layer is separate and "
            "optional; quoting a single total for 'the install' hides which layer is meant."
        ),
    }


def report(abi, dlc) -> int:
    health = abi.healthcheck()
    caps = abi.capabilities()
    layers = disclosure(dlc, health)
    payload = {
        "status": health.get("status"),
        "healthcheck": health,
        "capabilities": caps,
        "install": layers,
    }
    print(json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False))
    return 0 if health.get("status") == "PASS" else 2


def render(layers: dict, health: dict) -> None:
    print(f"BASE_LITE  healthcheck={health.get('status')}  runtime={health.get('runtime_root_origin')}")
    print(f"  installed size         {layers['base_only_install']}  (no network, no model pack)")
    print("DLC_COMPONENTS (optional, installed on request)")
    for unit in layers["layers"][1]["units"]:
        print(f"  {unit['unit_id']:<24} download {unit['download_human']:>9}  {unit['capability']}")
    print(f"  {'total public DLC':<24} download {layers['layers'][1]['download_human']:>9}")
    for unit in layers["layers"][1]["not_public"]:
        print(f"  {unit['unit_id']:<24} NOT_PUBLIC ({unit['license_class']})")
    print(f"  base + all public DLC  {layers['base_plus_public_dlc_install']}")


def run_startup_check(root: Path) -> dict:
    """Run tools/startup_check.py --json and report its verdict verbatim."""
    script = ROOT / "tools" / "startup_check.py"
    if not script.is_file():
        return {"status": "FAIL", "returncode": None, "detail": "tools/startup_check.py missing"}
    proc = subprocess.run([sys.executable, str(script), "--root", str(root), "--json"],
                          cwd=str(root), stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=False)
    parsed = {}
    whole = (proc.stdout or "").strip()
    if whole.startswith("{"):
        try:
            parsed = json.loads(whole)
        except ValueError:
            parsed = {}
    for line in reversed(whole.splitlines()):
        if isinstance(parsed, dict) and parsed:
            break
        try:
            loaded = json.loads(line)
        except ValueError:
            continue
        if isinstance(loaded, dict):
            parsed = loaded
            break
    value = parsed.get("STARTUP_CHECK") or parsed.get("startup_check")
    ok = proc.returncode == 0 and value == "PASS"
    return {"status": "PASS" if ok else "FAIL", "returncode": proc.returncode,
            "checks": parsed.get("checks"), "stderr": (proc.stderr or "").strip()[-300:]}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--check", action="store_true", help="verify the base install (default)")
    parser.add_argument("--install-dlc", nargs="*", default=None, metavar="UNIT", help="install public DLC components")
    parser.add_argument("--skip-dlc", action="store_true", help="install base Lite only (no DLC components)")
    parser.add_argument("--skip-startup-check", action="store_true", help="do not run the startup checker")
    parser.add_argument("--keep-packages", action="store_true", help="keep downloaded DLC packages")
    parser.add_argument("--uninstall-dlc", action="store_true", help="remove installed DLC components")
    parser.add_argument("--package-dir", type=Path, default=None, help="directory of DLC packages (offline mirror)")
    parser.add_argument("--release-base", default=None, help="override the release base URL")
    parser.add_argument("--no-verify", action="store_true", help="skip package checksum verification (not recommended)")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    abi = _load("solve_lite_abi")
    dlc = _load("solve_lite_dlc")

    if args.uninstall_dlc:
        runtime = dlc.default_runtime_root()
        removed = [dlc.uninstall_unit(spec["unit_id"], runtime_root=runtime) for spec in dlc.DLC_UNITS]
        payload = {"status": "PASS", "uninstalled": removed}
        print(json.dumps(payload, indent=2, sort_keys=True) if args.json else f"removed: {', '.join(removed) or 'nothing'}")
        return 0

    runtime = dlc.default_runtime_root()
    verify = not args.no_verify
    log = None if args.json else (lambda message: print(f"  {message}", file=sys.stderr))
    base_url = args.release_base or dlc.RELEASE_BASE_URL


    if args.check:
        return report(abi, dlc)

    health = abi.healthcheck()
    if health.get("status") != "PASS":
        print(json.dumps(health, indent=2, sort_keys=True))
        return 2

    if args.check:
        return report(abi, dlc)
    health = abi.healthcheck()
    if health.get("status") != "PASS":
        print(json.dumps(health, indent=2, sort_keys=True))
        return 2
    layers = disclosure(dlc, health)
    if not args.json:
        render(layers, health)
    if args.skip_dlc:
        summary = {"status": "SKIPPED", "results": [], "units_installed": 0, "installed_unit_ids": []}
        summary["message"] = "DLC skipped (--skip-dlc); base Lite is available now"
    else:
        wanted = args.install_dlc or [s["unit_id"] for s in dlc.DLC_UNITS if s["public"]]
        results = dlc.install_units(wanted, runtime_root=runtime, package_dir=args.package_dir,
                                    base_url=base_url, verify=verify,
                                    keep_packages=args.keep_packages)
        summary = dlc.summarise(results)
        if not args.json:
            for item in results:
                print("  " + str(item["status"]) + " " + str(item["unit_id"]))
    state = dlc.capability_view(runtime)
    startup = {"status": "SKIPPED", "returncode": None}
    if not args.skip_startup_check:
        startup = run_startup_check(ROOT)
        if not args.json:
            print("STARTUP_CHECK=" + str(startup["status"]))
            if startup["status"] == "FAIL":
                print("STARTUP_CHECK=FAIL  see tools/startup_check.py --root . --json")
    payload = {"status": health.get("status"), "healthcheck": health, "install": layers,
               "dlc": {"summary": summary, "capability": state}, "startup_check": startup}
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False))
    else:
        names = ", ".join(summary.get("installed_unit_ids") or [])
        print("installed DLC: " + (names or "none"))
        print(summary["message"])
        print("specialist execution: " + str(state.get("specialist_execution_status")))
        print("activation is opt-in: " + dlc.ACTIVATION_ENV + "=1")
    if startup["status"] == "FAIL":
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
