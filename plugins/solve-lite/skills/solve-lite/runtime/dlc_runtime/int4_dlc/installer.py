"""DLC installer: explicit, opt-in, licence-guarded. Nothing auto-installs.

Under ``addon_root``:

    installed/<dlc_id>/...    the DLC package (copy or symlink)
    asset-root/<asset_rel>    link to installed/<dlc_id>/<dlc_rel>
    dlc-registry.json         installed record (sizes, checksums, licence class)
    not-installed/<id>.json   marker written on uninstall
"""
from __future__ import annotations

import hashlib
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

from .dlc_table import DLC_UNITS, unit_by_id
from .format import (
    ADDON_ASSET_ROOT_DIRNAME,
    ADDON_DIRNAME,
    ADDON_REGISTRY_FILE,
    LICENSE_ENGINEERING_ONLY,
    MANIFEST_FILE,
)


def default_addon_root(stage: Path) -> Path:
    return Path(stage) / "addons" / ADDON_DIRNAME


def sha256_file(path: Path, block: int = 1 << 20) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(block), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify_package(dlc_root: Path, dlc_id: str) -> dict:
    """Check every file listed in dlc.json against its recorded sha256."""
    package = Path(dlc_root) / dlc_id
    manifest = json.loads((package / MANIFEST_FILE).read_text(encoding="utf-8"))
    bad, checked, total = [], 0, 0
    files = []
    for row in manifest.get("files", []):
        files.append((Path(row.get("rel") or row.get("path")), row))
    for member in manifest.get("members", []):
        base = Path(member.get("dlc_rel", ""))
        for row in member.get("files", []):
            files.append((base / (row.get("rel") or row.get("path")), row))
    for rel_path, row in files:
        target = package / rel_path
        if not target.is_file():
            bad.append({"rel": str(rel_path), "error": "missing"})
            continue
        checked += 1
        total += target.stat().st_size
        if sha256_file(target) != row["sha256"]:
            bad.append({"rel": str(rel_path), "error": "sha256_mismatch"})
    return {"dlc_id": dlc_id, "files_checked": checked, "bytes": total, "bad": bad,
            "ok": not bad}


def _registry_path(addon_root: Path) -> Path:
    return Path(addon_root) / ADDON_REGISTRY_FILE


def read_registry(addon_root: Path) -> dict:
    path = _registry_path(addon_root)
    if not path.is_file():
        return {"schema": "solve-lite.int4-dlc.registry.v1", "installed": {}}
    return json.loads(path.read_text(encoding="utf-8"))


