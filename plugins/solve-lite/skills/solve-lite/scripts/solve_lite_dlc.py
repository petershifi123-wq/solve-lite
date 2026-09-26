"""Public Specialist DLC component layer.

Base Lite is the product you get from a plain clone: native decisions, offline,
no model pack.  Specialist capabilities ship as *DLC components* - separate
downloads from the public release - and this module is the whole public contract
for them:

  install      download from the public release, verify, materialise, register
  capability   per-capability status (never a claim of a computation we cannot run)
  activation   opt-in only, lazy, at most one resident DLC (DLCBusy), no preload

Rules this module keeps:

* install is the only step that may touch the network, and only the GitHub
  release of this repository is ever used - no third party, no model hub;
* runtime, healthcheck and capability paths never download and never import torch;
* a missing or incomplete DLC is reported as SPECIALIST_CAPABILITY_UNAVAILABLE -
  never as CORE_ASSET_UNAVAILABLE and never as a fabricated answer;
* installing a DLC never activates it.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import sys
import time
from pathlib import Path
from typing import Any, Iterable, Mapping

SCHEMA = "solve-lite.dlc-registry.v1"

ADDON_DIRNAME = "solve-lite-int4-dlc"
ASSET_ROOT_DIRNAME = "asset-root"
INSTALLED_DIRNAME = "installed"
STAGED_DIRNAME = "staged"
REGISTRY_FILENAME = "dlc-registry.json"
EVENTS_FILENAME = "dlc-events.jsonl"
DESCRIPTOR_FILENAME = "dlc.json"

RELEASE_TAG = "v0.1.5"
RELEASE_BASE_URL = f"https://github.com/petershifi123-wq/solve-lite/releases/download/{RELEASE_TAG}"

STATUS_INSTALLED = "DLC_INSTALLED"
STATUS_NOT_INSTALLED = "DLC_NOT_INSTALLED"
STATUS_NOT_PUBLIC = "DLC_NOT_PUBLIC"

LICENSE_OFFICIAL = "OFFICIAL_DLC_APACHE_2_0"
LICENSE_ENGINEERING_ONLY = "ENGINEERING_VERIFICATION_ONLY_DO_NOT_DISTRIBUTE"

#: activation policy inherited from the sealed INT4 DLC line
MAX_RESIDENT_DLC = 1
PRELOAD_AT_STARTUP = False
ACTIVATION_ENV = "SOLVE_LITE_INT4_DLC"
ACTIVATION_ROOT_ENV = "SOLVE_LITE_INT4_DLC_ROOT"
ACTIVATION_IDLE_ENV = "SOLVE_LITE_INT4_DLC_IDLE_SECONDS"

#: the four capability units of the component.  Financial is engineering-only and
#: is deliberately NOT exported: it can never be installed from the public release.
DLC_UNITS: tuple[dict[str, Any], ...] = (
    {
        "unit_id": "review-sst2-distilbert-int4-g64",
        "addon_id": "solve-lite-review-compact",
        "capability": "advanced_sentiment_review_polarity",
        "route": "review",
        "route_dirs": ("model-cache/distilbert--distilbert-base-uncased-finetuned-sst-2-english",),
        "package": "solve-lite-review-compact.tar.gz",
        "package_bytes": 29172762,
        "package_sha256": "264a7bbd905426ac9c2c67bbc2fc813d0bca60967ec329a955e8e2e7c0573a34",
        "weights_sha256": "6129187636f5e588649b38d083bff01abfb9965c8bc1421a48031914df4930e8",
        "container_name": "model.slint4.safetensors",
        "quantization_scheme": "mixed_int4_int3_groupwise",
        "decision_agreement_vs_frozen_fp32_reference": 0.9747,
        "reference_decisions": 1500,
        "license_class": LICENSE_OFFICIAL,
        "public": True,
    },
    {
        "unit_id": "topic-dbpedia14-bert-int4-g64",
        "addon_id": "solve-lite-topic-compact",
        "capability": "knowledge_topic_routing",
        "route": "topic",
        "route_dirs": ("model-cache/fabriceyhc--bert-base-uncased-dbpedia_14",),
        "package": "solve-lite-topic-compact.tar.gz",
        "package_bytes": 44319676,
        "package_sha256": "ad2933cbe828441b6b3196b1230b094e81e4726eeac258d119373802b94a9e08",
        "weights_sha256": "caa82163a0c90f35ca1e1509b1c000cdfe3da195fd9120cd3aeed1544817f901",
        "container_name": "model.slint4.safetensors",
        "quantization_scheme": "mixed_int4_int3_groupwise",
        "decision_agreement_vs_frozen_fp32_reference": 0.9913,
        "reference_decisions": 1500,
        "license_class": LICENSE_OFFICIAL,
        "public": True,
    },
    {
        "unit_id": "nli-deberta-v3-base-int4-g64",
        "addon_id": "solve-lite-nli-compact",
        "capability": "natural_language_inference",
        "route": "nli",
        "route_dirs": ("model-cache/cross-encoder--nli-deberta-v3-base",),
        "package": "solve-lite-nli-compact.tar.gz",
        "package_bytes": 76350116,
        "package_sha256": "4deddd7e5c5e9457af6746d0b28f1343223721a445142b7a91fcc626c956df00",
        "weights_sha256": "24c8b72e2b546e3dab7e4dbf587e71d950712f0f098c2194cb4a90de28abc46f",
        "container_name": "model.slint4.safetensors",
        "quantization_scheme": "mixed_int4_int3_groupwise",
        "decision_agreement_vs_frozen_fp32_reference": 0.9593,
        "reference_decisions": 1500,
        "license_class": LICENSE_OFFICIAL,
        "public": True,
    },
    {
        "unit_id": "financial-pair-int4-g64-ENGINEERING-ONLY",
        "addon_id": "financial-pair",
        "capability": "financial_sentiment_pair",
        "route": "financial",
        "route_dirs": (
            "model-cache/ProsusAI--finbert",
            "model-cache-public-trained/financial_sentiment",
        ),
        "package": None,
        "package_bytes": None,
        "package_sha256": None,
        "weights_sha256": None,
        "container_name": "model.slint4.safetensors",
        "quantization_scheme": "mixed_int4_int3_groupwise",
        "decision_agreement_vs_frozen_fp32_reference": None,
        "reference_decisions": None,
        "license_class": LICENSE_ENGINEERING_ONLY,
        "public": False,
    },
)

PYTHON_DEPENDENCIES: tuple[str, ...] = ("torch", "transformers")


# --------------------------------------------------------------------------- paths


def addon_root(runtime_root: str | Path) -> Path:
    return Path(runtime_root).expanduser().resolve() / "addons" / ADDON_DIRNAME


def effective_asset_root(runtime_root: str | Path) -> Path | None:
    """Specialist asset root the kernel should be pointed at, when installed."""
    root = addon_root(runtime_root) / ASSET_ROOT_DIRNAME
    try:
        if (root / "model-cache").is_dir():
            return root
    except OSError:
        return None
    return None


def registry_path(runtime_root: str | Path) -> Path:
    return addon_root(runtime_root) / REGISTRY_FILENAME


def events_path(runtime_root: str | Path) -> Path:
    return addon_root(runtime_root) / EVENTS_FILENAME


def unit(unit_id: str) -> dict[str, Any]:
    for item in DLC_UNITS:
        if item["unit_id"] == unit_id or item["addon_id"] == unit_id:
            return dict(item)
    raise KeyError(unit_id)


def public_units() -> list[dict[str, Any]]:
    return [dict(item) for item in DLC_UNITS if item["public"]]


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _module_present(name: str) -> bool:
    """Filesystem-only presence test; never enters the import machinery."""
    for entry in list(sys.path):
        if not entry:
            continue
        base = Path(entry)
        try:
            if (base / f"{name}.py").is_file() or (base / name / "__init__.py").is_file():
                return True
            if any(base.glob(f"{name}-*.dist-info")) or any(base.glob(f"{name}-*.egg-info")):
                return True
        except OSError:
            continue
    return False


# --------------------------------------------------------------------------- registry


def load_registry(runtime_root: str | Path) -> dict[str, Any]:
    path = registry_path(runtime_root)
    if not path.is_file():
        return {"schema": SCHEMA, "release_tag": RELEASE_TAG, "units": {}, "runtime_root": str(runtime_root)}
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"schema": SCHEMA, "release_tag": RELEASE_TAG, "units": {}, "runtime_root": str(runtime_root)}
    document.setdefault("units", {})
    document.setdefault("schema", SCHEMA)
    document.setdefault("release_tag", RELEASE_TAG)
    document["runtime_root"] = str(runtime_root)
    return document


def _write_registry(runtime_root: str | Path, document: Mapping[str, Any]) -> Path:
    path = registry_path(runtime_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    document = dict(document)
    document["schema"] = SCHEMA
    document["release_tag"] = RELEASE_TAG
    document["runtime_root"] = str(runtime_root)
    path.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def _append_event(runtime_root: str | Path, event: Mapping[str, Any]) -> None:
    path = events_path(runtime_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    record = {"timestamp_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), **event}
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, sort_keys=True) + "\n")


# --------------------------------------------------------------------------- install


def _fetch(url: str, timeout: float = 60.0) -> bytes:
    import urllib.request

    request = urllib.request.Request(url, headers={"User-Agent": "solve-lite-dlc-installer"})
    with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310 - fixed public release URL
        return response.read()


def release_sha256sums(base_url: str = RELEASE_BASE_URL) -> dict[str, str]:
    """Published checksum list of the release, used to cross-check every package."""
    raw = _fetch(f"{base_url.rstrip('/')}/SHA256SUMS").decode("utf-8")
    table: dict[str, str] = {}
    for line in raw.splitlines():
        parts = line.split()
        if len(parts) == 2 and len(parts[0]) == 64:
            table[parts[1]] = parts[0]
    return table


#: download resilience (a flaky CDN must never make the installer look broken)
DOWNLOAD_ATTEMPTS = 3
DOWNLOAD_BACKOFF_SECONDS = 2.0
DOWNLOAD_TIMEOUT_SECONDS = 120.0
#: set to 1 to skip the network entirely (mirror/cache only)
OFFLINE_ENV = "SOLVE_LITE_DLC_OFFLINE"
ATTEMPTS_ENV = "SOLVE_LITE_DLC_DOWNLOAD_ATTEMPTS"
BACKOFF_ENV = "SOLVE_LITE_DLC_BACKOFF_SECONDS"
TIMEOUT_ENV = "SOLVE_LITE_DLC_DOWNLOAD_TIMEOUT"


def download_timeout() -> float:
    raw = os.environ.get(TIMEOUT_ENV)
    try:
        value = float(str(raw).strip()) if raw else DOWNLOAD_TIMEOUT_SECONDS
    except (TypeError, ValueError):
        value = DOWNLOAD_TIMEOUT_SECONDS
    return max(5.0, min(600.0, value))


def backoff_seconds() -> float:
    raw = os.environ.get(BACKOFF_ENV)
    try:
        value = float(str(raw).strip()) if raw else DOWNLOAD_BACKOFF_SECONDS
    except (TypeError, ValueError):
        value = DOWNLOAD_BACKOFF_SECONDS
    return max(0.0, min(30.0, value))


def download_attempts() -> int:
    raw = os.environ.get(ATTEMPTS_ENV)
    try:
        value = int(str(raw).strip()) if raw else DOWNLOAD_ATTEMPTS
    except (TypeError, ValueError):
        value = DOWNLOAD_ATTEMPTS
    return max(1, min(10, value))


def offline_only() -> bool:
    return str(os.environ.get(OFFLINE_ENV, "")).strip().lower() in {"1", "true", "yes", "on"}


def _download_once(url: str, part: Path, *, offset: int) -> dict[str, Any]:
    """One HTTP attempt; resumes from ``offset`` with Range when possible."""
    import urllib.request

    headers = {"User-Agent": "solve-lite-dlc-installer"}
    if offset > 0:
        headers["Range"] = f"bytes={offset}-"
    request = urllib.request.Request(url, headers=headers)
    resumed = False
    with urllib.request.urlopen(request, timeout=download_timeout()) as response:  # noqa: S310 - fixed public release URL
        status = getattr(response, "status", 200)
        if offset > 0 and status == 206:
            resumed = True
        else:
            offset = 0  # server ignored the range: restart the file
        mode = "ab" if resumed else "wb"
        with part.open(mode) as handle:  # noqa: S310 - path is our own staging file
            while True:
                block = response.read(1024 * 1024)
                if not block:
                    break
                handle.write(block)
    return {"resumed": resumed, "offset": offset}


def _download(
    url: str,
    destination: Path,
    *,
    expect_sha256: str | None = None,
    log: Any = None,
) -> dict[str, Any]:
    """Download with retry, exponential backoff, Range resume and hash check.

    Returns a status document; never raises.  A hash mismatch deletes the partial
    file and retries, because a truncated body is the usual cause.
    """
    say = log or (lambda *_args, **_kwargs: None)
    import urllib.error

    destination.parent.mkdir(parents=True, exist_ok=True)
    part = destination.with_suffix(destination.suffix + ".part")
    attempts = download_attempts()
    history: list[dict[str, Any]] = []
    if offline_only():
        return {"status": "DOWNLOAD_SKIPPED", "reason": "OFFLINE_ONLY", "attempts": 0, "history": history}
    for attempt in range(1, attempts + 1):
        offset = part.stat().st_size if part.is_file() else 0
        try:
            info = _download_once(url, part, offset=offset)
            written = part.stat().st_size if part.is_file() else 0
            digest = _sha256_file(part) if part.is_file() else ""
            if written == 0:
                raise ValueError("empty response body")
            if expect_sha256 and digest != expect_sha256:
                history.append({"attempt": attempt, "outcome": "SHA256_MISMATCH", "bytes": written, "sha256": digest})
                say(f"attempt {attempt}: checksum mismatch, retrying ({written} bytes)")
                part.unlink(missing_ok=True)
                _backoff(attempt)
                continue
            os.replace(part, destination)
            history.append({"attempt": attempt, "outcome": "OK", "bytes": written, "sha256": digest,
                            "resumed": info["resumed"]})
            return {
                "status": "OK",
                "attempts": attempt,
                "bytes": written,
                "sha256": digest,
                "resumed": info["resumed"],
                "history": history,
            }
        except Exception as exc:  # noqa: BLE001 - every failure is retried, then reported
            history.append({"attempt": attempt, "outcome": f"{type(exc).__name__}", "detail": str(exc)[:200],
                            "bytes": part.stat().st_size if part.is_file() else 0})
            say(f"attempt {attempt}/{attempts} failed: {type(exc).__name__}")
            if attempt < attempts:
                _backoff(attempt)
    last = history[-1]["outcome"] if history else "NO_ATTEMPT"
    reason = "ATTEMPTS_EXHAUSTED_SHA256_MISMATCH" if last == "SHA256_MISMATCH" else "ATTEMPTS_EXHAUSTED"
    return {
        "status": "DOWNLOAD_FAILED",
        "reason": reason,
        "attempts": attempts,
        "bytes": part.stat().st_size if part.is_file() else 0,
        "history": history,
        "recoverable": True,
    }


def _backoff(attempt: int) -> None:
    delay = backoff_seconds() * (2 ** (attempt - 1))
    time.sleep(min(delay, 30.0))


def _extract(package: Path, destination: Path) -> Path:
    import tarfile

    destination.mkdir(parents=True, exist_ok=True)
    with tarfile.open(package, "r:gz") as archive:
        for member in archive.getmembers():
            target = (destination / member.name).resolve()
            if not str(target).startswith(str(destination.resolve())):
                raise ValueError(f"refusing archive member outside the staging directory: {member.name}")
        archive.extractall(destination)  # noqa: S202 - members are validated above
    return destination


def _payload_root(extracted: Path, relative: str) -> Path:
    """Locate the directory holding ``relative`` inside an extracted package.

    Release packages carry a single top level directory named after the addon;
    the helper also accepts a flattened archive.
    """
    candidates = [extracted / relative]
    for child in sorted(extracted.glob("*")):
        candidates.append(child / relative)
    for candidate in candidates:
        if candidate.is_dir():
            return candidate
    raise FileNotFoundError(f"package does not contain {relative}")


def _materialise(unit_spec: Mapping[str, Any], staged_package_dir: Path, addon: Path) -> dict[str, Any]:
    """Copy the unit's asset directories into installed/<unit_id>/ and link them."""
    installed = addon / INSTALLED_DIRNAME / str(unit_spec["unit_id"])
    installed.mkdir(parents=True, exist_ok=True)
    layers: list[dict[str, Any]] = []
    for relative in unit_spec["route_dirs"]:
        source = _payload_root(staged_package_dir, relative)
        target = installed / relative
        if target.exists():
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(source, target)
        layers.append({"asset_relative_path": relative, "files": sum(1 for item in target.rglob("*") if item.is_file())})
    descriptor = {
        "schema": "solve-lite.dlc.v1",
        "dlc_id": unit_spec["unit_id"],
        "addon_id": unit_spec["addon_id"],
        "capability": unit_spec["capability"],
        "route": unit_spec["route"],
        "asset_relative_paths": list(unit_spec["route_dirs"]),
        "container_name": unit_spec["container_name"],
        "quantization_scheme": unit_spec["quantization_scheme"],
        "weights_sha256": unit_spec["weights_sha256"],
        "precision_label": "INT4_WEIGHT_ONLY_DEQUANT_FP32_ACCUM",
        "license_class": unit_spec["license_class"],
        "decision_agreement_vs_frozen_fp32_reference": unit_spec["decision_agreement_vs_frozen_fp32_reference"],
        "reference_decisions": unit_spec["reference_decisions"],
        "source_release_tag": RELEASE_TAG,
        "source_package": unit_spec["package"],
        "source_package_sha256": unit_spec["package_sha256"],
    }
    (installed / DESCRIPTOR_FILENAME).write_text(json.dumps(descriptor, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    asset_root = addon / ASSET_ROOT_DIRNAME
    for relative in unit_spec["route_dirs"]:
        link = asset_root / relative
        link.parent.mkdir(parents=True, exist_ok=True)
        if link.is_symlink() or link.exists():
            if link.is_symlink() and str(link.resolve()) == str((installed / relative).resolve()):
                continue
            if link.is_dir() and not link.is_symlink():
                continue
            link.unlink()
        try:
            target = os.path.relpath(installed / relative, link.parent)
            link.symlink_to(target)
        except OSError:
            shutil.copytree(installed / relative, link)
    return {"installed_dir": str(installed), "descriptor": descriptor, "layers": layers}


def install_unit(
    unit_id: str,
    *,
    runtime_root: str | Path,
    base_url: str = RELEASE_BASE_URL,
    package_dir: str | Path | None = None,
    verify: bool = True,
    force: bool = False,
    keep_packages: bool = False,
    log: Any = None,
) -> dict[str, Any]:
    """Download, verify, materialise and register one DLC unit.

    ``package_dir`` (a local directory holding the release tarballs) is the
    offline mirror used by the acceptance harness; it is verified against the
    same pinned release checksums, so it is never a weaker path.
    """
    spec = unit(unit_id)
    if not spec["public"]:
        return {
            "status": STATUS_NOT_PUBLIC,
            "unit_id": spec["unit_id"],
            "license_class": spec["license_class"],
            "reason": "ENGINEERING_ONLY_NOT_EXPORTED",
            "detail": "this unit is not published and cannot be installed from the release",
        }
    say = log or (lambda *_args, **_kwargs: None)
    addon = addon_root(runtime_root)
    installed_dir = addon / INSTALLED_DIRNAME / spec["unit_id"]
    if installed_dir.is_dir() and not force:
        return {"status": STATUS_INSTALLED, "unit_id": spec["unit_id"], "already_installed": True,
                "installed_dir": str(installed_dir)}
    staged = addon / STAGED_DIRNAME
    package = staged / str(spec["package"])
    if package_dir is not None:
        origin = Path(package_dir).expanduser() / str(spec["package"])
        if not origin.is_file():
            return {
                "status": "DLC_PACKAGE_MISSING",
                "unit_id": spec["unit_id"],
                "reason": "LOCAL_PACKAGE_NOT_FOUND",
                "detail": str(origin),
            }
        staged.mkdir(parents=True, exist_ok=True)
        if not package.is_file() or _sha256_file(package) != str(spec["package_sha256"]):
            shutil.copy2(origin, package)
        source = f"local:{origin}"
    else:
        if package.is_file() and _sha256_file(package) == str(spec["package_sha256"]):
            source = f"cached:{package}"
        elif offline_only():
            # mirror/cache only: never touch the network in an offline install
            return {
                "status": STATUS_NOT_INSTALLED,
                "unit_id": spec["unit_id"],
                "reason": "OFFLINE_ONLY",
                "detail": "offline mode with no local mirror: nothing downloaded; base Lite is unaffected",
                "recoverable": True,
                "base_lite_unaffected": True,
                "source": "release_url_skipped",
            }
        else:
            url = f"{base_url.rstrip('/')}/{spec['package']}"
            say(f"download {url}")
            outcome = _download(url, package, expect_sha256=str(spec["package_sha256"]), log=say)
            if outcome["status"] != "OK":
                # never fatal: a flaky CDN must not make the install look broken
                return {
                    "status": STATUS_NOT_INSTALLED,
                    "unit_id": spec["unit_id"],
                    "reason": "DOWNLOAD_FAILED",
                    "download_status": outcome["status"],
                    "download_reason": outcome.get("reason"),
                    "attempts": outcome.get("attempts"),
                    "partial_bytes": outcome.get("bytes"),
                    "history": outcome.get("history", []),
                    "url": url,
                    "recoverable": True,
                    "base_lite_unaffected": True,
                    "detail": "specialist add-on not installed; base Lite is unaffected",
                }
            source = url
    digest = _sha256_file(package)
    expected = str(spec["package_sha256"])
    verification = "PINNED_RELEASE_DIGEST"
    if not verify:
        verification = "UNVERIFIED_OPT_OUT"
    elif digest != expected:
        published: str | None = None
        try:
            published = release_sha256sums(base_url).get(str(spec["package"]))
        except Exception:  # noqa: BLE001 - offline hosts still verify against the pin
            published = None
        if published and published == digest:
            verification = "RELEASE_SHA256SUMS_MATCH_PIN_DRIFT"
            say(f"note: {spec['package']} matches the release SHA256SUMS (release rebuilt since the pin)")
        else:
            return {
                "status": "DLC_VERIFY_FAILED",
                "unit_id": spec["unit_id"],
                "reason": "PACKAGE_SHA256_MISMATCH",
                "expected": expected,
                "observed": digest,
                "published_sha256sums": published,
                "detail": "refusing to install bytes that no published checksum vouches for",
            }
    extracted = _extract(package, staged / str(spec["addon_id"]))
    try:
        materialised = _materialise(spec, extracted, addon)
    except (OSError, FileNotFoundError, ValueError) as exc:
        return {
            "status": "DLC_INSTALL_FAILED",
            "unit_id": spec["unit_id"],
            "reason": f"MATERIALISE_FAILED:{type(exc).__name__}",
            "detail": str(exc),
        }
    # the extracted staging tree duplicates the installed payload; drop it unless
    # the caller asked to keep packages for offline re-verification. A package
    # copied from --package-dir is the user's own file and is never removed.
    staged_reclaimed = 0
    if not keep_packages:
        staged_reclaimed = _directory_bytes(extracted) if extracted.is_dir() else 0
        shutil.rmtree(extracted, ignore_errors=True)
        # the staged package is always ours (downloaded or copied in); the user's
        # own mirror file under --package-dir is never touched.
        if package.is_file():
            staged_reclaimed += package.stat().st_size
            package.unlink()
    document = load_registry(runtime_root)
    document["units"][spec["unit_id"]] = {
        "unit_id": spec["unit_id"],
        "addon_id": spec["addon_id"],
        "capability": spec["capability"],
        "route": spec["route"],
        "status": STATUS_INSTALLED,
        "license_class": spec["license_class"],
        "asset_relative_paths": list(spec["route_dirs"]),
        "package": spec["package"],
        "package_bytes": spec["package_bytes"],
        "package_sha256": spec["package_sha256"],
        "observed_package_sha256": digest,
        "verification": verification,
        "installed_bytes": _directory_bytes(installed_dir),
        "source": source,
        "installed_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "activated": False,
        "preloaded": False,
    }
    _write_registry(runtime_root, document)
    _append_event(
        runtime_root,
        {
            "event": "dlc_installed",
            "unit_id": spec["unit_id"],
            "package_sha256": spec["package_sha256"],
            "source": source,
            "network_used": not str(source).startswith("local:"),
            "activation_performed": False,
        },
    )
    assembled = assemble_asset_root(runtime_root)
    return {
        "status": STATUS_INSTALLED,
        "unit_id": spec["unit_id"],
        "asset_root_view": assembled["status"],
        "asset_root_entries": len(assembled["present"]),
        "package": str(package),
        "package_sha256": digest,
        "verification": verification,
        "installed_dir": materialised["installed_dir"],
        "installed_bytes": _directory_bytes(installed_dir),
        "staging_reclaimed_bytes": staged_reclaimed,
        "source": source,
        "activated": False,
    }


def _directory_bytes(path: Path) -> int:
    total = 0
    for item in path.rglob("*"):
        try:
            if item.is_file():
                total += item.stat().st_size
        except OSError:
            continue
    return total


def assemble_asset_root(runtime_root: str | Path, *, force: bool = False) -> dict[str, Any]:
    """(Re)build the runtime asset-root view from the installed units.

    Idempotent and self-healing: a correct symlink is left alone, a stale one is
    repointed, and a filesystem that refuses links (cross-device or read-only)
    gets a copy instead.  Callable at install time, at activation time, or as a
    repair step - never downloads and never imports torch.
    """
    root = Path(runtime_root).expanduser().resolve()
    addon = addon_root(root)
    asset_root = addon / ASSET_ROOT_DIRNAME
    document = load_registry(root)
    records = document.get("units") or {}
    created: list[str] = []
    repaired: list[str] = []
    copied: list[str] = []
    missing: list[str] = []
    units: list[str] = []
    for spec in DLC_UNITS:
        record = records.get(spec["unit_id"]) or {}
        if str(record.get("status")) != STATUS_INSTALLED:
            continue
        installed = addon / INSTALLED_DIRNAME / spec["unit_id"]
        units.append(spec["unit_id"])
        for relative in spec["route_dirs"]:
            source = installed / relative
            if not source.is_dir():
                missing.append(f"{spec['unit_id']}:{relative}")
                continue
            link = asset_root / relative
            link.parent.mkdir(parents=True, exist_ok=True)
            target = os.path.relpath(source, link.parent)
            if link.is_symlink():
                if os.readlink(link) == target:
                    continue
                link.unlink()
                repaired.append(relative)
            elif link.exists() and not force:
                continue
            try:
                link.symlink_to(target)
                created.append(relative)
            except OSError:
                shutil.copytree(source, link, dirs_exist_ok=True)
                copied.append(relative)
    present = [
        relative
        for spec in DLC_UNITS
        for relative in spec["route_dirs"]
        if (asset_root / relative).is_dir()
    ]
    return {
        "status": "PASS" if present else "EMPTY",
        "asset_root": str(asset_root),
        "installed_units": units,
        "present": present,
        "created": created,
        "repaired": repaired,
        "copied": copied,
        "missing": missing,
        "idempotent": not created and not repaired and not copied,
        "network_used": False,
    }


def summarise(results: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate unit results; a failed DLC never fails the install."""
    installed = [i for i in results if i["status"] == STATUS_INSTALLED]
    deferred = [i for i in results if i["status"] != STATUS_INSTALLED]
    stop = [i for i in results if i.get("status") == "DLC_VERIFY_FAILED"]
    status = "SECURITY_STOP" if stop else ("PASS" if not deferred else ("PARTIAL" if installed else "BASE_ONLY"))
    return {
        "status": status,
        "results": results,
        "units_requested": len(results),
        "units_installed": len(installed),
        "units_deferred": [{"unit_id": i["unit_id"], "reason": i.get("reason")} for i in deferred],
        "installed_unit_ids": [i["unit_id"] for i in installed],
        "security_stop": [i["unit_id"] for i in stop],
        "base_lite_unaffected": True,
        "message": f"{len(installed)} specialist add-on(s) installed; base Lite is available now" if installed else "No specialist add-on installed; base Lite is unaffected",
    }


def install_public_units(
    *,
    runtime_root: str | Path,
    base_url: str = RELEASE_BASE_URL,
    package_dir: str | Path | None = None,
    verify: bool = True,
    log: Any = None,
) -> dict[str, Any]:
    results = [
        install_unit(
            spec["unit_id"],
            runtime_root=runtime_root,
            base_url=base_url,
            package_dir=package_dir,
            verify=verify,
            log=log,
        )
        for spec in public_units()
    ]
    return summarise(results)


# --------------------------------------------------------------------------- capability


def _unit_state(unit_spec: Mapping[str, Any], runtime_root: str | Path) -> dict[str, Any]:
    registry = load_registry(runtime_root)
    record = registry["units"].get(str(unit_spec["unit_id"])) or {}
    asset_root = addon_root(runtime_root) / ASSET_ROOT_DIRNAME
    missing_dirs = [item for item in unit_spec["route_dirs"] if not (asset_root / item).is_dir()]
    installed = str(record.get("status")) == STATUS_INSTALLED and not missing_dirs
    if not unit_spec["public"]:
        status = STATUS_NOT_PUBLIC
    elif installed:
        status = STATUS_INSTALLED
    else:
        status = STATUS_NOT_INSTALLED
    return {
        "unit_id": unit_spec["unit_id"],
        "addon_id": unit_spec["addon_id"],
        "capability": unit_spec["capability"],
        "route": unit_spec["route"],
        "status": status,
        "public": bool(unit_spec["public"]),
        "license_class": unit_spec["license_class"],
        "asset_relative_paths": list(unit_spec["route_dirs"]),
        "missing_asset_directories": missing_dirs,
        "package": unit_spec["package"],
        "package_bytes": unit_spec["package_bytes"],
        "package_sha256": unit_spec["package_sha256"],
        "decision_agreement_vs_frozen_fp32_reference": unit_spec["decision_agreement_vs_frozen_fp32_reference"],
        "activated": bool(record.get("activated")),
    }


def capability_view(runtime_root: str | Path) -> dict[str, Any]:
    """Per-capability DLC state.  No import, no network, no model load."""
    states = [_unit_state(spec, runtime_root) for spec in DLC_UNITS]
    missing_modules = [name for name in PYTHON_DEPENDENCIES if not _module_present(name)]
    installed = [item for item in states if item["status"] == STATUS_INSTALLED]
    public_installed = [item for item in installed if item["public"]]
    backend_present = (Path(runtime_root).expanduser().resolve() / "dlc_runtime" / "int4_dlc").is_dir()
    activation_requested = str(os.environ.get(ACTIVATION_ENV, "")).strip().lower() in {"1", "true", "yes", "on"}
    if not public_installed and not any(item["status"] == STATUS_INSTALLED for item in states):
        execution = "SPECIALIST_CAPABILITY_UNAVAILABLE"
        reason = "DLC_NOT_INSTALLED"
    elif not backend_present:
        execution = "SPECIALIST_CAPABILITY_UNAVAILABLE"
        reason = "DLC_EXECUTION_BACKEND_ABSENT"
    elif missing_modules:
        execution = "SPECIALIST_CAPABILITY_UNAVAILABLE"
        reason = "PYTHON_DEPENDENCIES_MISSING"
    elif not activation_requested:
        execution = "SPECIALIST_CAPABILITY_UNAVAILABLE"
        reason = "DLC_INSTALLED_NOT_ACTIVATED"
    else:
        execution = "SPECIALIST_CAPABILITY_OPT_IN_ACTIVE"
        reason = "DLC_ACTIVATED"
    return {
        "schema": SCHEMA,
        "release_tag": RELEASE_TAG,
        "release_base_url": RELEASE_BASE_URL,
        "runtime_root": str(runtime_root),
        "addon_root": str(addon_root(runtime_root)),
        "units": states,
        "installed_units": len(installed),
        "public_installed_units": len(public_installed),
        "not_public_units": [item["unit_id"] for item in states if item["status"] == STATUS_NOT_PUBLIC],
        "missing_python_modules": missing_modules,
        "required_python_modules": list(PYTHON_DEPENDENCIES),
        "execution_backend_present": backend_present,
        "specialist_execution_status": execution,
        "specialist_execution_reason": reason,
        "activation_state": "ACTIVATED" if activation_requested else "NOT_ACTIVATED",
        "activation_env": ACTIVATION_ENV,
        "installed_means_called": not activation_requested,
        "resident_model_limit": MAX_RESIDENT_DLC,
        "activation_policy": activation_contract(enabled=activation_requested),
        "preloaded": PRELOAD_AT_STARTUP,
        "network_used": False,
        "torch_imported": False,
    }


def route_view(runtime_root: str | Path) -> dict[str, Any]:
    view = capability_view(runtime_root)
    return {
        "status": "PASS",
        "installed_routes": [item["route"] for item in view["units"] if item["status"] == STATUS_INSTALLED],
        "not_installed_routes": [item["route"] for item in view["units"] if item["status"] == STATUS_NOT_INSTALLED],
        "not_public_routes": [item["route"] for item in view["units"] if item["status"] == STATUS_NOT_PUBLIC],
        "specialist_execution_status": view["specialist_execution_status"],
        "specialist_execution_reason": view["specialist_execution_reason"],
        "activation_state": view["activation_state"],
        "installed_means_called": view["installed_means_called"],
        "activation_policy": view["activation_policy"],
    }


def activation_contract(*, enabled: bool | None = None) -> dict[str, Any]:
    if enabled is None:
        enabled = str(os.environ.get(ACTIVATION_ENV, "")).strip().lower() in {"1", "true", "yes", "on"}
    return {
        "opt_in_env": ACTIVATION_ENV,
        "root_env": ACTIVATION_ROOT_ENV,
        "idle_env": ACTIVATION_IDLE_ENV,
        "enabled": bool(enabled),
        "installed_means_called": False,
        "preload_at_startup": PRELOAD_AT_STARTUP,
        "max_resident_dlc": MAX_RESIDENT_DLC,
        "lazy_load": True,
        "busy_semantics": "DLCBusy",
        "engine": "int4_dlc.activate:activate",
    }


def unavailable_hint(runtime_root: str | Path) -> dict[str, Any]:
    """What a host should tell a user when a specialist route is refused."""
    view = capability_view(runtime_root)
    return {
        "specialist_execution_status": view["specialist_execution_status"],
        "specialist_execution_reason": view["specialist_execution_reason"],
        "installed_units": [item["unit_id"] for item in view["units"] if item["status"] == STATUS_INSTALLED],
        "installable_units": [
            {"unit_id": item["unit_id"], "package": item["package"], "package_bytes": item["package_bytes"]}
            for item in view["units"]
            if item["public"]
        ],
        "not_public_units": view["not_public_units"],
        "install_command": "python3 tools/installer.py --install-dlc",
        "fallback_computation": False,
    }


def verify_installation(runtime_root: str | Path) -> dict[str, Any]:
    """Download-free verification of what is on disk right now."""
    view = capability_view(runtime_root)
    checks: list[dict[str, Any]] = []
    for state in view["units"]:
        if state["status"] != STATUS_INSTALLED:
            continue
        descriptor = (
            addon_root(runtime_root) / INSTALLED_DIRNAME / state["unit_id"] / DESCRIPTOR_FILENAME
        )
        checks.append(
            {
                "unit_id": state["unit_id"],
                "descriptor_present": descriptor.is_file(),
                "asset_dirs_present": not state["missing_asset_directories"],
            }
        )
    ok = bool(checks) and all(item["descriptor_present"] and item["asset_dirs_present"] for item in checks)
    return {
        "status": "PASS" if ok else ("NOT_INSTALLED" if not checks else "FAIL"),
        "units_checked": checks,
        "specialist_execution_status": view["specialist_execution_status"],
        "specialist_execution_reason": view["specialist_execution_reason"],
        "network_used": False,
    }


def install_units(unit_ids: Iterable[str], **kwargs: Any) -> list[dict[str, Any]]:
    return [install_unit(item, **kwargs) for item in unit_ids]


# --------------------------------------------------------------------------- helpers

#: the int4 backend reads this variable to find the activated DLC asset root
LEGACY_DLC_ROOT_ENV = ACTIVATION_ROOT_ENV


def default_runtime_root() -> Path:
    """The runtime that ships inside this repository (``../runtime``)."""
    return (Path(__file__).resolve().parent / ".." / "runtime").resolve()


def base_install_bytes(repo_root: str | Path, *, runtime_root: str | Path | None = None) -> int:
    """Size of a base Lite install: the clone itself, DLC assets excluded."""
    root = Path(repo_root).resolve()
    excluded = addon_root(runtime_root or default_runtime_root())
    total = 0
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if "__pycache__" in path.parts or path.suffix == ".pyc":
            continue
        if excluded == path or excluded in path.parents:
            continue
        total += path.stat().st_size
    return total


def uninstall_unit(unit_id: str, *, runtime_root: str | Path | None = None) -> str:
    """Remove one installed DLC unit: assets, descriptor and registry entry."""
    root = runtime_root or default_runtime_root()
    addon = addon_root(root)
    removed: list[str] = []
    installed_dir = addon / INSTALLED_DIRNAME / str(unit_id)
    if installed_dir.is_dir():
        shutil.rmtree(installed_dir)
        removed.append("installed")
    spec = next((item for item in DLC_UNITS if item["unit_id"] == unit_id), None)
    if spec:
        asset_root = addon / ASSET_ROOT_DIRNAME
        for relative in spec["route_dirs"]:
            path = asset_root / relative
            if path.is_symlink() or path.is_file():
                path.unlink()
                removed.append(relative)
            elif path.is_dir():
                shutil.rmtree(path)
                removed.append(relative)
    document = load_registry(root)
    document["units"].pop(str(unit_id), None)
    _write_registry(root, document)
    _append_event(root, {"event": "dlc_uninstall", "unit_id": unit_id, "removed": removed})
    return f"{unit_id}:{len(removed)} entries removed" if removed else f"{unit_id}:nothing installed"


__all__ = [
    "ACTIVATION_ENV",
    "ADDON_DIRNAME",
    "DLC_UNITS",
    "LEGACY_DLC_ROOT_ENV",
    "MAX_RESIDENT_DLC",
    "RELEASE_BASE_URL",
    "RELEASE_TAG",
    "SCHEMA",
    "STATUS_INSTALLED",
    "STATUS_NOT_INSTALLED",
    "STATUS_NOT_PUBLIC",
    "activation_contract",
    "addon_root",
    "assemble_asset_root",
    "capability_view",
    "effective_asset_root",
    "install_public_units",
    "install_unit",
    "install_units",
    "load_registry",
    "public_units",
    "release_sha256sums",
    "route_view",
    "unit",
    "unavailable_hint",
    "verify_installation",
]
