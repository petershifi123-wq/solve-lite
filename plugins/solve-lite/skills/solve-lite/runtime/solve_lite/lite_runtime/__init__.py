"""Current LITE runtime package.

Contents:
  capability.py          native/shared-CoreML capability registry
  frozen_runtime_lite.py bundled native Markov execution
  _kernel_native/        eight verified native modules
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
    """Capability registry snapshot with no model load or network access."""
    return capability_report(native_core_status(), asset_root)


def healthcheck(asset_root: str | Path | None = None) -> dict[str, Any]:
    """Import-level health for the bundled native kernel and shared asset."""
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
        "shared_coreml_required_for_specialist_routes": True,
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
