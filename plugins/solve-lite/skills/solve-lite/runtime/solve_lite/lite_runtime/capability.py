"""LITE capability registry: native vs specialist (VV ruling A3, PHASE 2B item 5).

The LITE runtime is *capability partitioned*.  Native routes are served by the
bundled native kernel with zero ML dependencies.  Summit / specialist routes need
an externally supplied model pack plus torch + transformers, which the LITE startup
path must never require, never probe by import, and never download.

Semantic discipline (task §三):

  native .so missing | hash mismatch | ABI root missing -> CORE_ASSET_UNAVAILABLE
  model pack missing                                   -> SPECIALIST_CAPABILITY_UNAVAILABLE

A missing model pack must never again masquerade as "the whole Core is missing".
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any

SCHEMA = "solve-lite.lite-capability.v1"
LITE_CORE_MANIFEST_NAME = "LITE_CORE_ASSET_MANIFEST.json"

CORE_ASSET_UNAVAILABLE = "CORE_ASSET_UNAVAILABLE"
SPECIALIST_CAPABILITY_UNAVAILABLE = "SPECIALIST_CAPABILITY_UNAVAILABLE"

NATIVE_CAPABILITY = "native"
SPECIALIST_CAPABILITY = "specialist"

#: routes answerable by the bundled native kernel alone (stdlib only, no ML)
NATIVE_ROUTES: tuple[str, ...] = ("markov",)
#: routes that need the optional specialist model pack
SPECIALIST_ROUTES: tuple[str, ...] = ("financial", "topic", "review", "nli")

#: optional specialist pack contents (same list the Full core hard-required)
SPECIALIST_MODEL_DIRS: tuple[str, ...] = (
    "model-cache/ProsusAI--finbert",
    "model-cache/fabriceyhc--bert-base-uncased-dbpedia_14",
    "model-cache/distilbert--distilbert-base-uncased-finetuned-sst-2-english",
    "model-cache/cross-encoder--nli-deberta-v3-base",
    "model-cache-public-trained/financial_sentiment",
)
SPECIALIST_PYTHON_MODULES: tuple[str, ...] = ("torch", "transformers")

#: which model directories each specialist route needs, so that a partial pack
#: (for example the three public DLC components without the financial pair) can
#: serve the routes it does have instead of failing as a whole
SPECIALIST_ROUTE_DIRS: dict[str, tuple[str, ...]] = {
    "nli": ("model-cache/cross-encoder--nli-deberta-v3-base",),
    "topic": ("model-cache/fabriceyhc--bert-base-uncased-dbpedia_14",),
    "review": ("model-cache/distilbert--distilbert-base-uncased-finetuned-sst-2-english",),
    "financial": (
        "model-cache/ProsusAI--finbert",
        "model-cache-public-trained/financial_sentiment",
    ),
}
#: container names: a plain transformers layout can be used by the kernel itself,
#: an int4 container needs the opt-in DLC backend loaded
NATIVE_CONTAINER_NAMES: tuple[str, ...] = ("model.safetensors", "pytorch_model.bin")
INT4_CONTAINER_NAME = "model.slint4.safetensors"
INT4_BACKEND_ENV = "SOLVE_LITE_INT4_DLC"

AVAILABLE = "AVAILABLE"
UNAVAILABLE = "UNAVAILABLE"


def runtime_dir() -> Path:
    return Path(__file__).resolve().parent


def lite_manifest_path() -> Path:
    return runtime_dir() / LITE_CORE_MANIFEST_NAME


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def lite_manifest() -> dict[str, Any]:
    return json.loads(lite_manifest_path().read_text(encoding="utf-8"))


def native_core_status(manifest: dict[str, Any] | None = None) -> dict[str, Any]:
    """Verify the bundled native core WITHOUT importing it and WITHOUT any ML.

    This is the only startup gate the LITE runtime has.  It never looks at the
    specialist model pack, never imports torch and never touches the network.
    """
    try:
        document = manifest if manifest is not None else lite_manifest()
    except (OSError, ValueError) as error:
        return {
            "capability": NATIVE_CAPABILITY,
            "status": UNAVAILABLE,
            "reason": CORE_ASSET_UNAVAILABLE,
            "detail": f"{LITE_CORE_MANIFEST_NAME} unreadable: {error}",
            "modules": [],
        }
    native = runtime_dir() / "_kernel_native"
    if not native.is_dir():
        return {
            "capability": NATIVE_CAPABILITY,
            "status": UNAVAILABLE,
            "reason": CORE_ASSET_UNAVAILABLE,
            "detail": f"native kernel directory missing: {native}",
            "modules": [],
        }
    modules = []
    for entry in document.get("native_kernel_modules", []):
        target = native / entry["file"]
        if not target.is_file():
            return {
                "capability": NATIVE_CAPABILITY,
                "status": UNAVAILABLE,
                "reason": CORE_ASSET_UNAVAILABLE,
                "detail": f"native module missing: {entry['file']}",
                "modules": modules,
            }
        digest = _sha256_file(target)
        if digest != entry["sha256"]:
            return {
                "capability": NATIVE_CAPABILITY,
                "status": UNAVAILABLE,
                "reason": CORE_ASSET_UNAVAILABLE,
                "detail": f"native module hash mismatch: {entry['file']}",
                "modules": modules,
            }
        modules.append({"file": entry["file"], "module": entry["module"], "sha256": digest,
                        "rebuilt": bool(entry.get("rebuilt"))})
    return {
        "capability": NATIVE_CAPABILITY,
        "status": AVAILABLE,
        "reason": "NATIVE_CORE_VERIFIED",
        "routes": [route for route in NATIVE_ROUTES],
        "modules": modules,
        "model_directories_checked": [],
        "torch_imported": False,
        "network_used": False,
    }


def _module_present(name: str) -> bool:
    """Filesystem-only presence test: never enters the import machinery.

    Deliberately NOT importlib.util.find_spec: the LITE startup/capability path
    must produce zero import-machinery events for torch/transformers so that
    TORCH_IMPORT_ATTEMPTS stays a meaningful, exactly-zero measurement.
    """
    import sys

    for entry in list(sys.path):
        if not entry:
            continue
        base = Path(entry)
        try:
            if (base / f"{name}.py").is_file() or (base / name / "__init__.py").is_file():
                return True
            if any(base.glob(f"{name}-*.dist-info")) or any(base.glob(f"{name}-*.egg-info")):
                return True
        except OSError:
            continue
    return False


def _env_flag(name: str) -> bool:
    return str(os.environ.get(name, "")).strip().lower() in {"1", "true", "yes", "on"}


def specialist_route_status(asset_root: str | Path | None, route: str) -> dict[str, Any]:
    """Per-route specialist availability (VV A3: per-route, not one global gate).

    A route is servable when its own model directories are present, the ML
    dependencies are present, and the model can actually be loaded: either the
    opt-in INT4 backend is active, or the directory ships a plain transformers
    container.  Nothing is imported and nothing is downloaded here.
    """
    root = Path(asset_root).expanduser() if asset_root else None
    directories = SPECIALIST_ROUTE_DIRS.get(route, ())
    if root is None or not root.is_dir():
        missing = list(directories)
    else:
        missing = [item for item in directories if not (root / item).is_dir()]
    missing_modules = [name for name in SPECIALIST_PYTHON_MODULES if not _module_present(name)]
    int4_active = _env_flag(INT4_BACKEND_ENV)
    native_container = False
    if not missing and root is not None:
        for item in directories:
            directory = root / item
            if any((directory / name).is_file() for name in NATIVE_CONTAINER_NAMES):
                native_container = True
    if missing:
        status, reason = UNAVAILABLE, "MODEL_PACK_MISSING"
    elif missing_modules:
        status, reason = UNAVAILABLE, "PYTHON_DEPENDENCIES_MISSING"
    elif int4_active or native_container:
        status = AVAILABLE
        reason = "INT4_BACKEND_ACTIVE" if int4_active else "NATIVE_CONTAINER_PRESENT"
    else:
        status, reason = UNAVAILABLE, "INT4_BACKEND_NOT_ACTIVATED"
    return {
        "route": route,
        "status": status,
        "reason": reason,
        "model_directories": list(directories),
        "missing_model_directories": missing,
        "missing_python_modules": missing_modules,
        "int4_backend_activated": int4_active,
        "native_container_present": native_container,
    }


def specialist_status(asset_root: str | Path | None) -> dict[str, Any]:
    """Describe the OPTIONAL specialist pack.  Never raises, never imports, never downloads."""
    root = Path(asset_root).expanduser() if asset_root else None
    missing_dirs: list[str] = []
    if root is None or not root.is_dir():
        missing_dirs = list(SPECIALIST_MODEL_DIRS)
    else:
        missing_dirs = [item for item in SPECIALIST_MODEL_DIRS if not (root / item).is_dir()]
    missing_modules = [name for name in SPECIALIST_PYTHON_MODULES if not _module_present(name)]
    if missing_dirs and missing_modules:
        reason = "MODEL_PACK_AND_PYTHON_DEPENDENCIES_MISSING"
    elif missing_dirs:
        reason = "MODEL_PACK_MISSING"
    elif missing_modules:
        reason = "PYTHON_DEPENDENCIES_MISSING"
    else:
        reason = "SPECIALIST_PACK_PRESENT"
    available = not missing_dirs and not missing_modules
    route_details = {route: specialist_route_status(root, route) for route in SPECIALIST_ROUTES}
    return {
        "capability": SPECIALIST_CAPABILITY,
        "status": AVAILABLE if available else UNAVAILABLE,
        "reason": reason,
        "routes": list(SPECIALIST_ROUTES),
        "route_details": route_details,
        "routes_available": [
            route for route, detail in route_details.items() if detail["status"] == AVAILABLE
        ],
        "asset_root": str(root) if root else None,
        "missing_model_directories": missing_dirs,
        "missing_python_modules": missing_modules,
        "required_python_modules": list(SPECIALIST_PYTHON_MODULES),
        "requires_network_download": False,
        "fallback_computation": False,
    }


def capability_report(
    native: dict[str, Any] | None = None,
    asset_root: str | Path | None = None,
) -> dict[str, Any]:
    native_status = native if native is not None else native_core_status()
    specialist = specialist_status(asset_root)
    return {
        "schema_version": SCHEMA,
        "build_line": "LITE",
        "native": native_status,
        "specialist": specialist,
        "native_capabilities": list(NATIVE_ROUTES),
        "specialist_capabilities": list(SPECIALIST_ROUTES),
    }


def route_capability(route: str) -> str:
    return SPECIALIST_CAPABILITY if route in SPECIALIST_ROUTES else NATIVE_CAPABILITY


__all__ = [
    "AVAILABLE",
    "CORE_ASSET_UNAVAILABLE",
    "LITE_CORE_MANIFEST_NAME",
    "NATIVE_CAPABILITY",
    "NATIVE_ROUTES",
    "SCHEMA",
    "SPECIALIST_CAPABILITY",
    "SPECIALIST_CAPABILITY_UNAVAILABLE",
    "SPECIALIST_MODEL_DIRS",
    "SPECIALIST_PYTHON_MODULES",
    "SPECIALIST_ROUTE_DIRS",
    "SPECIALIST_ROUTES",
    "INT4_BACKEND_ENV",
    "UNAVAILABLE",
    "capability_report",
    "specialist_route_status",
    "lite_manifest",
    "lite_manifest_path",
    "native_core_status",
    "route_capability",
    "runtime_dir",
    "specialist_status",
]
