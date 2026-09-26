"""Language-neutral, session-routed public ABI — LITE build line.

Same public surface as the frozen Full core (`solve_lite.abi:route_session` plus
`healthcheck`) so a host cannot tell the two apart at the entrypoint level.  The
difference is contractual, not cosmetic: the LITE ABI reports a capability
registry and never requires the optional specialist model pack at import or
startup.

Refusal semantics (PHASE 2B §三):
  native Core missing / hash mismatch  -> CORE_ASSET_UNAVAILABLE
  specialist model pack missing        -> SPECIALIST_CAPABILITY_UNAVAILABLE
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from .lite_runtime.capability import capability_report, native_core_status
from .lite_runtime.frozen_runtime_lite import (
    LITE_NATIVE_CAPABILITIES,
    LITE_RUNTIME_SCHEMA,
    FrozenKernelLite,
    run_frozen_case_lite,
)
from .presentation import detect_session_locale

ABI_SCHEMA = "solve-lite.lite-abi.v1"


def route_session(
    workspace: str | Path,
    case: dict[str, Any],
    session: Mapping[str, Any] | None,
    *,
    asset_root: str | Path | None = None,
    namespace: str = "production",
    invocation_id: str | None = None,
) -> dict[str, Any]:
    """Route one ordinary host session without a user language selector.

    Never downloads, never requires the specialist pack, and never substitutes a
    computation for a missing capability.
    """
    locale = detect_session_locale(session)
    result = run_frozen_case_lite(
        workspace,
        case,
        asset_root=asset_root,
        namespace=namespace,
        invocation_id=invocation_id,
        locale=locale,
    )
    result["presentation_locale"] = locale
    return result


def capabilities(asset_root: str | Path | None = None) -> dict[str, Any]:
    """Capability registry snapshot: no model load, no torch, no network."""
    native = native_core_status()
    report = capability_report(native, asset_root)
    report["abi_schema"] = ABI_SCHEMA
    report["runtime_schema"] = LITE_RUNTIME_SCHEMA
    return report


def healthcheck() -> dict[str, Any]:
    """Return import-level health without loading models or using the network."""
    native = native_core_status()
    return {
        "status": "PASS" if native["status"] == "AVAILABLE" else "FAIL",
        "entrypoint": "solve_lite.abi:route_session",
        "build_line": "LITE",
        "runtime_schema": LITE_RUNTIME_SCHEMA,
        "native_capabilities": list(LITE_NATIVE_CAPABILITIES),
        "native_core": native,
        "specialist_pack_required": False,
        "torch_imported": False,
        "offline": True,
        "telemetry": False,
        "network_used": False,
    }


def instantiate(asset_root: str | Path | None = None, *, require_specialist: bool = False) -> FrozenKernelLite:
    return FrozenKernelLite(asset_root, require_specialist=require_specialist)


__all__ = ["ABI_SCHEMA", "capabilities", "healthcheck", "instantiate", "route_session"]
