"""Capability / registry view over the INT4 DLC addon.

Pure stdlib.  Answers, per route, "what is actually installed right now" without
importing torch and without touching the frozen kernel.
"""
from __future__ import annotations

import json
from pathlib import Path

from .dlc_table import DLC_UNITS
from .format import (
    ADDON_ASSET_ROOT_DIRNAME,
    ADDON_DIRNAME,
    ADDON_REGISTRY_FILE,
    DESCRIPTOR_FILE,
    LICENSE_ENGINEERING_ONLY,
    LICENSE_OFFICIAL_APACHE2,
    PRECISION_LABEL,
    STATUS_INSTALLED,
    STATUS_NOT_INSTALLED,
)

STATUS_INT4_READY = "INT4_DLC_INSTALLED"
STATUS_FP32_PACK = "FP32_SPECIALIST_PACK_PRESENT"
STATUS_UNAVAILABLE = "SPECIALIST_CAPABILITY_UNAVAILABLE"
STATUS_ENGINEERING = "INT4_DLC_INSTALLED_ENGINEERING_ONLY"

#: shipped next to dlc-registry.json.  The runtime cannot read the staging
#: evidence tree, so the numbers a user-facing prompt needs (download size and
#: the DLC memory increment) travel with the addon.  Absent file => the route
#: row simply carries no numbers, and callers must not invent any.
PROFILE_FILE = "dlc-profile.json"
MEMORY_CALIBER = "DLC_INCREMENT = peak_rss - baseline_rss"


def profile(addon_root: Path) -> dict:
    path = Path(addon_root) / PROFILE_FILE
    if not path.is_file():
        return {"schema": "solve-lite.int4-dlc.profile.v1", "present": False, "dlcs": {}}
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["present"] = True
    return payload


def registry(addon_root: Path) -> dict:
    path = Path(addon_root) / ADDON_REGISTRY_FILE
    if not path.is_file():
        return {"schema": "solve-lite.int4-dlc.registry.v1", "installed": {}, "present": False}
    data = json.loads(path.read_text(encoding="utf-8"))
    data["present"] = True
    return data


def installed_dlc_ids(addon_root: Path) -> list[str]:
    return sorted(registry(addon_root).get("installed", {}))


def asset_root(addon_root: Path) -> Path:
    return Path(addon_root) / ADDON_ASSET_ROOT_DIRNAME


def asset_entry_state(entry: Path) -> str:
    if entry.is_symlink():
        return "present" if entry.exists() else "broken_symlink"
    if entry.is_dir():
        return "present"
    return "absent"


def _display(unit: dict, prof: dict) -> dict:
    """Add-on name / download size / memory increment for the prompt renderer."""
    row = (prof.get("dlcs") or {}).get(unit["dlc_id"]) or {}
    memory = row.get("memory") or {}
    return {
        "addon": row.get("addon"),
        "addon_cn": row.get("addon_cn"),
        "capability": row.get("capability"),
        "download_bytes": row.get("download_bytes"),
        "download_mb": row.get("download_mb"),
        "memory": memory or None,
        "memory_caliber": prof.get("memory_caliber") or MEMORY_CALIBER,
        "profile_present": bool(prof.get("present")),
    }


def capability_view(addon_root: Path, *, fp32_asset_root: Path | None = None) -> dict:
    """Per-route capability snapshot.  INT4 wins, fp32 pack is reported as-is."""
    addon_root = Path(addon_root)
    root = asset_root(addon_root)
    reg = registry(addon_root)
    prof = profile(addon_root)
    routes: dict[str, dict] = {}
    for unit in DLC_UNITS:
        member_states = {}
        int4_ready = True
        for member in unit["members"]:
            entry = root / member["asset_rel"]
            state = asset_entry_state(entry)
            member_states[member["asset_rel"]] = state
            if state != "present":
                int4_ready = False
            elif not (entry / DESCRIPTOR_FILE).is_file():
                int4_ready = False
        installed = unit["dlc_id"] in reg.get("installed", {})
        if installed and int4_ready:
            status = (
                STATUS_INT4_READY
                if unit["license_class"] == LICENSE_OFFICIAL_APACHE2
                else STATUS_ENGINEERING
            )
        elif fp32_asset_root is not None and all(
            (Path(fp32_asset_root) / m["asset_rel"] / "config.json").is_file()
            for m in unit["members"]
        ):
            status = STATUS_FP32_PACK
        else:
            status = STATUS_UNAVAILABLE
        routes[unit["route"]] = {
            "dlc_id": unit["dlc_id"],
            "status": status,
            "installed": installed,
            "members": member_states,
            "license_class": unit["license_class"],
            "license_spdx": unit["license_spdx"],
            "distributable": bool(unit.get("distributable", True)),
            "precision": PRECISION_LABEL if status.startswith("INT4") else None,
            "engineering_only": unit["license_class"] == LICENSE_ENGINEERING_ONLY,
            # --- what a "capability missing" prompt needs (VV §6).  Every field
            # --- is None when the shipped profile is absent: a prompt must never
            # --- render a number the addon cannot back up.
            "display": _display(unit, prof),
        }
    return {
        "schema": "solve-lite.int4-dlc.capability.v1",
        "addon_root": str(addon_root),
        "asset_root": str(root),
        "addon_dirname": ADDON_DIRNAME,
        "installed_dlc_ids": sorted(reg.get("installed", {})),
        "registry_present": bool(reg.get("present")),
        "routes": routes,
        "default_chain_requires_dlc": False,
        "notes": [
            "DLCs are opt-in: with no registry file every route reports "
            f"{STATUS_UNAVAILABLE} (identical to the Lite default chain).",
            "route 'financial' is one DLC unit containing two co-required checkpoints.",
        ],
    }


def status_constants() -> dict:
    return {
        "INT4_READY": STATUS_INT4_READY,
        "FP32_PACK": STATUS_FP32_PACK,
        "UNAVAILABLE": STATUS_UNAVAILABLE,
        "ENGINEERING": STATUS_ENGINEERING,
        "INSTALLED": STATUS_INSTALLED,
        "NOT_INSTALLED": STATUS_NOT_INSTALLED,
    }
