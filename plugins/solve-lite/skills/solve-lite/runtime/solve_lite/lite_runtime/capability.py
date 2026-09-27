"""Current LITE capability registry for the native and shared-CoreML paths.

The bundled native kernel serves Markov locally.  The four specialist routes are
served by one installed shared CoreML asset.  Capability discovery only validates
that current layout; it never probes historical runtimes or downloads anything.
"""

from __future__ import annotations

import hashlib
import json
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
#: routes served by the installed shared CoreML runtime
SPECIALIST_ROUTES: tuple[str, ...] = ("financial", "topic", "review", "nli")
SHARED_ASSET_REQUIRED_PATHS: tuple[str, ...] = (
    "METADATA.json",
    "heads/heads.json",
    "model/shared-encoder.mlpackage/Manifest.json",
    "model/shared-encoder.mlpackage/Data/com.apple.CoreML/model.mlmodel",
    "model/shared-encoder.mlpackage/Data/com.apple.CoreML/weights/weight.bin",
    "tokenizer/config.json",
    "tokenizer/vocab.txt",
)

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
    shared specialist asset and never touches the network.
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
        "network_used": False,
    }


def _shared_asset_status(asset_root: str | Path | None) -> tuple[Path | None, list[str], str]:
    root = Path(asset_root).expanduser() if asset_root else None
    if root is None or not root.is_dir():
        return root, list(SHARED_ASSET_REQUIRED_PATHS), "SHARED_RUNTIME_MISSING"
    missing = [relative for relative in SHARED_ASSET_REQUIRED_PATHS if not (root / relative).is_file()]
    return root, missing, "SHARED_ASSET_INVALID" if missing else "SHARED_COREML_READY"


def specialist_route_status(asset_root: str | Path | None, route: str) -> dict[str, Any]:
    """Describe whether the current shared CoreML asset can serve one route."""
    root, missing, reason = _shared_asset_status(asset_root)
    supported = route in SPECIALIST_ROUTES
    status = AVAILABLE if supported and not missing else UNAVAILABLE
    if not supported:
        reason = "SHARED_ROUTE_UNSUPPORTED"
    return {
        "route": route,
        "status": status,
        "reason": reason,
        "asset_root": str(root) if root else None,
        "missing_shared_asset_paths": missing,
    }


def specialist_status(asset_root: str | Path | None) -> dict[str, Any]:
    """Describe the current shared CoreML asset without loading or downloading it."""
    root, missing, reason = _shared_asset_status(asset_root)
    available = not missing
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
        "missing_shared_asset_paths": missing,
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
    "SPECIALIST_ROUTES",
    "SHARED_ASSET_REQUIRED_PATHS",
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
