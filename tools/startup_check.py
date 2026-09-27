#!/usr/bin/env python3
"""Read-only v0.1.9 startup and shared-runtime integrity check."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def check_core(root: Path) -> dict:
    try:
        manifest = json.loads((root / "CORE_ASSET_MANIFEST.json").read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return {"status": "FAIL", "reason": f"MANIFEST:{type(exc).__name__}"}
    runtime = root / manifest["runtime_root"]
    failures = []
    for item in manifest.get("artifacts", []):
        path = runtime / item["relative_path"]
        if not path.is_file() or path.stat().st_size != item["bytes"] or sha256(path) != item["sha256"]:
            failures.append(item["relative_path"])
    return {"status": "PASS" if not failures else "FAIL", "failures": failures, "runtime": str(runtime)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--runtime-root", type=Path, default=None)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    root = args.root.expanduser().resolve()
    scripts = root / "plugins/solve-lite/skills/solve-lite/scripts"
    sys.path.insert(0, str(scripts))
    import compact_runtime
    import shared_runtime
    import solve_lite_abi

    runtime = Path(args.runtime_root or shared_runtime.resolve(root / "plugins/solve-lite/skills/solve-lite")).resolve()
    core = check_core(root)
    health = solve_lite_abi.healthcheck(runtime)
    compact = compact_runtime.status(runtime)
    checks = {
        "core_hashes": core.get("status") == "PASS",
        "healthcheck": health.get("status") == "PASS",
        "compact_runtime": compact.get("status") == "PASS",
        "single_shared_encoder": compact.get("shared_encoder_copies") == 1,
        "network0_runtime": compact.get("network_used") is False,
        "no_torch_runtime": compact.get("torch_runtime") is False,
        "no_transformers_runtime": compact.get("transformers_runtime") is False,
    }
    payload = {
        "STARTUP_CHECK": "PASS" if all(checks.values()) else "FAIL",
        "version": "v0.1.9",
        "runtime_root": str(runtime),
        "checks": checks,
        "core": core,
        "healthcheck": health,
        "compact_runtime": compact,
    }
    print(json.dumps(payload, indent=2 if args.json else None, sort_keys=True))
    return 0 if payload["STARTUP_CHECK"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
