"""Public Solve Lite ABI bridge - LITE-first.

This module is the only entrypoint a host needs.  On a fresh install the bundled
LITE runtime is found without any configuration: there is no core asset root to
supply, no 2.33 GB model pack to fetch, and no Owner-supplied asset tree.

Contract
--------
  bundled native Core missing / hash mismatch / ABI mismatch -> CORE_ASSET_UNAVAILABLE
  Specialist DLC component not installed / not complete      -> SPECIALIST_CAPABILITY_UNAVAILABLE
  Nothing else blocks: the native decision path is executable the moment the
  plugin tree exists on disk.

Design rules kept from the sealed LITE line:

* no network at import, during healthcheck, or during routing;
* no torch/transformers import on the startup or native path;
* never substitute a computation for a missing capability;
* every failure is returned as a structured mapping - this module does not
  raise out of ``healthcheck``, ``route_prompt`` or ``capabilities``.
"""

from __future__ import annotations

import hashlib
import json
import os
import platform
import subprocess
import sys
from pathlib import Path
from typing import Any, Mapping

ENTRYPOINT = "solve_lite_abi:route_prompt"
CORE_ENTRYPOINT = "solve_lite.abi:route_session"
CORE_HEALTHCHECK = "solve_lite.abi:healthcheck"
MODULE_NAME = "solve_lite.abi"
BUILD_LINE = "LITE"

ERROR_CORE = "CORE_ASSET_UNAVAILABLE"
#: there is no separate "missing asset root" code any more: the LITE runtime ships
#: with the package, so the only remaining failure is a core that is absent or
#: damaged (VV ruling: the retired missing-asset-root code is no longer used).
#: older host that still compares against it reads the same real-core code.
ERROR_ROOT = ERROR_CORE
ERROR_SPECIALIST = "SPECIALIST_CAPABILITY_UNAVAILABLE"

ABI_SCHEMA = "solve-lite.public-abi.lite.v1"

#: default location of the bundled runtime, relative to this file
BUNDLED_RUNTIME_RELATIVE = Path("..") / "runtime"

ENV_RUNTIME_ROOT = "SOLVE_LITE_RUNTIME_ROOT"
#: backward-compatible explicit switch. Public routing now activates an installed
#: specialist backend lazily when (and only when) the admitted case needs it.
BACKEND_ENV = "SOLVE_LITE_INT4_DLC"
DLC_RUNTIME_DIRNAME = "dlc_runtime"
ACTIVATION_ROOT_ENV = "SOLVE_LITE_INT4_DLC_ROOT"
SPECIALIST_WORKER_ENV = "SOLVE_LITE_SPECIALIST_WORKER"
_BACKEND_STATE: dict[str, Any] = {}
#: honoured for backward compatibility only - never required on a fresh install

KERNEL_DIRNAME = "_kernel_native"
MODULE_SUFFIX = ".so"


def _tree_root() -> Path:
    """Repository root when this file is checked out, else the plugin root."""
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / "PUBLIC_REPO_MANIFEST.json").is_file() or (parent / "plugins").is_dir():
            return parent
    return here.parents[2]


def _skill_root() -> Path:
    return Path(__file__).resolve().parents[1]


def skill_root() -> Path:
    return _skill_root()


def bundled_runtime_root() -> Path:
    return (Path(__file__).resolve().parent / BUNDLED_RUNTIME_RELATIVE).resolve()


def manifest_candidates() -> list[Path]:
    root = _tree_root()
    return [
        _skill_root() / "CORE_ASSET_MANIFEST.json",
        root / "CORE_ASSET_MANIFEST.json",
        bundled_runtime_root() / "CORE_ASSET_MANIFEST_LITE.json",
    ]


def _abi_mismatch() -> str | None:
    if platform.system() != "Darwin":
        return f"UNSUPPORTED_PLATFORM:{platform.system()}"
    if sys.version_info[:2] != (3, 9):
        return f"UNSUPPORTED_PYTHON_ABI:cp{sys.version_info[0]}{sys.version_info[1]}"
    return None


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_manifest() -> tuple[Path | None, dict[str, Any]]:
    """Public Lite manifest; the first readable candidate wins."""
    for path in manifest_candidates():
        if path.is_file():
            try:
                return path, json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
    return None, {}


