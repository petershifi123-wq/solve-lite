"""LITE build line runtime package (VV ruling A3).

Contents:
  capability.py          native/specialist capability registry (no imports, no net)
  frozen_runtime_lite.py derived from the sealed 0.1.3 frozen_runtime.py by an
                         anchored transform; only the global 5-model gate is
                         replaced by per-route capability gating
  _kernel_native/        eight .so: seven byte-identical to Full Core 0.1.3 plus
                         _slk5-lite (the single authorized native delta)
  LITE_CORE_ASSET_MANIFEST.json / LITE_SHA256SUMS.txt
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .capability import (
    AVAILABLE,
    CORE_ASSET_UNAVAILABLE,
    NATIVE_CAPABILITY,
    NATIVE_ROUTES,
    SPECIALIST_CAPABILITY,
    SPECIALIST_CAPABILITY_UNAVAILABLE,
    SPECIALIST_ROUTES,
    UNAVAILABLE,
    capability_report,
    native_core_status,
    specialist_status,
)
from .frozen_runtime_lite import (
    LITE_CASE_RESULT_SCHEMA,
    LITE_NATIVE_CAPABILITIES,
    LITE_RUNTIME_SCHEMA,
    FrozenKernelLite,
    run_frozen_case_lite,
)


def capabilities(asset_root: str | Path | None = None) -> dict[str, Any]:
    """Capability registry snapshot: no model load, no torch, no network."""
    return capability_report(native_core_status(), asset_root)


def healthcheck(asset_root: str | Path | None = None) -> dict[str, Any]:
    """Import-level health for the LITE line: native Core only, pack optional."""
    native = native_core_status()
    specialist = specialist_status(asset_root)
    return {
        "status": "PASS" if native["status"] == AVAILABLE else "FAIL",
        "entrypoint": "solve_lite.abi:route_session",
        "build_line": "LITE",
        "runtime_schema": LITE_RUNTIME_SCHEMA,
        "native_capabilities": list(LITE_NATIVE_CAPABILITIES),
        "native_core_status": native["status"],
        "native_core_reason": native["reason"],
        "native_modules_verified": len(native.get("modules", [])),
        "rebuilt_modules": [item["module"] for item in native.get("modules", []) if item.get("rebuilt")],
        "specialist_status": specialist["status"],
        "specialist_reason": specialist["reason"],
        "specialist_pack_required_at_startup": False,
        "torch_imported": False,
        "offline": True,
        "telemetry": False,
        "network_used": False,
    }

__all__ = [
    "AVAILABLE",
    "CORE_ASSET_UNAVAILABLE",
    "FrozenKernelLite",
    "LITE_CASE_RESULT_SCHEMA",
    "LITE_NATIVE_CAPABILITIES",
    "LITE_RUNTIME_SCHEMA",
    "NATIVE_CAPABILITY",
    "NATIVE_ROUTES",
    "SPECIALIST_CAPABILITY",
    "SPECIALIST_CAPABILITY_UNAVAILABLE",
    "SPECIALIST_ROUTES",
    "UNAVAILABLE",
    "capability_report",
    "native_core_status",
    "run_frozen_case_lite",
    "specialist_status",
]
