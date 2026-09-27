"""One-copy CoreML specialist runtime for Solve Lite v0.1.9."""

from __future__ import annotations

import atexit
import hashlib
import json
import os
import shutil
import subprocess
import tarfile
import tempfile
import time
import urllib.request
from pathlib import Path
from typing import Any, Mapping

ASSET_MANIFEST = Path(__file__).resolve().parents[1] / "assets" / "specialist-assets.json"
ASSET_DIRNAME = "shared-encoder-runtime"
RECEIPT_FILENAME = "compact-runtime-receipt.json"
ROUTES = ("review", "topic", "nli", "financial")
_PROCESS: subprocess.Popen[str] | None = None
_PROCESS_ROOT: Path | None = None


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def manifest() -> dict[str, Any]:
    return json.loads(ASSET_MANIFEST.read_text(encoding="utf-8"))


def asset_root(runtime_root: str | Path) -> Path:
    return Path(runtime_root).expanduser().resolve() / ASSET_DIRNAME


def _tree(root: Path) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    if root.is_dir():
        for path in sorted(root.rglob("*"), key=lambda item: item.as_posix()):
            if path.is_file():
                rows.append({
                    "path": path.relative_to(root).as_posix(),
                    "bytes": path.stat().st_size,
                    "sha256": _sha256(path),
                })
    payload = "\n".join(f"{row['path']}\0{row['bytes']}\0{row['sha256']}" for row in rows)
    if rows:
        payload += "\n"
    return {
        "file_count": len(rows),
        "bytes": sum(row["bytes"] for row in rows),
        "sha256": hashlib.sha256(payload.encode()).hexdigest(),
        "files": rows,
    }


def status(runtime_root: str | Path) -> dict[str, Any]:
    document = manifest()
    expected = document["asset"]
    root = asset_root(runtime_root)
    observed = _tree(root)
    required = (
        root / "bin/solve-lite-coreml-helper",
        root / "model/shared-encoder.mlpackage/Manifest.json",
        root / "heads/heads.json",
        root / "tokenizer/vocab.txt",
        root / "tokenizer/config.json",
    )
    passed = (
        all(path.is_file() for path in required)
        and observed["file_count"] == expected["installed_file_count"]
        and observed["bytes"] == expected["installed_bytes"]
        and observed["sha256"] == expected["installed_tree_sha256"]
    )
    return {
        "status": "PASS" if passed else "NOT_INSTALLED",
        "runtime_root": str(Path(runtime_root).expanduser().resolve()),
        "asset_root": str(root),
        "backend": "CoreML-native",
        "routes": list(ROUTES) if passed else [],
        "network_used": False,
        "torch_runtime": False,
        "transformers_runtime": False,
        "shared_encoder_copies": 1 if passed else 0,
        "expected": {
            "file_count": expected["installed_file_count"],
            "bytes": expected["installed_bytes"],
            "sha256": expected["installed_tree_sha256"],
        },
        "observed": observed,
    }


def _safe_extract(package: Path, destination: Path) -> None:
    with tarfile.open(package, "r:gz") as archive:
        members = archive.getmembers()
        for member in members:
            value = Path(member.name)
            if value.is_absolute() or ".." in value.parts or member.issym() or member.islnk():
                raise ValueError(f"unsafe archive member: {member.name}")
        archive.extractall(destination, members=members)


def _download(url: str, destination: Path) -> None:
    partial = destination.with_suffix(destination.suffix + ".part")
    offset = partial.stat().st_size if partial.is_file() else 0
    headers = {"User-Agent": "solve-lite-v0.1.9-installer"}
    if offset:
        headers["Range"] = f"bytes={offset}-"
    with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=180) as response:
        resumed = offset > 0 and getattr(response, "status", 200) == 206
        with partial.open("ab" if resumed else "wb") as handle:
            while True:
                block = response.read(1024 * 1024)
                if not block:
                    break
                handle.write(block)
    os.replace(partial, destination)


def install(
    runtime_root: str | Path,
    *,
    package_dir: str | Path | None = None,
    offline: bool = False,
) -> dict[str, Any]:
    runtime = Path(runtime_root).expanduser().resolve()
    current = status(runtime)
    if current["status"] == "PASS":
        return {**current, "created": False}
    spec = manifest()["asset"]
    runtime.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix="solve-lite-v019-", dir=str(runtime.parent)))
    try:
        package = temporary / spec["filename"]
        if package_dir is not None:
            source = Path(package_dir).expanduser().resolve() / spec["filename"]
            if not source.is_file():
                return {"status": "FAIL", "reason": "LOCAL_PACKAGE_MISSING", "path": str(source)}
            shutil.copy2(source, package)
            source_label = f"local:{source}"
        elif offline:
            return {"status": "FAIL", "reason": "OFFLINE_WITHOUT_PACKAGE"}
        else:
            _download(spec["download_url"], package)
            source_label = spec["download_url"]
        observed_sha = _sha256(package)
        if package.stat().st_size != spec["download_bytes"] or observed_sha != spec["sha256"]:
            return {
                "status": "FAIL",
                "reason": "ARCHIVE_HASH_MISMATCH",
                "expected_sha256": spec["sha256"],
                "observed_sha256": observed_sha,
                "expected_bytes": spec["download_bytes"],
                "observed_bytes": package.stat().st_size,
            }
        extracted = temporary / "extracted"
        extracted.mkdir()
        _safe_extract(package, extracted)
        staged = extracted / spec["installed_root"]
        if not staged.is_dir():
            return {"status": "FAIL", "reason": "ARCHIVE_ROOT_MISSING"}
        observed = _tree(staged)
        if (
            observed["file_count"] != spec["installed_file_count"]
            or observed["bytes"] != spec["installed_bytes"]
            or observed["sha256"] != spec["installed_tree_sha256"]
        ):
            return {"status": "FAIL", "reason": "INSTALLED_TREE_HASH_MISMATCH", "observed": observed}
        runtime.mkdir(parents=True, exist_ok=True)
        target = asset_root(runtime)
        if target.exists():
            shutil.rmtree(target)
        os.replace(staged, target)
        receipt = {
            "schema": "solve-lite.compact-runtime.install.v1",
            "version": "v0.1.9",
            "source": source_label,
            "archive_sha256": observed_sha,
            "installed_tree_sha256": observed["sha256"],
            "runtime_root": str(runtime),
            "network_used": package_dir is None,
            "offline_after_install": True,
        }
        (runtime / RECEIPT_FILENAME).write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n")
        return {**status(runtime), "created": True, "source": source_label, "receipt": receipt}
    except Exception as exc:  # noqa: BLE001 - installer returns a structured failure
        return {"status": "FAIL", "reason": f"INSTALL_EXCEPTION:{type(exc).__name__}", "detail": str(exc)[:300]}
    finally:
        shutil.rmtree(temporary, ignore_errors=True)