def write_registry(addon_root: Path, registry: dict) -> Path:
    path = _registry_path(addon_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    registry["updated_utc"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    path.write_text(json.dumps(registry, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def install(
    dlc_id: str,
    *,
    dlc_root: Path,
    addon_root: Path,
    mode: str = "symlink",
    allow_engineering_only: bool = False,
    verify: bool = True,
) -> dict:
    """Install ONE DLC.  Refuses licence-unclear units unless explicitly allowed."""
    unit = unit_by_id(dlc_id)
    if unit["license_class"] == LICENSE_ENGINEERING_ONLY and not allow_engineering_only:
        raise PermissionError(
            f"ENGINEERING_ONLY_DLC_REQUIRES_FLAG: {dlc_id} carries licence class "
            f"{LICENSE_ENGINEERING_ONLY}; pass allow_engineering_only=True to install locally"
        )
    if mode not in {"symlink", "copy"}:
        raise ValueError(f"UNKNOWN_INSTALL_MODE: {mode}")
    package = Path(dlc_root) / dlc_id
    if not (package / MANIFEST_FILE).is_file():
        raise FileNotFoundError(f"DLC_PACKAGE_MISSING: {package}")
    check = verify_package(dlc_root, dlc_id) if verify else {"ok": None}
    if verify and not check["ok"]:
        raise RuntimeError(f"DLC_PACKAGE_CHECKSUM_FAILED: {check['bad']}")

    addon_root = Path(addon_root)
    target = addon_root / "installed" / dlc_id
    if target.exists() or target.is_symlink():
        shutil.rmtree(target) if target.is_dir() and not target.is_symlink() else target.unlink()
    target.parent.mkdir(parents=True, exist_ok=True)
    if mode == "symlink":
        target.symlink_to(package, target_is_directory=True)
    else:
        shutil.copytree(package, target)

    asset_root = addon_root / ADDON_ASSET_ROOT_DIRNAME
    links = []
    for member in unit["members"]:
        entry = asset_root / member["asset_rel"]
        if entry.is_symlink() or entry.is_file():
            entry.unlink()
        elif entry.is_dir():
            shutil.rmtree(entry)
        entry.parent.mkdir(parents=True, exist_ok=True)
        source = target / member["dlc_rel"]
        entry.symlink_to(source, target_is_directory=True)
        links.append({"asset_rel": member["asset_rel"], "dlc_rel": member["dlc_rel"]})

    manifest = json.loads((package / MANIFEST_FILE).read_text(encoding="utf-8"))
    registry = read_registry(addon_root)
    registry["installed"][dlc_id] = {
        "dlc_id": dlc_id,
        "family": unit["family"],
        "route": unit["route"],
        "license_class": unit["license_class"],
        "license_spdx": unit["license_spdx"],
        "distributable": bool(unit.get("distributable", True)),
        "precision_label": manifest.get("precision_label"),
        "mode": mode,
        "package": str(package),
        "installed_path": str(target),
        "dlc_bytes": manifest.get("totals", {}).get("dlc_bytes"),
        "members": links,
        "checksums_verified": bool(check.get("ok")),
        "installed_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    write_registry(addon_root, registry)
    return registry["installed"][dlc_id]


def uninstall(dlc_id: str, *, addon_root: Path) -> dict:
    addon_root = Path(addon_root)
    unit = unit_by_id(dlc_id)
    asset_root = addon_root / ADDON_ASSET_ROOT_DIRNAME
    for member in unit["members"]:
        entry = asset_root / member["asset_rel"]
        if entry.is_symlink() or entry.is_file():
            entry.unlink()
        elif entry.is_dir():
            shutil.rmtree(entry)
    target = addon_root / "installed" / dlc_id
    if target.is_symlink() or target.is_file():
        target.unlink()
    elif target.is_dir():
        shutil.rmtree(target)
    marker_dir = addon_root / "not-installed"
    marker_dir.mkdir(parents=True, exist_ok=True)
    marker = {
        "dlc_id": dlc_id,
        "status": "DLC_NOT_INSTALLED",
        "asset_rels": [m["asset_rel"] for m in unit["members"]],
        "uninstalled_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    (marker_dir / f"{dlc_id}.json").write_text(
        json.dumps(marker, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    registry = read_registry(addon_root)
    registry["installed"].pop(dlc_id, None)
    write_registry(addon_root, registry)
    return marker


def export_distributable(dlc_root: Path, dest: Path, dlc_ids: list[str] | None = None) -> dict:
    """Copy ONLY licence-clean (official) DLCs.  Engineering-only units are refused."""
    dlc_root, dest = Path(dlc_root), Path(dest)
    wanted = dlc_ids or [u["dlc_id"] for u in DLC_UNITS if u.get("distributable", True)]
    refused = [d for d in wanted if not unit_by_id(d).get("distributable", True)]
    if refused:
        raise PermissionError(f"REFUSING_DISTRIBUTABLE_EXPORT_OF_ENGINEERING_ONLY_DLC: {refused}")
    copied = []
    for dlc_id in wanted:
        source = dlc_root / dlc_id
        verify_package(dlc_root, dlc_id)
        if (dest / dlc_id).exists():
            shutil.rmtree(dest / dlc_id)
        dest.mkdir(parents=True, exist_ok=True)
        shutil.copytree(source, dest / dlc_id)
        copied.append(dlc_id)
    manifest = {
        "schema": "solve-lite.int4-dlc.export.v1",
        "exported_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "dlc_ids": copied,
        "license_classes": {d: unit_by_id(d)["license_class"] for d in copied},
        "engineering_only_excluded": [
            u["dlc_id"] for u in DLC_UNITS if not u.get("distributable", True)
        ],
    }
    dest.mkdir(parents=True, exist_ok=True)
    (dest / "EXPORT_MANIFEST.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return manifest