def _runtime_root_candidates(asset_root: str | Path | None) -> list[tuple[Path, str]]:
    candidates: list[tuple[Path, str]] = []
    if asset_root:
        candidates.append((Path(asset_root).expanduser(), "explicit_argument"))
    for env_name, origin in (
        (ENV_RUNTIME_ROOT, "env_SOLVE_LITE_RUNTIME_ROOT"),
    ):
        import os

        value = os.environ.get(env_name)
        if value:
            candidates.append((Path(value).expanduser(), origin))
    candidates.append((bundled_runtime_root(), "bundled"))
    return candidates


def locate_runtime_root(asset_root: str | Path | None = None) -> tuple[Path | None, str]:
    """Return ``(root, origin)`` for the first usable runtime root."""
    for root, origin in _runtime_root_candidates(asset_root):
        try:
            if (root / "solve_lite").is_dir():
                return root.resolve(), origin
        except OSError:
            continue
    return None, "unresolved"


def _native_status(root: Path, manifest: Mapping[str, Any]) -> dict[str, Any]:
    """Hash-verify the bundled native modules.  This is the only hard gate."""
    entries = [
        item
        for item in manifest.get("artifacts", [])
        if isinstance(item, Mapping) and item.get("kind") == "native_kernel_module"
    ] or [
        item
        for item in manifest.get("artifacts", [])
        if isinstance(item, Mapping) and str(item.get("relative_path", "")).endswith(MODULE_SUFFIX)
    ]
    kernel = root / "solve_lite" / "lite_runtime" / KERNEL_DIRNAME
    if not entries:
        return {
            "status": "FAIL",
            "reason": ERROR_CORE,
            "detail": "manifest lists no native kernel modules",
            "modules": [],
        }
    if not kernel.is_dir():
        return {
            "status": "FAIL",
            "reason": ERROR_CORE,
            "detail": f"native kernel directory missing: {kernel.name}",
            "modules": [],
        }
    verified: list[dict[str, Any]] = []
    for entry in entries:
        relative = Path(str(entry.get("relative_path") or "")).name
        target = kernel / relative
        if not target.is_file():
            return {
                "status": "FAIL",
                "reason": ERROR_CORE,
                "detail": f"native module missing: {relative}",
                "modules": verified,
            }
        digest = _sha256_file(target)
        expected = str(entry.get("sha256") or "")
        if not expected or digest != expected:
            return {
                "status": "FAIL",
                "reason": ERROR_CORE,
                "detail": f"native module hash mismatch: {relative}",
                "modules": verified,
            }
        verified.append({"file": relative, "sha256": digest, "rebuilt": bool(entry.get("rebuilt"))})
    return {
        "status": "AVAILABLE",
        "reason": "NATIVE_CORE_VERIFIED",
        "modules": verified,
        "modules_verified": len(verified),
        "rebuilt_modules": [item["file"] for item in verified if item["rebuilt"]],
    }


_CORE_CACHE: dict[str, Any] = {}


