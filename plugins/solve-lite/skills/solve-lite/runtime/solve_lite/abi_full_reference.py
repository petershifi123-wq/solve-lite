"""Language-neutral, session-routed public ABI."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from .frozen_runtime import run_frozen_case
from .presentation import detect_session_locale


def route_session(
    workspace: str | Path,
    case: dict[str, Any],
    session: Mapping[str, Any] | None,
    *,
    asset_root: str | Path | None = None,
    namespace: str = "production",
    invocation_id: str | None = None,
) -> dict[str, Any]:
    """Route one ordinary host session without a user language selector."""
    locale = detect_session_locale(session)
    result = run_frozen_case(
        workspace,
        case,
        asset_root=asset_root,
        namespace=namespace,
        invocation_id=invocation_id,
        locale=locale,
    )
    result["presentation_locale"] = locale
    return result


def healthcheck() -> dict[str, Any]:
    """Return import-level health without loading models or using the network."""
    return {
        "status": "PASS",
        "entrypoint": "solve_lite.abi:route_session",
        "offline": True,
        "telemetry": False,
    }


__all__ = ["healthcheck", "route_session"]
