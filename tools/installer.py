#!/usr/bin/env python3
"""Install Solve Lite on a host - LITE base plus the public DLC components.

The base install is this repository: it carries the LITE native kernel and the
public ABI, works offline, and needs no asset root.  A plain run also installs
the three public DLC components from this repository's GitHub Release.

--skip-dlc is an engineering-only base-Lite fixture switch; --install-dlc UNIT
installs selected components.  Normal installation includes all three public
components.  The capability router activates only the required component,
loads lazily, and keeps at most one model resident (DLCBusy semantics apply).

  python3 tools/installer.py          # base Lite + the 3 public DLC components
  python3 tools/installer.py --install-dlc review-sst2-distilbert-int4-g64
  python3 tools/installer.py --install-dlc --package-dir DIR   # offline mirror
  python3 tools/installer.py --check  # read-only status report
  python3 tools/installer.py --uninstall-dlc

Never touches the frozen kernel, never installs outside this repository.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "plugins" / "solve-lite" / "skills" / "solve-lite" / "scripts"
MB = 1_000_000
INSTALLED_MANIFEST_REL = Path("runtime") / "CORE_ASSET_MANIFEST_LITE.json"
INSTALLED_ADDON_REL = Path("runtime") / "addons" / "solve-lite-int4-dlc"
INSTALLED_VENV_PYTHON_REL = Path("runtime") / "specialist-env" / "bin" / "python3"


def _mb(value: int) -> str:
    return f"{value / MB:.2f} MB"


def _load(name: str):
    if str(SCRIPTS) not in sys.path:
        sys.path.insert(0, str(SCRIPTS))
    return __import__(name)


def _sha256_file(path: Path) -> str | None:
    if not path.is_file():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _immutable_tree_snapshot(root: Path) -> dict:
    """Hash every installed payload file/symlink, excluding only Python caches."""
    rows: list[str] = []
    total_bytes = 0
    if root.is_dir():
        for path in sorted(root.rglob("*"), key=lambda item: item.as_posix()):
            relative = path.relative_to(root)
            if "__pycache__" in relative.parts or path.suffix in {".pyc", ".pyo"}:
                continue
            try:
                mode = path.lstat().st_mode & 0o777
                if path.is_symlink():
                    target = os.readlink(path)
                    payload = target.encode("utf-8", errors="surrogateescape")
                    kind = "symlink"
                    size = len(payload)
                    digest = hashlib.sha256(payload).hexdigest()
                elif path.is_file():
                    kind = "file"
                    size = path.stat().st_size
                    digest = _sha256_file(path) or ""
                else:
                    continue
            except OSError:
                continue
            total_bytes += size
            rows.append(f"{relative.as_posix()}\0{kind}\0{mode:o}\0{size}\0{digest}")
    content = ("\n".join(rows) + ("\n" if rows else "")).encode("utf-8")
    return {
        "file_count": len(rows),
        "tree_sha256": hashlib.sha256(content).hexdigest(),
        "total_bytes": total_bytes,
    }


def _dlc_install_readback(destination: Path, dlc) -> dict:
    runtime = destination / "runtime"
    addon = destination / INSTALLED_ADDON_REL
    registry_path = addon / "dlc-registry.json"
    try:
        registry = json.loads(registry_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        registry = {}
    records = registry.get("units") if isinstance(registry.get("units"), dict) else {}
    units = {}
    for spec in dlc.DLC_UNITS:
        unit_id = str(spec["unit_id"])
        installed = addon / "installed" / unit_id
        descriptor_path = installed / "dlc.json"
        try:
            descriptor = json.loads(descriptor_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            descriptor = {}
        weights = list(installed.rglob(str(spec.get("container_name") or "model.slint4.safetensors")))
        observed_weights = _sha256_file(weights[0]) if len(weights) == 1 else None
        record = records.get(unit_id) if isinstance(records.get(unit_id), dict) else {}
        route_dirs = [installed / str(relative) for relative in spec.get("route_dirs") or ()]
        present = installed.is_dir() and descriptor_path.is_file() and all(path.is_dir() for path in route_dirs)
        hashes_match = bool(
            descriptor.get("source_package_sha256") == spec.get("package_sha256")
            and descriptor.get("weights_sha256") == spec.get("weights_sha256")
            and record.get("package_sha256") == spec.get("package_sha256")
            and record.get("observed_package_sha256") == spec.get("package_sha256")
            and observed_weights == spec.get("weights_sha256")
        )
        units[unit_id] = {
            "public": bool(spec.get("public")),
            "present": present,
            "descriptor_sha256": _sha256_file(descriptor_path),
            "expected_package_sha256": spec.get("package_sha256"),
            "observed_package_sha256": record.get("observed_package_sha256"),
            "expected_weights_sha256": spec.get("weights_sha256"),
            "observed_weights_sha256": observed_weights,
            "hashes_match": hashes_match,
        }
    public = [value for value in units.values() if value["public"]]
    private = [value for value in units.values() if not value["public"]]
    return {
        "addon_root": str(addon),
        "registry_path": str(registry_path),
        "registry_sha256": _sha256_file(registry_path),
        "units": units,
        "public_units_complete": bool(public) and all(item["present"] and item["hashes_match"] for item in public),
        "financial_dlc_absent": all(not item["present"] for item in private),
        "runtime_root_recorded": str(registry.get("runtime_root") or "") == str(runtime.resolve()),
    }


def installed_destination_readback(destination: Path, dlc, expected: dict | None = None) -> dict:
    destination = Path(destination).expanduser()
    snapshot = _immutable_tree_snapshot(destination)
    skill_md = destination / "SKILL.md"
    manifest = destination / INSTALLED_MANIFEST_REL
    python = destination / INSTALLED_VENV_PYTHON_REL
    dlc_state = _dlc_install_readback(destination, dlc)
    current = {
        "destination": str(destination),
        "destination_exists": destination.is_dir(),
        **snapshot,
        "skill_md_sha256": _sha256_file(skill_md),
        "manifest_sha256": _sha256_file(manifest),
        "installed_runtime_root": str((destination / "runtime").resolve()),
        "installed_addon_root": str((destination / INSTALLED_ADDON_REL).resolve()),
        "installed_specialist_env": str((destination / "runtime" / "specialist-env").resolve()),
        "specialist_python": str(python),
        "specialist_python_exists": python.is_file(),
        "specialist_python_executable": python.is_file() and os.access(python, os.X_OK),
        "dlc": dlc_state,
    }
    if expected is None:
        matches = True
    else:
        matches = all(
            current.get(key) == expected.get(key)
            for key in ("file_count", "tree_sha256", "skill_md_sha256", "manifest_sha256")
        )
    current["destination_hash_match"] = matches
    current["checks"] = {
        "DESTINATION_EXISTS": current["destination_exists"],
        "DEST_SKILL_MD_HASH": bool(current["skill_md_sha256"]),
        "DEST_MANIFEST_HASH": bool(current["manifest_sha256"]),
        "DEST_FILE_COUNT": current["file_count"] > 0,
        "DEST_TREE_HASH": bool(current["tree_sha256"]),
        "DEST_SPECIALIST_PYTHON_EXISTS": current["specialist_python_exists"],
        "DEST_SPECIALIST_PYTHON_EXECUTABLE": current["specialist_python_executable"],
        "DEST_PUBLIC_DLC_COMPLETE": dlc_state["public_units_complete"],
        "FINANCIAL_DLC_ABSENT": dlc_state["financial_dlc_absent"],
        "DLC_RUNTIME_ROOT_RELOCATED": dlc_state["runtime_root_recorded"],
        "DESTINATION_HASH_MATCH": matches,
    }
    current["status"] = "PASS" if all(current["checks"].values()) else "FAIL"
    return current


def _destination_decision_cases() -> list[dict]:
    topic_labels = [
        "Company", "EducationalInstitution", "Artist", "Athlete", "OfficeHolder",
        "MeanOfTransportation", "Building", "NaturalPlace", "Village", "Animal",
        "Plant", "Album", "Film", "WrittenWork",
    ]
    native = json.loads((ROOT / "tests" / "fixtures" / "native_markov_case.json").read_text(encoding="utf-8"))
    return [
        native,
        {"case_id": "installed-review", "family": "amazon_review_polarity",
         "state": {"items": [{"id": "item_0", "text": "This product is excellent and works perfectly."}]},
         "questions": {"q_0": {"type": "noul", "input_ref": "item_0",
                                  "criteria": {"false": "negative review", "true": "positive review"},
                                  "instructions": "Is this a positive review?"}}},
        {"case_id": "installed-topic", "family": "knowledge_topic_routing",
         "state": {"items": [{"id": "item_0", "title": "Apple Inc.",
                               "content": "Apple is a technology company that designs consumer electronics."}]},
         "questions": {"q_0": {"type": "choice", "input_ref": "item_0",
                                  "criteria": {label: label for label in topic_labels},
                                  "instructions": "Classify the topic."}}},
        {"case_id": "installed-nli", "family": "natural_language_inference",
         "state": {"items": [{"id": "item_0", "premise": "A dog is running outside.",
                               "hypothesis": "An animal is outdoors."}]},
         "questions": {"q_0": {"type": "choice", "input_ref": "item_0",
                                  "criteria": {"contradiction": "not entailed", "entailment": "entailed",
                                               "neutral": "uncertain"},
                                  "instructions": "Classify the relation."}}},
    ]


def run_installed_destination(destination: Path) -> dict:
    """Run health/native/Review/Topic/NLI only with the installed interpreter/code."""
    destination = Path(destination).expanduser()
    python = destination / INSTALLED_VENV_PYTHON_REL
    scripts = destination / "scripts"
    runtime = destination / "runtime"
    if not (python.is_file() and os.access(python, os.X_OK) and scripts.is_dir()):
        return {"status": "FAIL", "reason": "INSTALLED_RUNTIME_MISSING", "python": str(python)}
    program = (
        "import json,pathlib,sys,tempfile;"
        f"scripts=pathlib.Path({str(scripts)!r});runtime=pathlib.Path({str(runtime)!r});"
        "sys.path.insert(0,str(scripts));import solve_lite_abi as A;"
        f"cases={_destination_decision_cases()!r};"
        "health=A.healthcheck(runtime);rows=[];"
        "\nfor case in cases:\n"
        "  with tempfile.TemporaryDirectory() as workspace:\n"
        "    result=A.route_prompt(workspace,case,{'metadata':{'locale':'en-US'}},asset_root=runtime,invocation_id='installed:'+str(case.get('case_id')))\n"
        "  rows.append({'case_id':case.get('case_id'),'family':case.get('family'),'status':result.get('status'),"
        "'route':result.get('adapter_route'),'answers':len(result.get('answers') or {}),"
        "'runtime_root':result.get('runtime_root'),'network_model_calls':result.get('network_model_calls'),"
        "'isolated_venv':(result.get('specialist_process') or {}).get('isolated_venv')})\n"
        "print(json.dumps({'python':sys.executable,'health':health,'rows':rows}))"
    )
    env = dict(os.environ)
    state_dir = Path(tempfile.mkdtemp(prefix="solve-lite-installed-state-"))
    env.update({
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONNOUSERSITE": "1",
        "SOLVE_LITE_RUNTIME_ROOT": str(runtime),
        "SOLVE_LITE_INT4_STATE_DIR": str(state_dir),
    })
    for name in ("PYTHONPATH", "SOLVE_LITE_INT4_DLC_ROOT", "SOLVE_LITE_SPECIALIST_WORKER"):
        env.pop(name, None)
    try:
        proc = subprocess.run(
            [str(python), "-I", "-c", program], cwd=str(destination), env=env,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=False, timeout=900,
        )
        payload = json.loads((proc.stdout or "").strip().splitlines()[-1]) if proc.returncode == 0 else {}
    except (OSError, subprocess.SubprocessError, ValueError, IndexError) as exc:
        shutil.rmtree(state_dir, ignore_errors=True)
        return {"status": "FAIL", "reason": type(exc).__name__, "python": str(python)}
    shutil.rmtree(state_dir, ignore_errors=True)
    rows = payload.get("rows") if isinstance(payload.get("rows"), list) else []
    by_family = {str(row.get("family")): row for row in rows if isinstance(row, dict)}
    native = rows[0] if rows else {}
    expected_runtime = str(runtime.resolve())
    checks = {
        "INSTALLED_INTERPRETER": Path(str(payload.get("python") or "")).resolve() == python.resolve(),
        "INSTALLED_HEALTHCHECK": (payload.get("health") or {}).get("status") == "PASS",
        "INSTALLED_NATIVE_DECISION": native.get("status") == "PASS" and int(native.get("answers") or 0) > 0,
        "INSTALLED_REVIEW_DECISION": by_family.get("amazon_review_polarity", {}).get("status") == "PASS",
        "INSTALLED_TOPIC_DECISION": by_family.get("knowledge_topic_routing", {}).get("status") == "PASS",
        "INSTALLED_NLI_DECISION": by_family.get("natural_language_inference", {}).get("status") == "PASS",
        "INSTALLED_RUNTIME_ONLY": all(str(row.get("runtime_root") or "") == expected_runtime for row in rows),
        "NO_NETWORK_MODEL_CALLS": all(int(row.get("network_model_calls") or 0) == 0 for row in rows),
    }
    return {
        "status": "PASS" if proc.returncode == 0 and all(checks.values()) else "FAIL",
        "returncode": proc.returncode,
        "python": payload.get("python"),
        "checks": checks,
        "health": payload.get("health"),
        "rows": rows,
        "stderr": (proc.stderr or "")[-500:],
    }


def no_native_hook_acceptance(plugin_root: Path, host_id: str, detected: dict,
                              selftest: dict, runtime_hook_api: str) -> dict:
    """Accept a no-hook host only when every explicit fallback proof passes."""
    registry = json.loads(
        (plugin_root / "skills" / "solve-lite" / "assets" / "agent_registry.json")
        .read_text(encoding="utf-8")
    )
    registry_host = next(
        (item for item in registry.get("hosts", []) if item.get("host_id") == host_id),
        {},
    )
    checks = selftest.get("checks") or {}
    return {
        "registry_declares_no_hook_api": registry_host.get("hook_api") is False,
        "runtime_declares_no_hook_api": runtime_hook_api == "none",
        "mandatory_banner": bool(
            detected.get("skill_installed") and detected.get("mandatory_first_step_present")
        ),
        "one_step_selftest": selftest.get("HOOK_FIRED") == "PASS",
        "real_decision": bool(
            checks.get("ENVELOPE_INJECTED") and checks.get("NO_MODEL_DISCRETION")
        ),
    }


def disclosure(dlc, health: dict | None = None, specialist=None) -> dict:
    units = [spec for spec in dlc.DLC_UNITS if spec["public"]]
    blocked = [spec for spec in dlc.DLC_UNITS if not spec["public"]]
    base_bytes = dlc.base_install_bytes(ROOT)
    dlc_bytes = sum(int(spec["package_bytes"] or 0) for spec in units)
    runtime_paths = specialist.runtime_paths(dlc.default_runtime_root()) if specialist else {}
    specialist_bytes = specialist.directory_bytes(runtime_paths["venv"]) if specialist else 0
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
                "layer": "SHARED_SPECIALIST_RUNTIME",
                "what": "repo-local pinned Python environment; dormant on the Lite path",
                "installed_bytes": specialist_bytes,
                "installed_human": _mb(specialist_bytes),
                "requires_network": True,
                "global_python_mutation": False,
            },
            {
                "layer": "DLC_COMPONENTS",
                "what": "public specialist capabilities, installed by default and loaded lazily",
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
            "Lite Core and the public DLC layer remain separate size classes. Normal public "
            "installation includes all three DLC packages; runtime loading remains lazy."
        ),
    }


def report(abi, dlc, specialist) -> int:
    health = abi.healthcheck()
    caps = abi.capabilities()
    specialist_health = specialist.healthcheck(dlc.default_runtime_root(), deep=False)
    layers = disclosure(dlc, health, specialist)
    payload = {
        "status": health.get("status"),
        "healthcheck": health,
        "capabilities": caps,
        "specialist_runtime": specialist_health,
        "install": layers,
    }
    print(json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False))
    return 0 if health.get("status") == "PASS" else 2


def render(layers: dict, health: dict) -> None:
    print(f"BASE_LITE  healthcheck={health.get('status')}  runtime={health.get('runtime_root_origin')}")
    print(f"  installed size         {layers['base_only_install']}  (no network, no model pack)")
    print("SHARED_SPECIALIST_RUNTIME (repo-local, pinned, dormant on Lite startup)")
    print(f"  installed size         {layers['layers'][1]['installed_human']}")
    print("DLC_COMPONENTS (installed by default, capability-routed lazy load)")
    for unit in layers["layers"][2]["units"]:
        print(f"  {unit['unit_id']:<24} download {unit['download_human']:>9}  {unit['capability']}")
    print(f"  {'total public DLC':<24} download {layers['layers'][2]['download_human']:>9}")
    for unit in layers["layers"][2]["not_public"]:
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


def register_host_hooks(host: str, plugin_root: Path, config_dir: Path = None, dlc=None) -> dict:
    """P1: install-time host registration, with the fallback command when the
    host exposes no writable hook location."""
    if not host or host in ("none",):
        return {"status": "SKIPPED", "reason": "no --host requested"}
    if str(ROOT / "tools") not in sys.path:
        sys.path.insert(0, str(ROOT / "tools"))
    import host_hooks  # noqa: PLC0415

    hosts = ["workbuddy", "doubao"] if host == "auto" else [host]
    payload = {"status": "PASS", "hosts": {}, "one_step_command": host_hooks.one_step_command(plugin_root)}
    for host_id in hosts:
        try:
            outcome = host_hooks.register(host_id, plugin_root, override=config_dir)
            if host_id == "doubao" and outcome.get("status") == "UNAVAILABLE_EXPECTED":
                import hook_selftest  # noqa: PLC0415

                destination = Path((outcome.get("skill") or {}).get("destination") or "")
                detected = host_hooks.detect(host_id, config_dir)
                post_copy = installed_destination_readback(destination, dlc)
                if post_copy.get("status") == "PASS":
                    selftest = hook_selftest.selftest_host(
                        host_id, plugin_root, config_dir=destination, runs=1
                    )
                    installed_runtime = run_installed_destination(destination)
                else:
                    selftest = {"HOOK_FIRED": "FAIL", "checks": {}, "reason": "POST_COPY_READBACK_FAILED"}
                    installed_runtime = {"status": "FAIL", "reason": "POST_COPY_READBACK_FAILED"}
                post_final = installed_destination_readback(destination, dlc, expected=post_copy)
                checks = selftest.get("checks") or {}
                acceptance = no_native_hook_acceptance(
                    plugin_root,
                    host_id,
                    detected,
                    selftest,
                    host_hooks.host_spec(host_id).hook_api,
                )
                destination_mutated = not bool(post_final.get("destination_hash_match"))
                destination_acceptance = {
                    "post_copy_readback": post_copy.get("status") == "PASS",
                    "installed_healthcheck": bool((installed_runtime.get("checks") or {}).get("INSTALLED_HEALTHCHECK")),
                    "installed_native_decision": bool((installed_runtime.get("checks") or {}).get("INSTALLED_NATIVE_DECISION")),
                    "installed_specialist_decisions": all(
                        bool((installed_runtime.get("checks") or {}).get(name))
                        for name in (
                            "INSTALLED_REVIEW_DECISION", "INSTALLED_TOPIC_DECISION", "INSTALLED_NLI_DECISION"
                        )
                    ),
                    "installed_interpreter": bool((installed_runtime.get("checks") or {}).get("INSTALLED_INTERPRETER")),
                    "post_install_final_readback": post_final.get("status") == "PASS",
                    "destination_not_mutated_after_install": not destination_mutated,
                }
                acceptance["installed_destination"] = all(destination_acceptance.values())
                accepted = all(acceptance.values())
                outcome["acceptance"] = acceptance
                outcome["destination_acceptance"] = destination_acceptance
                outcome["POST_COPY_READBACK"] = post_copy
                outcome["installed_runtime_tests"] = installed_runtime
                outcome["POST_INSTALL_FINAL_READBACK"] = post_final
                outcome["DESTINATION_MUTATED_AFTER_INSTALL"] = destination_mutated
                outcome["one_step_evidence"] = {
                    "HOOK_FIRED": selftest.get("HOOK_FIRED"),
                    "checks": checks,
                    "latency_ms": selftest.get("latency_ms"),
                    "peak_rss_mb": selftest.get("peak_rss_mb"),
                }
                outcome["status"] = (
                    "PASS_ACCEPTED_NO_NATIVE_HOOK" if accepted else "FAIL_NO_NATIVE_HOOK_CONTRACT"
                )
        except Exception as exc:  # noqa: BLE001 - never fail the install on a host quirk
            outcome = {"status": "FAIL", "error": f"{type(exc).__name__}: {exc}"}
        payload["hosts"][host_id] = outcome
        if str(outcome.get("status")) not in (
            "PASS", "REGISTERED", "PASS_ACCEPTED_NO_NATIVE_HOOK"
        ):
            payload["status"] = "PARTIAL"
    return payload


def preassemble_dlc_view(dlc, runtime: Path) -> dict:
    """P1: pre-assemble the runtime asset view at install time.

    The first specialist call must not pay for symlink assembly, so it happens
    here, once, and the second call proves the step is idempotent.
    """
    started = time.perf_counter()
    try:
        first = dlc.assemble_asset_root(runtime)
    except Exception as exc:  # noqa: BLE001
        return {"status": "FAIL", "error": f"{type(exc).__name__}: {exc}",
                "preassemble_ms": round((time.perf_counter() - started) * 1000.0, 3)}
    first_ms = (time.perf_counter() - started) * 1000.0
    started = time.perf_counter()
    second = dlc.assemble_asset_root(runtime)
    return {
        "status": "PASS",
        "preassemble_ms": round(first_ms, 3),
        "second_call_ms": round((time.perf_counter() - started) * 1000.0, 3),
        "first_view": first,
        "second_view": second,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--check", action="store_true", help="verify the base install (default)")
    parser.add_argument("--install-dlc", nargs="*", default=None, metavar="UNIT", help="install public DLC components")
    parser.add_argument("--skip-dlc", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--skip-startup-check", action="store_true", help="do not run the startup checker")
    parser.add_argument("--keep-packages", action="store_true", help="keep downloaded DLC packages")
    parser.add_argument("--uninstall-dlc", action="store_true", help="remove installed DLC components")
    parser.add_argument("--package-dir", type=Path, default=None, help="directory of DLC packages (offline mirror)")
    parser.add_argument("--specialist-wheel-dir", type=Path, default=None,
                        help="offline wheel mirror for the pinned repo-local specialist environment")
    parser.add_argument("--specialist-python", type=Path, default=None,
                        help="compatible Python used only to create the repo-local specialist environment")
    parser.add_argument("--release-base", default=None, help="override the release base URL")
    parser.add_argument("--no-verify", action="store_true", help="skip package checksum verification (not recommended)")
    parser.add_argument("--host", default="none",
                        help="register the unconditional UserPromptSubmit hook: workbuddy|doubao|auto|none")
    parser.add_argument("--config-dir", type=Path, default=None,
                        help="override the host config directory (isolated installs and host-shaped tests)")
    parser.add_argument("--no-preassemble", action="store_true",
                        help="skip the install-time DLC asset-view pre-assembly")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    abi = _load("solve_lite_abi")
    dlc = _load("solve_lite_dlc")
    specialist = _load("specialist_runtime")

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
        return report(abi, dlc, specialist)

    health = abi.healthcheck()
    if health.get("status") != "PASS":
        print(json.dumps(health, indent=2, sort_keys=True))
        return 2

    layers = disclosure(dlc, health, specialist)
    if not args.json:
        render(layers, health)
    if args.skip_dlc:
        specialist_state = {"status": "SKIPPED", "reason": "engineering base-Lite fixture"}
        summary = {"status": "SKIPPED", "results": [], "units_installed": 0, "installed_unit_ids": []}
        summary["message"] = "DLC skipped (--skip-dlc); base Lite is available now"
    else:
        specialist_state = specialist.ensure(
            runtime,
            python=args.specialist_python,
            wheel_dir=args.specialist_wheel_dir,
        )
        if specialist_state.get("status") != "PASS":
            payload = {
                "status": "FAIL",
                "required_checks": {"specialist_runtime": False},
                "healthcheck": health,
                "install": layers,
                "specialist_runtime": specialist_state,
            }
            print(json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False))
            return 3
        wanted = args.install_dlc or [s["unit_id"] for s in dlc.DLC_UNITS if s["public"]]
        results = dlc.install_units(wanted, runtime_root=runtime, package_dir=args.package_dir,
                                    base_url=base_url, verify=verify,
                                    keep_packages=args.keep_packages)
        summary = dlc.summarise(results)
        if not args.json:
            for item in results:
                print("  " + str(item["status"]) + " " + str(item["unit_id"]))
    state = dlc.capability_view(runtime)
    health = abi.healthcheck()
    layers = disclosure(dlc, health, specialist)
    installed_units = list(summary.get("installed_unit_ids") or [])
    preassembly = {"status": "SKIPPED", "reason": "no installed public DLC unit"}
    if installed_units and not args.no_preassemble:
        preassembly = preassemble_dlc_view(dlc, runtime)
        if not args.json:
            print("DLC_PREASSEMBLED=%s  preassemble_ms=%s  second_call_ms=%s"
                  % (preassembly.get("status"), preassembly.get("preassemble_ms"),
                     preassembly.get("second_call_ms")))
    registration = register_host_hooks(
        str(args.host), ROOT / "plugins" / "solve-lite", args.config_dir, dlc=dlc
    )
    if not args.json and registration.get("status") != "SKIPPED":
        print("HOST_HOOK_REGISTRATION=%s  hosts=%s" % (registration.get("status"),
                                                       ",".join(registration.get("hosts", {}))))
        print("解决不了就照抄这条一步命令: " + str(registration.get("one_step_command")))
    startup = {"status": "SKIPPED", "returncode": None}
    if not args.skip_startup_check:
        startup = run_startup_check(ROOT)
        if not args.json:
            print("STARTUP_CHECK=" + str(startup["status"]))
            if startup["status"] == "FAIL":
                print("STARTUP_CHECK=FAIL  see tools/startup_check.py --root . --json")
    required_checks = {
        "healthcheck": health.get("status") == "PASS",
        "specialist_runtime": args.skip_dlc or specialist_state.get("status") == "PASS",
        "dlc_install": args.skip_dlc or summary.get("status") == "PASS",
        "dlc_preassembly": preassembly.get("status") in ("PASS", "SKIPPED"),
        "host_registration": registration.get("status") in ("PASS", "SKIPPED"),
        "startup_check": startup.get("status") in ("PASS", "SKIPPED"),
    }
    overall_status = "PASS" if all(required_checks.values()) else "FAIL"
    payload = {"status": overall_status, "required_checks": required_checks,
               "healthcheck": health, "install": layers,
               "specialist_runtime": specialist_state,
               "dlc": {"summary": summary, "capability": state, "preassembly": preassembly},
               "host_registration": registration, "startup_check": startup}
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False))
    else:
        names = ", ".join(summary.get("installed_unit_ids") or [])
        print("installed DLC: " + (names or "none"))
        print(summary["message"])
        print("specialist execution: " + str(state.get("specialist_execution_status")))
        print("specialist activation: automatic capability routing; lazy; max resident DLC=1")
    if overall_status != "PASS":
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
