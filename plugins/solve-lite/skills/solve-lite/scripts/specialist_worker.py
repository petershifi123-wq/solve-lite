#!/usr/bin/env python3
"""JSON-lines boundary for a specialist decision in the isolated venv."""

from __future__ import annotations

import json
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import solve_lite_abi  # noqa: E402


def main() -> int:
    try:
        request = json.loads(sys.stdin.read())
        result = solve_lite_abi.route_prompt(
            request["workspace"],
            request["case"],
            request.get("session"),
            asset_root=request.get("asset_root"),
            namespace=request.get("namespace", "production"),
            invocation_id=request.get("invocation_id"),
        )
    except Exception as exc:  # noqa: BLE001 - child boundary must stay structured
        result = {
            "status": "SPECIALIST_CAPABILITY_UNAVAILABLE",
            "error": "SPECIALIST_CAPABILITY_UNAVAILABLE",
            "reason": f"SPECIALIST_WORKER_EXCEPTION:{type(exc).__name__}",
            "detail": str(exc)[:300],
            "answers": {},
            "fallback_computation": False,
        }
    sys.stdout.write(json.dumps(result, ensure_ascii=False, sort_keys=True) + "\n")
    return 0 if str(result.get("status", "")).startswith(("PASS", "SPECIALIST")) else 1


if __name__ == "__main__":
    raise SystemExit(main())
