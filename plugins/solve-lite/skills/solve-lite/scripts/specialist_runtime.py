"""Pinned, repository-local Python runtime for public specialist routes.

The Lite process never imports specialist dependencies. Installation creates a
venv under the bundled runtime, installs a hash-locked dependency set there,
and records a machine-verifiable receipt. No global or system Python package is
ever installed or modified.
"""

from __future__ import annotations

import hashlib
import json
import os
import platform
import shutil
import subprocess
import sys
import tarfile
import tempfile
import urllib.request
from pathlib import Path
from typing import Any, Mapping

LOCK_NAME = "specialist-runtime-lock.json"
RECEIPT_NAME = "solve-lite-specialist-runtime.json"
BOOTSTRAP_ARCHIVE_NAME = "python-build-standalone.tar.gz"


def skill_root() -> Path:
    return Path(__file__).resolve().parents[1]


def assets_root() -> Path:
    return skill_root() / "assets"


def bundled_runtime_root() -> Path:
    return skill_root() / "runtime"


def load_lock() -> dict[str, Any]:
    return json.loads((assets_root() / LOCK_NAME).read_text(encoding="utf-8"))


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def directory_bytes(path: Path) -> int:
    total = 0
    if not path.exists():
        return 0
    for item in path.rglob("*"):
        try:
            if item.is_file():
                total += item.stat().st_size
        except OSError:
            continue
    return total


def runtime_paths(runtime_root: str | Path | None = None) -> dict[str, Path]:
    root = Path(runtime_root or bundled_runtime_root()).expanduser().resolve()
    spec = load_lock()["runtime"]
    venv = root / spec["venv_dir"]
    return {
        "runtime_root": root,
        "venv": venv,
        "python": venv / "bin" / "python3",
        "receipt": venv / RECEIPT_NAME,
        "bootstrap": root / spec["bootstrap_dir"],
    }


def _python_probe(executable: Path) -> dict[str, Any]:
    code = (
        "import json,platform,sys;"
        "print(json.dumps({'version':list(sys.version_info[:3]),"
        "'machine':platform.machine(),'executable':sys.executable}))"
    )
    try:
        proc = subprocess.run(
            [str(executable), "-I", "-c", code],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
            timeout=15,
        )
        payload = json.loads((proc.stdout or "").strip().splitlines()[-1]) if proc.returncode == 0 else {}
    except (OSError, subprocess.SubprocessError, ValueError, IndexError):
        return {"compatible": False, "executable": str(executable)}
    version = tuple(payload.get("version") or ())
    compatible = (
        len(version) == 3
        and version[:2] == (3, 9)
        and payload.get("machine") in {"arm64", "aarch64"}
    )
    return {**payload, "compatible": compatible, "executable": str(executable)}


def _candidate_pythons(explicit: str | Path | None = None) -> list[Path]:
    candidates: list[Path] = []
    if explicit:
        candidates.append(Path(explicit).expanduser())
    for name in ("python3.9",):
        located = shutil.which(name)
        if located:
            candidates.append(Path(located))
    candidates.extend((Path(sys.executable), Path("/usr/bin/python3")))
    unique: list[Path] = []
    seen: set[str] = set()
    for candidate in candidates:
        key = str(candidate)
        if key not in seen and candidate.is_file():
            unique.append(candidate)
            seen.add(key)
    return unique


def select_compatible_python(explicit: str | Path | None = None) -> dict[str, Any]:
    if platform.system() != "Darwin" or platform.machine() not in {"arm64", "aarch64"}:
        return {
            "status": "UNSUPPORTED_PLATFORM",
            "system": platform.system(),
            "machine": platform.machine(),
        }
    probes = [_python_probe(candidate) for candidate in _candidate_pythons(explicit)]
    chosen = next((probe for probe in probes if probe.get("compatible")), None)
    return {
        "status": "PASS" if chosen else "NO_COMPATIBLE_PYTHON",
        "selected": chosen,
        "probes": probes,
    }