def load_core(asset_root: str | Path | None = None) -> dict[str, Any]:
    """Resolve, verify and import the LITE core.  Never raises."""
    try:
        manifest_path, manifest = load_manifest()
        if manifest_path is None:
            return {
                "status": "BLOCKED",
                "error": ERROR_CORE,
                "reason": "CORE_MANIFEST_MISSING",
                "detail": "CORE_ASSET_MANIFEST.json not found",
                "entrypoint": ENTRYPOINT,
            }
        root, origin = locate_runtime_root(asset_root)
        if root is None:
            # unreachable on a normal install: the bundled LITE runtime is part of
            # the package.  Only a damaged/rebuilt tree lacking runtime/solve_lite
            # can land here, so it is reported as core damage, not as a missing
            # asset that the user is expected to supply.
            return {
                "status": "BLOCKED",
                "error": ERROR_CORE,
                "reason": "CORE_RUNTIME_NOT_FOUND",
                "detail": "bundled LITE runtime not found or damaged (reinstall the package)",
                "entrypoint": ENTRYPOINT,
            }
        mismatch = _abi_mismatch()
        if mismatch:
            return {
                "status": "BLOCKED",
                "error": ERROR_CORE,
                "reason": "ABI_MISMATCH",
                "detail": mismatch,
                "runtime_root": str(root),
                "entrypoint": ENTRYPOINT,
            }
        native = _native_status(root, manifest)
        if native["status"] != "AVAILABLE":
            return {
                "status": "BLOCKED",
                "error": ERROR_CORE,
                "reason": native.get("detail") or ERROR_CORE,
                "native_core": native,
                "runtime_root": str(root),
                "runtime_root_origin": origin,
                "entrypoint": ENTRYPOINT,
            }
        key = str(root)
        module = _CORE_CACHE.get(key)
        if module is None:
            if key not in sys.path:
                sys.path.insert(0, key)
            import importlib

            module = importlib.import_module(MODULE_NAME)
            resolved = Path(getattr(module, "__file__", "") or "").resolve()
            if not str(resolved).startswith(str(root)):
                return {
                    "status": "BLOCKED",
                    "error": ERROR_CORE,
                    "reason": "MODULE_OUTSIDE_RUNTIME_ROOT",
                    "detail": f"{MODULE_NAME} resolved outside the runtime root",
                    "runtime_root": str(root),
                    "entrypoint": ENTRYPOINT,
                }
            if not all(callable(getattr(module, name, None)) for name in ("route_session", "healthcheck")):
                return {
                    "status": "BLOCKED",
                    "error": ERROR_CORE,
                    "reason": "ENTRYPOINT_MISSING",
                    "detail": f"{MODULE_NAME} does not expose route_session/healthcheck",
                    "runtime_root": str(root),
                    "entrypoint": ENTRYPOINT,
                }
            _CORE_CACHE[key] = module
        return {
            "status": "AVAILABLE",
            "module": module,
            "runtime_root": str(root),
            "runtime_root_origin": origin,
            "manifest_path": str(manifest_path),
            "manifest": manifest,
            "native_core": native,
            "entrypoint": ENTRYPOINT,
        }
    except Exception as exc:  # noqa: BLE001 - the public entrypoint never raises
        return {
            "status": "BLOCKED",
            "error": ERROR_CORE,
            "reason": f"LOADER_EXCEPTION:{type(exc).__name__}",
            "detail": str(exc),
            "entrypoint": ENTRYPOINT,
        }


def locate_core(asset_root: str | Path | None = None) -> dict[str, Any]:
    """Backward-compatible alias: previous releases returned a core descriptor."""
    loaded = load_core(asset_root)
    if loaded.get("status") != "AVAILABLE":
        return loaded
    return {
        "status": "AVAILABLE",
        "runtime_root": loaded["runtime_root"],
        "entrypoint": ENTRYPOINT,
        "module": MODULE_NAME,
    }


def _dlc_layer():
    scripts = str(Path(__file__).resolve().parent)
    if scripts not in sys.path:
        sys.path.insert(0, scripts)
    import solve_lite_dlc

    return solve_lite_dlc


def _specialist_asset_root(runtime_root: Path) -> Path | None:
    """Where the kernel should look for optional specialist/DLC assets."""
    try:
        return _dlc_layer().effective_asset_root(runtime_root)
    except Exception:  # noqa: BLE001
        return None


def _core_capabilities(module: Any, asset_root: Path | None) -> dict[str, Any]:
    if asset_root is not None:
        try:
            return module.capabilities(asset_root)
        except TypeError:
            pass
    return module.capabilities()


