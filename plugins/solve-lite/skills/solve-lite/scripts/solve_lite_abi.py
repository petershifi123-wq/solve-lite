"""Minimal public loader for the separately distributed local closed Core."""

from __future__ import annotations

import hashlib
import importlib
import json
import os
import re
import sys
from pathlib import Path
from types import ModuleType
from typing import Any, Mapping


ERROR = "CORE_ASSET_UNAVAILABLE"
ENTRYPOINT = "solve_lite_abi:route_prompt"
CORE_ENTRYPOINT = "route_session"
CORE_HEALTHCHECK = "healthcheck"
_MODULE_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_.]*$")


def _blocked(reason: str) -> dict[str, Any]:
    return {
        "status": "BLOCKED",
        "error": ERROR,
        "reason": reason,
        "entrypoint": ENTRYPOINT,
        "offline": True,
        "telemetry": False,
    }


def _manifest_path() -> Path | None:
    for parent in Path(__file__).resolve().parents:
        candidate = parent / "CORE_ASSET_MANIFEST.json"
        if candidate.is_file():
            return candidate
    return None


def _manifest() -> Mapping[str, Any] | None:
    path = _manifest_path()
    if path is None:
        return None
    value = json.loads(path.read_text(encoding="utf-8"))
    return value if isinstance(value, Mapping) else None


def locate_core(asset_root: str | os.PathLike[str] | None = None) -> Path | None:
    """Locate an explicitly configured Core root; never download or infer one."""
    value = asset_root or os.environ.get("SOLVE_LITE_CORE_ASSET_ROOT")
    if not value:
        return None
    root = Path(value).expanduser().resolve()
    return root if root.is_dir() else None


def _verify(root: Path, manifest: Mapping[str, Any]) -> dict[str, Any] | None:
    if sys.platform != "darwin" or sys.implementation.cache_tag != "cpython-39":
        return _blocked("ABI_MISMATCH")
    artifacts = manifest.get("artifacts")
    if not isinstance(artifacts, list) or not artifacts:
        return _blocked("ASSET_MANIFEST_INVALID")
    for artifact in artifacts:
        if not isinstance(artifact, Mapping):
            return _blocked("ASSET_MANIFEST_INVALID")
        relative = str(artifact.get("relative_path") or artifact.get("name") or "")
        candidate = (root / relative).resolve()
        try:
            candidate.relative_to(root)
        except ValueError:
            return _blocked("ASSET_PATH_INVALID")
        if not relative or Path(relative).is_absolute() or ".." in Path(relative).parts:
            return _blocked("ASSET_PATH_INVALID")
        if not candidate.is_file():
            return _blocked("ASSET_FILE_MISSING")
        data = candidate.read_bytes()
        if len(data) != artifact.get("bytes") or hashlib.sha256(data).hexdigest() != artifact.get("sha256"):
            return _blocked("ASSET_HASH_MISMATCH")
    return None