def _download_verified(url: str, expected_sha256: str, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    part = destination.with_suffix(destination.suffix + ".part")
    request = urllib.request.Request(url, headers={"User-Agent": "solve-lite-specialist-runtime"})
    with urllib.request.urlopen(request, timeout=180) as response:  # noqa: S310 - pinned source and hash
        with part.open("wb") as target:
            shutil.copyfileobj(response, target, length=1024 * 1024)
    observed = sha256_file(part)
    if observed != expected_sha256:
        part.unlink(missing_ok=True)
        raise ValueError(f"bootstrap archive SHA-256 mismatch: {observed}")
    os.replace(part, destination)


def _safe_extract(archive: Path, destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    root = destination.resolve()
    with tarfile.open(archive, "r:gz") as bundle:
        for member in bundle.getmembers():
            target = (destination / member.name).resolve()
            if target != root and root not in target.parents:
                raise ValueError(f"unsafe bootstrap archive member: {member.name}")
            if member.issym() or member.islnk():
                link_target = (target.parent / member.linkname).resolve()
                if link_target != root and root not in link_target.parents:
                    raise ValueError(f"unsafe bootstrap archive link: {member.name}")
        bundle.extractall(destination)  # noqa: S202 - every path and link was bounded above


def prepare_fallback_python(runtime_root: str | Path | None = None) -> dict[str, Any]:
    paths = runtime_paths(runtime_root)
    lock = load_lock()
    fallback = lock["python"]["fallback"]
    executable = paths["bootstrap"] / "python" / "bin" / "python3"
    ready = _python_probe(executable)
    if ready.get("compatible"):
        return {"status": "PASS", "selected": ready, "source": "cached_pinned_fallback"}
    paths["bootstrap"].mkdir(parents=True, exist_ok=True)
    archive = paths["bootstrap"] / BOOTSTRAP_ARCHIVE_NAME
    if not archive.is_file() or sha256_file(archive) != fallback["archive_sha256"]:
        _download_verified(fallback["archive_url"], fallback["archive_sha256"], archive)
    with tempfile.TemporaryDirectory(dir=str(paths["bootstrap"]), prefix="extract-") as tmp:
        extracted = Path(tmp)
        _safe_extract(archive, extracted)
        source = extracted / "python"
        if not (source / "bin" / "python3").is_file():
            raise FileNotFoundError("pinned Python archive has no python/bin/python3")
        final = paths["bootstrap"] / "python"
        if final.exists():
            shutil.rmtree(final)
        os.replace(source, final)
    ready = _python_probe(executable)
    if not ready.get("compatible"):
        return {"status": "FAIL", "reason": "PINNED_FALLBACK_PYTHON_NOT_COMPATIBLE", "probe": ready}
    return {"status": "PASS", "selected": ready, "source": "downloaded_pinned_fallback"}


def _expected_imports() -> dict[str, str]:
    return dict(load_lock()["requirements"]["required_imports"])


def receipt_status(runtime_root: str | Path | None = None) -> dict[str, Any]:
    """Filesystem-only readiness check used by Lite startup/capabilities."""
    paths = runtime_paths(runtime_root)
    lock = load_lock()
    lock_path = assets_root() / lock["requirements"]["lock_path"]
    try:
        receipt = json.loads(paths["receipt"].read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"status": "NOT_INSTALLED", "python": str(paths["python"]), "probe_mode": "receipt_only"}
    expected = _expected_imports()
    ok = (
        paths["python"].is_file()
        and lock_path.is_file()
        and sha256_file(lock_path) == lock["requirements"]["lock_sha256"]
        and receipt.get("requirements_lock_sha256") == lock["requirements"]["lock_sha256"]
        and receipt.get("verified_versions") == expected
        and receipt.get("python_abi") == "cp39"
        and receipt.get("machine") in {"arm64", "aarch64"}
        and receipt.get("global_site_packages") is False
        and receipt.get("system_pip_install") is False
    )
    return {
        "status": "PASS" if ok else "FAIL",
        "python": str(paths["python"]),
        "exact_versions": receipt.get("verified_versions") == expected,
        "lock_hash_verified": receipt.get("requirements_lock_sha256") == lock["requirements"]["lock_sha256"],
        "python_abi_cp39": receipt.get("python_abi") == "cp39",
        "machine_arm64": receipt.get("machine") in {"arm64", "aarch64"},
        "probe_mode": "receipt_only",
        "specialist_process_started": False,
        "torch_imported_in_lite": "torch" in sys.modules,
    }


def healthcheck(runtime_root: str | Path | None = None, *, deep: bool = True) -> dict[str, Any]:
    """Probe the local env in a child process; import nothing into Lite."""
    if not deep:
        return receipt_status(runtime_root)
    paths = runtime_paths(runtime_root)
    python = paths["python"]
    if not python.is_file():
        return {"status": "NOT_INSTALLED", "python": str(python), "torch_imported_in_lite": "torch" in sys.modules}
    expected = _expected_imports()
    code = (
        "import importlib,json,sys;"
        f"expected={expected!r};"
        "seen={};errors={};"
        "[(seen.__setitem__(n,getattr(importlib.import_module(n),'__version__','')) "
        "if not errors else None) for n in []];"
        "\nfor n in expected:\n"
        " try: seen[n]=str(getattr(importlib.import_module(n),'__version__',''))\n"
        " except Exception as e: errors[n]=type(e).__name__+':'+str(e)[:160]\n"
        "import platform;"
        "print(json.dumps({'versions':seen,'errors':errors,'prefix':sys.prefix,'base_prefix':sys.base_prefix,"
        "'python_version':list(sys.version_info[:3]),'machine':platform.machine()}))"
    )
    try:
        proc = subprocess.run(
            [str(python), "-I", "-c", code],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
            timeout=120,
        )
        payload = json.loads((proc.stdout or "").strip().splitlines()[-1]) if proc.returncode == 0 else {}
    except (OSError, subprocess.SubprocessError, ValueError, IndexError) as exc:
        return {"status": "FAIL", "reason": type(exc).__name__, "python": str(python)}
    versions = payload.get("versions") or {}
    exact = not payload.get("errors") and all(versions.get(name) == version for name, version in expected.items())
    python_abi = tuple(payload.get("python_version") or ())[:2] == (3, 9)
    machine_ok = payload.get("machine") in {"arm64", "aarch64"}
    lock_path = assets_root() / load_lock()["requirements"]["lock_path"]
    lock_ok = lock_path.is_file() and sha256_file(lock_path) == load_lock()["requirements"]["lock_sha256"]
    receipt_ok = paths["receipt"].is_file()
    return {
        "status": "PASS" if proc.returncode == 0 and exact and lock_ok and receipt_ok and python_abi and machine_ok else "FAIL",
        "python": str(python),
        "versions": versions,
        "errors": payload.get("errors") or {},
        "exact_versions": exact,
        "lock_hash_verified": lock_ok,
        "receipt_present": receipt_ok,
        "isolated_prefix": payload.get("prefix") != payload.get("base_prefix"),
        "python_abi_cp39": python_abi,
        "machine_arm64": machine_ok,
        "torch_imported_in_lite": "torch" in sys.modules,
        "probe_mode": "deep_child_import",
        "specialist_process_started": True,
    }


def _stamp_verified_receipt(paths: Mapping[str, Path], result: Mapping[str, Any]) -> None:
    if result.get("status") != "PASS":
        return
    try:
        receipt = json.loads(paths["receipt"].read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return
    receipt.update(
        {
            "verified_versions": dict(result.get("versions") or {}),
            "python_abi": "cp39" if result.get("python_abi_cp39") else "UNSUPPORTED",
            "machine": "arm64" if result.get("machine_arm64") else "UNSUPPORTED",
            "deep_healthcheck": "PASS",
        }
    )
    paths["receipt"].write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def ensure(
    runtime_root: str | Path | None = None,
    *,
    python: str | Path | None = None,
    wheel_dir: str | Path | None = None,
) -> dict[str, Any]:
    paths = runtime_paths(runtime_root)
    ready = healthcheck(runtime_root)
    if ready.get("status") == "PASS":
        _stamp_verified_receipt(paths, ready)
        return {**ready, "created": False}
    lock = load_lock()
    lock_path = assets_root() / lock["requirements"]["lock_path"]
    observed_lock = sha256_file(lock_path) if lock_path.is_file() else None
    if observed_lock != lock["requirements"]["lock_sha256"]:
        return {"status": "FAIL", "reason": "REQUIREMENTS_LOCK_SHA256_MISMATCH", "observed": observed_lock}
    selected = select_compatible_python(python)
    if selected["status"] != "PASS":
        try:
            selected = prepare_fallback_python(runtime_root)
        except Exception as exc:  # noqa: BLE001 - installer must return a closed failure
            return {"status": "FAIL", "reason": f"PYTHON_BOOTSTRAP_FAILED:{type(exc).__name__}", "detail": str(exc)[:300]}
    source_python = Path(selected["selected"]["executable"])
    if paths["venv"].exists():
        shutil.rmtree(paths["venv"])
    proc = subprocess.run(
        [str(source_python), "-m", "venv", str(paths["venv"])],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=False,
    )
    if proc.returncode != 0:
        return {"status": "FAIL", "reason": "VENV_CREATE_FAILED", "stderr": (proc.stderr or "")[-300:]}
    command = [str(paths["python"]), "-m", "pip", "install", "--disable-pip-version-check", "--require-hashes"]
    if wheel_dir:
        command += ["--no-index", "--find-links", str(Path(wheel_dir).expanduser().resolve())]
    command += ["-r", str(lock_path)]
    env = dict(os.environ)
    env["PYTHONNOUSERSITE"] = "1"
    installed = subprocess.run(command, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=False)
    if installed.returncode != 0:
        return {
            "status": "FAIL",
            "reason": "PINNED_DEPENDENCY_INSTALL_FAILED",
            "returncode": installed.returncode,
            "stderr": (installed.stderr or "")[-1000:],
        }
    receipt = {
        "schema": "solve-lite.specialist-runtime-receipt.v1",
        "python": _python_probe(paths["python"]),
        "source_python": str(source_python),
        "requirements_lock": str(lock_path),
        "requirements_lock_sha256": observed_lock,
        "global_site_packages": False,
        "system_pip_install": False,
    }
    paths["receipt"].write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    checked = healthcheck(runtime_root)
    _stamp_verified_receipt(paths, checked)
    return {**checked, "created": True, "source_python": str(source_python)}


def worker_environment(runtime_root: str | Path | None = None) -> dict[str, str]:
    paths = runtime_paths(runtime_root)
    return {
        "SOLVE_LITE_SPECIALIST_WORKER": "1",
        "SOLVE_LITE_RUNTIME_ROOT": str(paths["runtime_root"]),
        "PYTHONNOUSERSITE": "1",
    }