def capabilities(asset_root: str | Path | None = None) -> dict[str, Any]:
    """Capability registry: no model load, no torch, no network, never raises."""
    base: dict[str, Any] = {
        "abi_schema": ABI_SCHEMA,
        "entrypoint": ENTRYPOINT,
        "build_line": BUILD_LINE,
        "runtime_assets_required": False,
        "legacy_full_precision_required": False,
        "offline": True,
        "network_used": False,
    }
    loaded = load_core(asset_root)
    if loaded.get("status") != "AVAILABLE":
        base.update(
            {
                "status": "BLOCKED",
                "error": loaded.get("error", ERROR_CORE),
                "reason": loaded.get("reason"),
                "detail": loaded.get("detail"),
            }
        )
        return base
    root = Path(loaded["runtime_root"])
    specialist_root = _specialist_asset_root(root)
    try:
        report = _core_capabilities(loaded["module"], specialist_root)
    except Exception as exc:  # noqa: BLE001
        report = {"error": ERROR_CORE, "reason": f"CAPABILITY_EXCEPTION:{type(exc).__name__}", "detail": str(exc)}
    base.update(
        {
            "status": "PASS",
            "runtime_root": str(root),
            "runtime_root_origin": loaded.get("runtime_root_origin"),
            "specialist_asset_root": str(specialist_root) if specialist_root else None,
            "core": report,
        }
    )
    try:
        base["dlc"] = _dlc_layer().capability_view(root)
    except Exception as exc:  # noqa: BLE001
        base["dlc"] = {"status": "UNKNOWN", "reason": f"DLC_LAYER_EXCEPTION:{type(exc).__name__}"}
    return base


def healthcheck(asset_root: str | Path | None = None) -> dict[str, Any]:
    """Startup health.  PASS means: the bundled LITE core is verified and the
    native decision path is executable.  No DLC and no model pack is required."""
    loaded = load_core(asset_root)
    base: dict[str, Any] = {
        "entrypoint": ENTRYPOINT,
        "core_entrypoint": CORE_ENTRYPOINT,
        "build_line": BUILD_LINE,
        "abi_schema": ABI_SCHEMA,
        "runtime_asset_configured": bool(asset_root),
        "asset_root_required": False,
        "legacy_core_asset_root_required": False,
        "full_precision_pack_required": False,
        "specialist_pack_required_at_startup": False,
        "torch_imported": False,
        "offline": True,
        "network_used": False,
        "telemetry": False,
    }
    if loaded.get("status") != "AVAILABLE":
        base.update(
            {
                "status": "BLOCKED",
                "error": loaded.get("error", ERROR_CORE),
                "reason": loaded.get("reason"),
                "detail": loaded.get("detail"),
            }
        )
        return base
    root = Path(loaded["runtime_root"])
    native = loaded["native_core"]
    base.update(
        {
            "status": "PASS",
            "runtime_root": str(root),
            "runtime_root_origin": loaded.get("runtime_root_origin"),
            "runtime_schema": (loaded["manifest"].get("runtime_schema") or "solve-lite.lite-runtime.v1"),
            "native_capabilities": list(loaded["manifest"].get("native_capabilities") or ["MARKOV"]),
            "native_core_status": "AVAILABLE",
            "native_core_reason": native.get("reason"),
            "native_modules_verified": native.get("modules_verified", len(native.get("modules", []))),
            "rebuilt_modules": native.get("rebuilt_modules", []),
        }
    )
    try:
        core_health = loaded["module"].healthcheck()
        base["core_healthcheck_status"] = core_health.get("status")
    except Exception as exc:  # noqa: BLE001
        base["core_healthcheck_status"] = "FAIL"
        base["core_healthcheck_reason"] = f"CORE_HEALTHCHECK_EXCEPTION:{type(exc).__name__}"
    try:
        base["dlc"] = _dlc_layer().capability_view(root)
    except Exception as exc:  # noqa: BLE001
        base["dlc"] = {"status": "UNKNOWN", "reason": f"DLC_LAYER_EXCEPTION:{type(exc).__name__}"}
    return base


