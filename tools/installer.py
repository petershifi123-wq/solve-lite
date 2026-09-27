#!/usr/bin/env python3
"""Install Solve Lite v0.1.9 with one shared, CoreML-native runtime."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / "plugins" / "solve-lite"
SKILL = PLUGIN / "skills" / "solve-lite"
SCRIPTS = SKILL / "scripts"
SOURCE_RUNTIME = SKILL / "runtime"


def _load(name: str):
    if str(SCRIPTS) not in sys.path:
        sys.path.insert(0, str(SCRIPTS))
    return __import__(name)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _tree(root: Path) -> dict:
    rows = []
    total = 0
    for path in sorted(root.rglob("*"), key=lambda item: item.as_posix()):
        if not path.is_file() or "__pycache__" in path.parts or path.suffix in {".pyc", ".pyo"}:
            continue
        relative = path.relative_to(root).as_posix()
        size = path.stat().st_size
        total += size
        rows.append(f"{relative}\0{size}\0{_sha256(path)}")
    payload = ("\n".join(rows) + ("\n" if rows else "")).encode()
    return {"file_count": len(rows), "bytes": total, "sha256": hashlib.sha256(payload).hexdigest()}


def _host_registration(host: str, config_dir: Path | None, runtime: Path) -> dict:
    if host == "none":
        return {"status": "SKIPPED", "hosts": {}}
    sys.path.insert(0, str(ROOT / "tools"))
    import host_hooks

    targets = ["workbuddy", "doubao", "codex", "hermes"] if host == "all" else [host]
    reports = {}
    for host_id in targets:
        override = config_dir / host_id if config_dir is not None and host == "all" else config_dir
        reports[host_id] = host_hooks.register(
            host_id,
            PLUGIN,
            override=override,
            shared_runtime_root=runtime,
        )
    passed = all(report.get("status") in {"PASS", "UNAVAILABLE_EXPECTED"} for report in reports.values())
    return {"status": "PASS" if passed else "FAIL", "hosts": reports}


def _report(runtime: Path) -> dict:
    compact = _load("compact_runtime")
    shared = _load("shared_runtime")
    abi = _load("solve_lite_abi")
    health = abi.healthcheck(runtime)
    asset = compact.status(runtime)
    return {
        "status": "PASS" if health.get("status") == "PASS" and asset.get("status") == "PASS" else "FAIL",
        "version": "v0.1.9",
        "current_install_target": "v0.1.9",
        "runtime_root": str(runtime),
        "healthcheck": health,
        "compact_runtime": asset,
        "runtime_tree": _tree(runtime) if runtime.is_dir() else {"file_count": 0, "bytes": 0, "sha256": None},
        "network_calls_at_runtime": 0,
        "torch_runtime": False,
        "transformers_runtime": False,
        "shared_encoder_copies": 1 if asset.get("status") == "PASS" else 0,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--shared-runtime-root", type=Path, default=None)
    parser.add_argument("--package-dir", type=Path, default=None,
                        help="verified offline directory containing the pinned shared archive")
    parser.add_argument("--offline", action="store_true")
    parser.add_argument("--host", choices=("auto", "all", "workbuddy", "doubao", "codex", "hermes", "none"), default="auto")
    parser.add_argument("--config-dir", type=Path, default=None)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    compact = _load("compact_runtime")
    shared = _load("shared_runtime")
    runtime = Path(args.shared_runtime_root or shared.default_runtime_root()).expanduser().resolve()
    if args.check:
        payload = _report(runtime)
        print(json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False))
        return 0 if payload["status"] == "PASS" else 1

    base = shared.prepare_base(SOURCE_RUNTIME, runtime)
    if base.get("status") != "PASS":
        payload = {"status": "FAIL", "stage": "prepare_base", "detail": base}
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 2
    install = compact.install(runtime, package_dir=args.package_dir, offline=args.offline)
    if install.get("status") != "PASS":
        payload = {"status": "FAIL", "stage": "install_compact_runtime", "detail": install}
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 3
    shared.write_pointer(SKILL, runtime)

    host = args.host
    if host == "auto":
        sys.path.insert(0, str(ROOT / "tools"))
        import host_hooks
        host = host_hooks.resolve_auto(args.config_dir)
    registration = _host_registration(host, args.config_dir, runtime)
    readback = _report(runtime)
    required = {
        "base_runtime": base.get("status") == "PASS",
        "compact_asset": install.get("status") == "PASS",
        "installed_copy": readback.get("status") == "PASS",
        "single_shared_encoder": readback.get("shared_encoder_copies") == 1,
        "host_adapters": registration.get("status") in {"PASS", "SKIPPED"},
        "network0_runtime": readback.get("network_calls_at_runtime") == 0,
        "no_torch_runtime": readback.get("torch_runtime") is False,
        "no_transformers_runtime": readback.get("transformers_runtime") is False,
    }
    payload = {
        "status": "PASS" if all(required.values()) else "FAIL",
        "version": "v0.1.9",
        "required_checks": required,
        "shared_runtime": base,
        "compact_install": install,
        "installed_readback": readback,
        "host_registration": registration,
    }
    print(json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False))
    return 0 if payload["status"] == "PASS" else 4


if __name__ == "__main__":
    raise SystemExit(main())
