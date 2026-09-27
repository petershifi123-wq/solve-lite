"""Canonical one-copy runtime layout for Solve Lite host adapters.

The public repository and every host adapter stay small.  The native runtime
and one shared CoreML asset live once per user in a versioned directory.
Hosts receive only a pointer receipt; no environment variable is required.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
from pathlib import Path
from typing import Any

RUNTIME_VERSION = "v0.1.10"
POINTER_FILENAME = ".solve-lite-runtime.json"
RECEIPT_FILENAME = "shared-runtime-receipt.json"
ENV_SHARED_RUNTIME_ROOT = "SOLVE_LITE_SHARED_RUNTIME_ROOT"
SCHEMA = "solve-lite.shared-runtime-pointer.v1"
HEAVY_RUNTIME_DIRS = frozenset({"shared-encoder-runtime"})


def default_runtime_root() -> Path:
    override = os.environ.get(ENV_SHARED_RUNTIME_ROOT)
    if override:
        return Path(override).expanduser().resolve()
    return (
        Path.home()
        / "Library"
        / "Application Support"
        / "Solve Lite"
        / "runtime"
        / RUNTIME_VERSION
    ).resolve()


def pointer_path(adapter_root: str | Path) -> Path:
    return Path(adapter_root).expanduser().resolve() / POINTER_FILENAME


def load_pointer(adapter_root: str | Path) -> dict[str, Any]:
    path = pointer_path(adapter_root)
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"status": "MISSING", "pointer": str(path)}
    root = document.get("runtime_root")
    if document.get("schema") != SCHEMA or not isinstance(root, str) or not root.strip():
        return {"status": "INVALID", "pointer": str(path)}
    return {
        **document,
        "status": "PASS",
        "pointer": str(path),
        "runtime_root": str(Path(root).expanduser().resolve()),
    }


def write_pointer(adapter_root: str | Path, runtime_root: str | Path) -> Path:
    root = Path(runtime_root).expanduser().resolve()
    path = pointer_path(adapter_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    document = {
        "schema": SCHEMA,
        "runtime_version": RUNTIME_VERSION,
        "runtime_root": str(root),
        "shared_runtime_single_copy": True,
    }
    fd, temporary = tempfile.mkstemp(prefix=path.name + ".", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(document, handle, indent=2, sort_keys=True)
            handle.write("\n")
        os.chmod(temporary, 0o600)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    return path


def resolve(adapter_root: str | Path | None = None) -> Path:
    if os.environ.get(ENV_SHARED_RUNTIME_ROOT):
        return default_runtime_root()
    if adapter_root is not None:
        pointer = load_pointer(adapter_root)
        if pointer.get("status") == "PASS":
            return Path(str(pointer["runtime_root"]))
    return default_runtime_root()


def _base_rows(root: Path) -> list[str]:
    rows: list[str] = []
    if not root.is_dir():
        return rows
    for path in sorted(root.rglob("*"), key=lambda item: item.as_posix()):
        relative = path.relative_to(root)
        if relative.parts and relative.parts[0] in HEAVY_RUNTIME_DIRS:
            continue
        if path.name == RECEIPT_FILENAME or "__pycache__" in relative.parts or path.suffix in {".pyc", ".pyo"}:
            continue
        if path.is_symlink():
            payload = os.readlink(path).encode("utf-8", errors="surrogateescape")
            rows.append(f"{relative.as_posix()}\0symlink\0{hashlib.sha256(payload).hexdigest()}")
        elif path.is_file():
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            rows.append(f"{relative.as_posix()}\0file\0{path.stat().st_size}\0{digest}")
    return rows


def base_tree_sha256(root: str | Path) -> str:
    rows = _base_rows(Path(root).expanduser().resolve())
    payload = ("\n".join(rows) + ("\n" if rows else "")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def prepare_base(source_runtime: str | Path, runtime_root: str | Path | None = None) -> dict[str, Any]:
    """Atomically seed a new versioned shared runtime; fail closed on conflict."""
    source = Path(source_runtime).expanduser().resolve()
    destination = Path(runtime_root or default_runtime_root()).expanduser().resolve()
    expected = base_tree_sha256(source)
    if not source.is_dir() or not (source / "solve_lite").is_dir():
        return {"status": "FAIL", "reason": "SOURCE_RUNTIME_MISSING", "source": str(source)}
    if destination.exists():
        observed = base_tree_sha256(destination)
        if observed != expected:
            return {
                "status": "FAIL",
                "reason": "SHARED_RUNTIME_VERSION_CONFLICT",
                "runtime_root": str(destination),
                "expected_base_tree_sha256": expected,
                "observed_base_tree_sha256": observed,
            }
        return {
            "status": "PASS",
            "created": False,
            "runtime_root": str(destination),
            "base_tree_sha256": observed,
        }
    destination.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=RUNTIME_VERSION + ".", dir=str(destination.parent)))
    try:
        for item in source.iterdir():
            if item.name in HEAVY_RUNTIME_DIRS or item.name == RECEIPT_FILENAME:
                continue
            target = staging / item.name
            if item.is_dir():
                shutil.copytree(item, target, symlinks=True)
            else:
                shutil.copy2(item, target, follow_symlinks=False)
        observed = base_tree_sha256(staging)
        if observed != expected:
            return {
                "status": "FAIL",
                "reason": "SHARED_RUNTIME_STAGE_HASH_MISMATCH",
                "expected_base_tree_sha256": expected,
                "observed_base_tree_sha256": observed,
            }
        receipt = {
            "schema": "solve-lite.shared-runtime-receipt.v1",
            "runtime_version": RUNTIME_VERSION,
            "runtime_root": str(destination),
            "base_tree_sha256": observed,
            "shared_runtime_single_copy": True,
        }
        (staging / RECEIPT_FILENAME).write_text(
            json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        os.replace(staging, destination)
    finally:
        if staging.exists():
            shutil.rmtree(staging, ignore_errors=True)
    return {
        "status": "PASS",
        "created": True,
        "runtime_root": str(destination),
        "base_tree_sha256": expected,
    }


def adapter_heavy_paths(adapter_root: str | Path) -> list[str]:
    root = Path(adapter_root).expanduser().resolve()
    matches: list[str] = []
    for runtime in (root / "runtime", root / "skills" / "solve-lite" / "runtime"):
        for name in HEAVY_RUNTIME_DIRS:
            path = runtime / name
            if path.exists() or path.is_symlink():
                matches.append(str(path))
    return sorted(matches)