def available_routes(asset_root: str | Path | None = None) -> dict[str, Any]:
    """Which decision routes this install can serve right now."""
    loaded = load_core(asset_root)
    if loaded.get("status") != "AVAILABLE":
        return {"status": "BLOCKED", "error": loaded.get("error", ERROR_CORE), "routes": []}
    try:
        report = loaded["module"].capabilities()
    except Exception:  # noqa: BLE001
        report = {}
    specialist = report.get("specialist") or {}
    root = Path(loaded["runtime_root"])
    try:
        dlc_view = _dlc_layer().capability_view(root)
    except Exception as exc:  # noqa: BLE001
        dlc_view = {"status": "UNKNOWN", "reason": f"DLC_LAYER_EXCEPTION:{type(exc).__name__}"}
    out = {
        "dlc": {
            "status": dlc_view.get("status"),
            "installed_routes": dlc_view.get("installed_routes") or [],
            "not_installed_routes": dlc_view.get("not_installed_routes") or [],
            "not_public_routes": dlc_view.get("not_public_routes") or [],
            "installed_units": [
                item.get("unit_id") for item in (dlc_view.get("units") or []) if item.get("status") == "DLC_INSTALLED"
            ],
            "installable_units": dlc_view.get("installable_units") or [],
            "activation": dlc_view.get("activation") or {},
        },
        "status": "PASS",
        "native_routes": list(report.get("native_capabilities") or ["markov"]),
        "installed_routes": dlc_view.get("installed_routes") or [],
        "not_installed_routes": dlc_view.get("not_installed_routes") or [],
        "specialist_execution_status": dlc_view.get("specialist_execution_status"),
        "specialist_execution_reason": dlc_view.get("specialist_execution_reason"),
        "activation_state": dlc_view.get("activation_state"),
        "activation_env": dlc_view.get("activation_env"),
        "installed_means_called": dlc_view.get("installed_means_called"),
        "resident_model_limit": dlc_view.get("resident_model_limit"),
        "preloaded": dlc_view.get("preloaded"),
        "native_status": (report.get("native") or {}).get("status"),
        "specialist_routes": list(report.get("specialist_capabilities") or []),
        "specialist_status": specialist.get("status"),
        "specialist_reason": specialist.get("reason"),
    }
    try:
        out["dlc"] = _dlc_layer().route_view(Path(loaded["runtime_root"]))
    except Exception as exc:  # noqa: BLE001
        out["dlc"] = {"status": "UNKNOWN", "reason": f"DLC_LAYER_EXCEPTION:{type(exc).__name__}"}
    return out


def _backend_opt_in() -> bool:
    import os

    return str(os.environ.get(BACKEND_ENV, "")).strip().lower() in {"1", "true", "yes", "on"}


def _required_route(case: Mapping[str, Any]) -> str | None:
    """Mirror the frozen kernel's admitted schema router without doing inference."""
    family = str(case.get("family") or "").strip().lower()
    family_routes = {
        "markov": "markov",
        "markov_attribution": "markov",
        "natural_language_inference": "nli",
        "nli": "nli",
        "topic": "topic",
        "knowledge_topic_routing": "topic",
        "review": "review",
        "advanced_sentiment_review_polarity": "review",
        "amazon_review_polarity": "review",
        "financial": "financial",
        "financial_sentiment": "financial",
    }
    if family in family_routes:
        return family_routes[family]
    state = case.get("state") or {}
    questions = case.get("questions") or {}
    if state.get("schema") == "MDP_ATTRIBUTION_V1":
        return "markov"
    items = state.get("items")
    if not isinstance(items, list) or not items or not isinstance(items[0], Mapping) or not questions:
        return None
    fields = set(items[0])
    first = questions[sorted(questions)[0]]
    criteria = first.get("criteria")
    if {"premise", "hypothesis"} <= fields:
        return "nli"
    if {"title", "content"} <= fields and isinstance(criteria, dict) and len(criteria) == 14:
        return "topic"
    if first.get("type") == "noul" and isinstance(criteria, dict):
        descriptions = " ".join(str(value).lower() for value in criteria.values())
        if "review" in descriptions and "positive" in descriptions:
            return "review"
    if first.get("type") == "score" and criteria == ["Bearish", "Neutral", "Bullish"]:
        return "financial"
    return None