def _close_process() -> None:
    global _PROCESS, _PROCESS_ROOT
    if _PROCESS is not None:
        try:
            if _PROCESS.stdin:
                _PROCESS.stdin.close()
            _PROCESS.terminate()
            _PROCESS.wait(timeout=2)
        except Exception:  # noqa: BLE001
            try:
                _PROCESS.kill()
            except Exception:  # noqa: BLE001
                pass
    _PROCESS = None
    _PROCESS_ROOT = None


atexit.register(_close_process)


def _process(runtime_root: Path) -> subprocess.Popen[str]:
    global _PROCESS, _PROCESS_ROOT
    root = asset_root(runtime_root)
    if _PROCESS is not None and _PROCESS.poll() is None and _PROCESS_ROOT == root:
        return _PROCESS
    _close_process()
    command = [
        str(root / "bin/solve-lite-coreml-helper"),
        str(root / "model/shared-encoder.mlpackage"),
        str(root / "tokenizer/vocab.txt"),
        str(root / "heads/heads.json"),
    ]
    _PROCESS = subprocess.Popen(
        command,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
        env={**os.environ, "NO_PROXY": "*", "no_proxy": "*"},
    )
    _PROCESS_ROOT = root
    return _PROCESS


def _item_texts(route: str, item: Mapping[str, Any]) -> tuple[str, str]:
    if route == "nli":
        return str(item.get("premise") or ""), str(item.get("hypothesis") or "")
    return str(item.get("text") or item.get("content") or ""), ""


def route_case(runtime_root: str | Path, case: Mapping[str, Any], route: str) -> dict[str, Any]:
    runtime = Path(runtime_root).expanduser().resolve()
    ready = status(runtime)
    if ready["status"] != "PASS":
        return {
            "status": "SPECIALIST_CAPABILITY_UNAVAILABLE",
            "error": "SPECIALIST_CAPABILITY_UNAVAILABLE",
            "reason": "COMPACT_RUNTIME_NOT_INSTALLED",
            "answers": {},
            "network_model_calls": 0,
            "fallback_computation": False,
        }
    if route not in ROUTES:
        return {"status": "SPECIALIST_CAPABILITY_UNAVAILABLE", "reason": "UNSUPPORTED_ROUTE", "answers": {}}
    items = {str(item.get("id")): item for item in (case.get("state") or {}).get("items", [])}
    questions = case.get("questions") or {}
    process = _process(runtime)
    answers: dict[str, Any] = {}
    started = time.perf_counter_ns()
    try:
        for qid in sorted(questions):
            question = questions[qid]
            item = items[str(question.get("input_ref"))]
            text_a, text_b = _item_texts(route, item)
            request = {
                "example_id": f"{case.get('case_id')}::{qid}",
                "route": route,
                "text_a": text_a,
                "text_b": text_b,
            }
            assert process.stdin is not None and process.stdout is not None
            process.stdin.write(json.dumps(request, separators=(",", ":"), ensure_ascii=False) + "\n")
            process.stdin.flush()
            line = process.stdout.readline()
            if not line:
                raise RuntimeError("CoreML helper ended before returning a decision")
            response = json.loads(line)
            labels = [str(value) for value in response["labels"]]
            probabilities = [float(value) for value in response["probabilities"]]
            answers[qid] = {
                "value": str(response["prediction"]),
                "support_labels": labels,
                "probabilities": dict(zip(labels, probabilities)),
                "confidence": max(probabilities),
                "backend_latency_ms": float(response.get("latency_ms") or 0.0),
            }
    except Exception as exc:  # noqa: BLE001
        _close_process()
        return {
            "status": "SPECIALIST_CAPABILITY_UNAVAILABLE",
            "error": "SPECIALIST_CAPABILITY_UNAVAILABLE",
            "reason": f"COREML_HELPER_FAILED:{type(exc).__name__}",
            "detail": str(exc)[:300],
            "answers": {},
            "network_model_calls": 0,
            "fallback_computation": False,
        }
    return {
        "status": "PASS",
        "adapter_route": route,
        "answers": answers,
        "runtime_root": str(runtime),
        "backend": "CoreML-native",
        "shared_encoder_copies": 1,
        "network_model_calls": 0,
        "credential_reads": 0,
        "jev_api_calls": 0,
        "torch_imported": False,
        "transformers_imported": False,
        "fallback_computation": False,
        "inference_wall_ms": (time.perf_counter_ns() - started) / 1_000_000,
    }