def _verify_runtime_assets(root: Path, manifest: Mapping[str, Any]) -> dict[str, Any] | None:
    """Require the sealed external model pack without downloading or substituting it."""
    root = root.resolve()
    expected = manifest.get("runtime_model_assets")
    if not isinstance(expected, Mapping) or expected.get("status") != "EXTERNAL_REQUIRED":
        return _blocked("RUNTIME_MODEL_ASSET_CONTRACT_INVALID")
    if expected.get("distribution") != "BYO_OR_OWNER_SUPPLIED":
        return _blocked("RUNTIME_MODEL_ASSET_CONTRACT_INVALID")
    if expected.get("auto_download") is not False or expected.get("fallback_computation") is not False:
        return _blocked("RUNTIME_MODEL_ASSET_CONTRACT_INVALID")
    manifest_name = str(expected.get("owner_manifest") or "")
    if not manifest_name or Path(manifest_name).is_absolute() or ".." in Path(manifest_name).parts:
        return _blocked("RUNTIME_MODEL_ASSET_CONTRACT_INVALID")
    owner_manifest_path = (root / manifest_name).resolve()
    try:
        owner_manifest_path.relative_to(root)
    except ValueError:
        return _blocked("RUNTIME_MODEL_ASSET_CONTRACT_INVALID")
    if not owner_manifest_path.is_file():
        return _blocked("RUNTIME_MODEL_ASSET_MANIFEST_MISSING")
    try:
        owner = json.loads(owner_manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return _blocked("RUNTIME_MODEL_ASSET_MANIFEST_INVALID")
    if not isinstance(owner, Mapping):
        return _blocked("RUNTIME_MODEL_ASSET_MANIFEST_INVALID")
    scalar_pairs = (
        ("schema", "owner_manifest_schema"),
        ("total_files", "total_files"),
        ("total_bytes", "total_bytes"),
        ("tree_sha256", "tree_sha256"),
    )
    if any(owner.get(actual) != expected.get(reference) for actual, reference in scalar_pairs):
        return _blocked("RUNTIME_MODEL_ASSET_HASH_MISMATCH")
    required = expected.get("required_directories")
    owner_required = owner.get("required_directories")
    if not isinstance(required, list) or not required or owner_required != required:
        return _blocked("RUNTIME_MODEL_ASSET_HASH_MISMATCH")
    for item in required:
        if not isinstance(item, Mapping):
            return _blocked("RUNTIME_MODEL_ASSET_CONTRACT_INVALID")
        relative = str(item.get("relative_path") or "")
        candidate = (root / relative).resolve()
        if not relative or Path(relative).is_absolute() or ".." in Path(relative).parts:
            return _blocked("RUNTIME_MODEL_ASSET_CONTRACT_INVALID")
        try:
            candidate.relative_to(root)
        except ValueError:
            return _blocked("RUNTIME_MODEL_ASSET_CONTRACT_INVALID")
        if not candidate.is_dir():
            return _blocked("RUNTIME_MODEL_ASSET_MISSING")
    return None


def load_core(asset_root: str | os.PathLike[str] | None = None) -> ModuleType | dict[str, Any]:
    """Verify and load only the manifest-declared Architecture A Core ABI."""
    manifest = _manifest()
    root = locate_core(asset_root)
    if manifest is None:
        return _blocked("ASSET_MANIFEST_MISSING")
    if root is None:
        return _blocked("ASSET_ROOT_MISSING")
    failure = _verify(root, manifest)
    if failure:
        return failure
    failure = _verify_runtime_assets(root, manifest)
    if failure:
        return failure
    public_abi = manifest.get("public_abi")
    if not isinstance(public_abi, Mapping) or public_abi.get("status") != "AVAILABLE":
        return _blocked("PUBLIC_CORE_ENTRYPOINT_MISSING")
    module_name = str(public_abi.get("module") or "")
    public_entry = str(public_abi.get("public_entry") or "")
    core_entry = str(public_abi.get("core_native_entry") or "")
    health_entry = str(public_abi.get("healthcheck") or "")
    if (
        not _MODULE_NAME.fullmatch(module_name)
        or public_entry != "route_prompt"
        or core_entry != CORE_ENTRYPOINT
        or health_entry != CORE_HEALTHCHECK
    ):
        return _blocked("PUBLIC_CORE_ENTRYPOINT_INVALID")
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    try:
        module = importlib.import_module(module_name)
    except (ImportError, OSError):
        return _blocked("PUBLIC_CORE_IMPORT_FAILED")
    module_file = getattr(module, "__file__", None)
    if not module_file:
        return _blocked("PUBLIC_CORE_MODULE_OUTSIDE_ASSET")
    try:
        Path(module_file).resolve().relative_to(root)
    except ValueError:
        return _blocked("PUBLIC_CORE_MODULE_OUTSIDE_ASSET")
    if not callable(getattr(module, CORE_ENTRYPOINT, None)) or not callable(
        getattr(module, CORE_HEALTHCHECK, None)
    ):
        return _blocked("PUBLIC_CORE_CALLABLE_MISSING")
    return module


def healthcheck(asset_root: str | os.PathLike[str] | None = None) -> dict[str, Any]:
    core = load_core(asset_root)
    if isinstance(core, dict):
        return core
    result = core.healthcheck()
    return result if isinstance(result, dict) else _blocked("PUBLIC_CORE_RESPONSE_INVALID")


def route_prompt(
    workspace: str | os.PathLike[str],
    case: Mapping[str, Any],
    session: Mapping[str, Any] | None,
    *,
    asset_root: str | os.PathLike[str] | None = None,
    namespace: str = "production",
    invocation_id: str | None = None,
) -> dict[str, Any]:
    resolved_root = locate_core(asset_root)
    core = load_core(resolved_root)
    if isinstance(core, dict):
        return core
    result = core.route_session(
        workspace,
        case,
        session,
        asset_root=resolved_root,
        namespace=namespace,
        invocation_id=invocation_id,
    )
    return result if isinstance(result, dict) else _blocked("PUBLIC_CORE_RESPONSE_INVALID")


__all__ = ["healthcheck", "load_core", "locate_core", "route_prompt"]