def _specialist_hint(runtime_root: Path) -> dict[str, Any]:
    """Public hint: which DLC components exist (read-only)."""
    try:
        return _dlc_layer().unavailable_hint(runtime_root)
    except Exception:  # noqa: BLE001
        return {}


def _specialist_runtime_layer():
    import specialist_runtime

    return specialist_runtime


def _inside_specialist_env(runtime_root: Path) -> bool:
    try:
        expected = _specialist_runtime_layer().runtime_paths(runtime_root)["venv"]
        return Path(sys.prefix).resolve() == Path(expected).resolve()
    except Exception:  # noqa: BLE001
        return False


def _delegate_specialist(
    runtime_root: Path,
    workspace: str | Path,
    case: dict[str, Any],
    session: Mapping[str, Any] | None,
    *,
    namespace: str,
    invocation_id: str | None,
) -> dict[str, Any]:
    """Run one specialist decision in the pinned repo-local environment."""
    try:
        specialist = _specialist_runtime_layer()
        ready = specialist.healthcheck(runtime_root, deep=False)
    except Exception as exc:  # noqa: BLE001 - public boundary is structured
        return {
            "status": ERROR_SPECIALIST,
            "error": ERROR_SPECIALIST,
            "reason": f"SPECIALIST_RUNTIME_PROBE_FAILED:{type(exc).__name__}",
            "detail": str(exc)[:300],
            "answers": {},
            "fallback_computation": False,
            "core_status": "AVAILABLE",
        }
    if ready.get("status") != "PASS":
        return {
            "status": ERROR_SPECIALIST,
            "error": ERROR_SPECIALIST,
            "reason": "SPECIALIST_RUNTIME_NOT_READY",
            "detail": ready,
            "answers": {},
            "fallback_computation": False,
            "core_status": "AVAILABLE",
            "dlc": _specialist_hint(runtime_root),
        }
    paths = specialist.runtime_paths(runtime_root)
    request = {
        "workspace": str(workspace),
        "case": case,
        "session": dict(session or {}),
        "asset_root": str(runtime_root),
        "namespace": namespace,
        "invocation_id": invocation_id,
    }
    environment = dict(os.environ)
    environment.update(specialist.worker_environment(runtime_root))
    try:
        process = subprocess.run(
            [str(paths["python"]), "-I", str(Path(__file__).with_name("specialist_worker.py"))],
            input=json.dumps(request, ensure_ascii=False),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=environment,
            check=False,
            timeout=300,
        )
        result = json.loads((process.stdout or "").strip().splitlines()[-1])
    except (OSError, subprocess.SubprocessError, ValueError, IndexError) as exc:
        return {
            "status": ERROR_SPECIALIST,
            "error": ERROR_SPECIALIST,
            "reason": f"SPECIALIST_WORKER_FAILED:{type(exc).__name__}",
            "detail": str(exc)[:300],
            "answers": {},
            "fallback_computation": False,
            "core_status": "AVAILABLE",
        }
    if not isinstance(result, dict):
        return {
            "status": ERROR_SPECIALIST,
            "error": ERROR_SPECIALIST,
            "reason": "SPECIALIST_WORKER_INVALID_RESPONSE",
            "answers": {},
            "fallback_computation": False,
            "core_status": "AVAILABLE",
        }
    result.setdefault("specialist_process", {})
    result["specialist_process"].update(
        {"isolated_venv": True, "returncode": process.returncode, "python": str(paths["python"])}
    )
    return result


