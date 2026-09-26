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


def load_core(asset_root: str | os.PathLike[str] | None = None) -> ModuleType | dict[str, Any]:
    """Verify and load only the manifest-declared stable public Core entrypoint."""
    manifest = _manifest()
    root = locate_core(asset_root)
    if manifest is None:
        return _blocked("ASSET_MANIFEST_MISSING")
    if root is None:
        return _blocked("ASSET_ROOT_MISSING")
    failure = _verify(root, manifest)
    if failure:
        return failure
    public_abi = manifest.get("public_abi")
    if not isinstance(public_abi, Mapping) or public_abi.get("status") != "AVAILABLE":
        return _blocked("PUBLIC_CORE_ENTRYPOINT_MISSING")
    module_name = str(public_abi.get("module") or "")
    artifact = str(public_abi.get("artifact") or "")
    declared = {str(item.get("relative_path") or item.get("name") or "") for item in manifest["artifacts"]}
    if not _MODULE_NAME.fullmatch(module_name) or artifact not in declared:
        return _blocked("PUBLIC_CORE_ENTRYPOINT_INVALID")
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    module = importlib.import_module(module_name)
    if not callable(getattr(module, "route_prompt", None)) or not callable(getattr(module, "healthcheck", None)):
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
    core = load_core(asset_root)
    if isinstance(core, dict):
        return core
    result = core.route_prompt(
        workspace,
        case,
        session,
        namespace=namespace,
        invocation_id=invocation_id,
    )
    return result if isinstance(result, dict) else _blocked("PUBLIC_CORE_RESPONSE_INVALID")


__all__ = ["healthcheck", "load_core", "locate_core", "route_prompt"]