def _activate_now(engine: Path, asset_root: Path, runtime_root: Path) -> dict[str, Any]:
    try:
        if str(engine) not in sys.path:
            sys.path.insert(0, str(engine))
        from int4_dlc.activate import activate  # type: ignore[import-not-found]
        native = runtime_root / "solve_lite" / "lite_runtime" / "_kernel_native"
        activation = activate(asset_root=asset_root, kernel_native=native)
    except Exception as exc:  # noqa: BLE001 - a broken backend must not break the host
        return {"status": "ACTIVATION_FAILED", "activated": False, "engine": str(engine),
                "reason": f"{type(exc).__name__}"[:120], "asset_root": str(asset_root)}
    manager = getattr(activation, "manager", None)
    _BACKEND_STATE["manager"] = manager
    return {
        "status": "ACTIVATED",
        "activated": True,
        "engine": str(engine),
        "asset_root": str(asset_root),
        "patched": bool(getattr(activation, "patched", False)),
        "max_resident_dlc": 1,
        "preload_at_startup": False,
        "resident_dlc_id": getattr(manager, "_current_dlc", None),
    }


def activate_specialist_backend(
    runtime_root: Path,
    asset_root: Path | None = None,
    required_route: str | None = None,
) -> dict[str, Any]:
    """Activate lazily for one admitted specialist route; never preload a model."""
    explicit = _backend_opt_in()
    if required_route is None and not explicit:
        active = bool((_BACKEND_STATE.get("value") or {}).get("activated"))
        return {"status": "NOT_REQUIRED", "activated": active, "engine": None, "asset_root": None}
    if required_route is not None:
        try:
            installed = set(_dlc_layer().route_view(runtime_root).get("installed_routes") or [])
        except Exception as exc:  # noqa: BLE001
            return {"status": "DLC_STATE_UNAVAILABLE", "activated": False,
                    "reason": type(exc).__name__, "required_route": required_route}
        if required_route not in installed:
            return {"status": "ROUTE_NOT_INSTALLED", "activated": False,
                    "required_route": required_route, "installed_routes": sorted(installed)}
    if asset_root is None:
        asset_root = _specialist_asset_root(runtime_root)
    engine = runtime_root / DLC_RUNTIME_DIRNAME
    if not (engine / "int4_dlc").is_dir():
        return {"status": "BACKEND_MISSING", "activated": False, "engine": str(engine), "asset_root": None}
    if asset_root is None or not asset_root.is_dir():
        return {"status": "NO_ASSET_ROOT", "activated": False, "engine": str(engine), "asset_root": None}
    key = f"{engine}:{asset_root}"
    if _BACKEND_STATE.get("key") == key:
        cached = dict(_BACKEND_STATE["value"])
        cached["activation_mode"] = "AUTO_LAZY_CAPABILITY" if required_route is not None else "EXPLICIT_ENV"
        cached["required_route"] = required_route
        return cached
    value = _activate_now(engine, asset_root, runtime_root)
    value["activation_mode"] = "AUTO_LAZY_CAPABILITY" if required_route is not None else "EXPLICIT_ENV"
    value["required_route"] = required_route
    _BACKEND_STATE.update({"key": key, "value": value})
    return value


def route_prompt(
    workspace: str | Path,
    case: dict[str, Any],
    session: Mapping[str, Any] | None = None,
    *,
    asset_root: str | Path | None = None,
    namespace: str = "production",
    invocation_id: str | None = None,
) -> dict[str, Any]:
    """Route one case through the LITE core.  Never raises, never downloads."""
    loaded = load_core(asset_root)
    if loaded.get("status") != "AVAILABLE":
        return {
            "status": "BLOCKED",
            "error": loaded.get("error", ERROR_CORE),
            "reason": loaded.get("reason"),
            "detail": loaded.get("detail"),
            "runtime_root": loaded.get("runtime_root"),
            "entrypoint": ENTRYPOINT,
            "case_id": (case or {}).get("case_id"),
            "invocation_id": invocation_id,
            "answers": {},
            "fallback_computation": False,
            "network_model_calls": 0,
            "credential_reads": 0,
            "jev_api_calls": 0,
        }
    root = Path(loaded["runtime_root"])
    asset_root = _specialist_asset_root(root)
    required_route = _required_route(case)
    specialist_route = required_route if required_route in {"financial", "topic", "review", "nli"} else None
    if (
        specialist_route is not None
        and os.environ.get(SPECIALIST_WORKER_ENV) != "1"
        and not _inside_specialist_env(root)
    ):
        return _delegate_specialist(
            root,
            workspace,
            case,
            session,
            namespace=namespace,
            invocation_id=invocation_id,
        )
    env_previous: dict[str, str | None] = {}
    if specialist_route is not None:
        for name in (BACKEND_ENV, ACTIVATION_ROOT_ENV):
            env_previous[name] = os.environ.get(name)
        os.environ[BACKEND_ENV] = "1"
        if asset_root is not None:
            os.environ[ACTIVATION_ROOT_ENV] = str(asset_root)
    backend = activate_specialist_backend(root, asset_root, specialist_route)
    try:
        result = loaded["module"].route_session(
            workspace,
            case,
            session,
            asset_root=asset_root or root,
            namespace=namespace,
            invocation_id=invocation_id,
        )
    except Exception as exc:  # noqa: BLE001 - a core fault must not become a traceback
        return {
            "status": "BLOCKED",
            "error": ERROR_CORE,
            "reason": f"CORE_EXCEPTION:{type(exc).__name__}",
            "detail": str(exc),
            "runtime_root": str(root),
            "entrypoint": ENTRYPOINT,
            "case_id": (case or {}).get("case_id"),
            "invocation_id": invocation_id,
            "answers": {},
            "fallback_computation": False,
            "network_model_calls": 0,
            "credential_reads": 0,
            "jev_api_calls": 0,
        }
    finally:
        if env_previous:
            for name, previous in env_previous.items():
                if previous is None:
                    os.environ.pop(name, None)
                else:
                    os.environ[name] = previous
    result.setdefault("entrypoint", ENTRYPOINT)
    result.setdefault("runtime_root", str(root))
    result.setdefault("fallback_computation", False)
    result.setdefault("specialist_backend", backend)
    if isinstance(result, dict) and result.get("status") == ERROR_SPECIALIST:
        # A missing/damaged specialist pack is a capability failure, not a core
        # failure. Normal public installation is responsible for installing all
        # three public packs.
        result.setdefault("error", ERROR_SPECIALIST)
        result.setdefault("core_status", "AVAILABLE")
        hint = _specialist_hint(root)
        if hint:
            result["dlc"] = hint
    return result


def _cli(argv: list[str] | None = None) -> int:
    """Dependency-free CLI for host integrations that do not use the hook."""
    import argparse
    import json as _json

    parser = argparse.ArgumentParser(prog=ENTRYPOINT.split(":")[0], description="Solve Lite public ABI (LITE-first)")
    parser.add_argument("command", choices=("healthcheck", "capabilities", "routes", "route"))
    parser.add_argument("--case")
    parser.add_argument("--workspace", default=None)
    parser.add_argument("--namespace", default="production")
    parser.add_argument("--asset-root", default=None)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    if args.command == "healthcheck":
        payload: Any = healthcheck(args.asset_root)
    elif args.command == "capabilities":
        payload = capabilities(args.asset_root)
    elif args.command == "routes":
        payload = available_routes(args.asset_root)
    else:
        if not args.case:
            parser.error("route requires --case FILE")
        case = _json.loads(Path(args.case).read_text(encoding="utf-8"))
        if isinstance(case, dict) and "cases" in case:
            case = case["cases"][0]
        workspace = Path(args.workspace or ".").expanduser()
        payload = route_prompt(
            workspace,
            case,
            {"metadata": {"locale": "en-US"}},
            asset_root=args.asset_root,
            namespace=args.namespace,
            invocation_id=f"cli:{workspace.name}",
        )
    print(_json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2 if args.json else None))
    return 0 if str(payload.get("status", "")).startswith(("PASS", "SPECIALIST")) else 1


if __name__ == "__main__":
    raise SystemExit(_cli())


__all__ = [
    "ABI_SCHEMA",
    "ENTRYPOINT",
    "available_routes",
    "bundled_runtime_root",
    "capabilities",
    "healthcheck",
    "load_core",
    "load_manifest",
    "locate_core",
    "locate_runtime_root",
    "manifest_candidates",
    "route_prompt",
    "skill_root",
]
