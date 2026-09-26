from __future__ import annotations

import hashlib
import json
import os
import re
import stat
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

SAFE_EXTENSIONS = {".md", ".txt", ".json", ".jsonl", ".csv"}
FORBIDDEN_PARTS = {
    ".ssh",
    ".aws",
    ".gnupg",
    "keychain",
    "secretstorage",
    ".env",
    ".git",
    ".solve-lite",
}
MAX_FILE_BYTES = 2_000_000
TOKENIZER_ID = "solve-unicode-segments-v1"

_TOKEN_RE = re.compile(
    r"[A-Za-z]+(?:'[A-Za-z]+)?|\d+(?:\.\d+)?|[\u3400-\u4dbf\u4e00-\u9fff]|[^\s\w]",
    re.UNICODE,
)
_WORD_RE = re.compile(r"[A-Za-z][A-Za-z0-9_'-]*|\d+(?:\.\d+)?")
_CJK_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff]")
_SECRET_PATTERNS = [
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----[\s\S]*?-----END (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"\bsk-[A-Za-z0-9_-]{12,}\b"),
    re.compile(r"(?i)\b(password|passwd|api[_-]?key|access[_-]?token|secret)\s*[:=]\s*[^\s,;]+"),
]


class SolveError(RuntimeError):
    def __init__(self, code: str, message: str, *, details: Any = None):
        super().__init__(message)
        self.code = code
        self.details = details


@dataclass(frozen=True)
class SafeText:
    path: Path
    relpath: str
    text: str
    content_hash: str


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_text(text: str) -> str:
    return sha256_bytes(text.encode("utf-8"))


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def stable_id(*parts: Any, prefix: str = "") -> str:
    digest = sha256_text("\x1f".join(canonical_json(p) for p in parts))[:24]
    return f"{prefix}{digest}"


def count_tokens(text: str) -> int:
    """Exact count for solve lite's documented local tokenizer, not a provider tokenizer."""
    return len(_TOKEN_RE.findall(text))


def search_terms(text: str) -> list[str]:
    terms = [m.group(0).lower() for m in _WORD_RE.finditer(text)]
    cjk = [m.group(0) for m in _CJK_RE.finditer(text)]
    terms.extend(cjk)
    terms.extend(a + b for a, b in zip(cjk, cjk[1:]))
    return terms


def redact_secrets(text: str) -> tuple[str, int]:
    count = 0
    for pattern in _SECRET_PATTERNS:
        text, found = pattern.subn("[REDACTED_SECRET]", text)
        count += found
    return text, count


def contains_secret(text: str) -> bool:
    return any(pattern.search(text) for pattern in _SECRET_PATTERNS)


def workspace_root(path: str | os.PathLike[str]) -> Path:
    root = Path(path).expanduser().resolve()
    if not root.exists() or not root.is_dir():
        raise SolveError("WORKSPACE_NOT_FOUND", f"Workspace is not a directory: {root}")
    return root


def state_dir(workspace: Path) -> Path:
    path = workspace / ".solve-lite"
    path.mkdir(mode=0o700, exist_ok=True)
    return path


def _has_forbidden_part(path: Path) -> bool:
    return any(part.lower() in FORBIDDEN_PARTS for part in path.parts)


def resolve_bounded_path(workspace: Path, candidate: str | os.PathLike[str]) -> Path:
    raw = Path(candidate).expanduser()
    path = (workspace / raw).resolve() if not raw.is_absolute() else raw.resolve()
    try:
        path.relative_to(workspace)
    except ValueError as exc:
        raise SolveError(
            "PATH_OUTSIDE_WORKSPACE",
            "Input path is outside the authorized workspace",
        ) from exc
    rel = path.relative_to(workspace)
    if _has_forbidden_part(rel):
        raise SolveError("FORBIDDEN_PATH", f"Refusing protected path: {rel}")
    probe = workspace
    for part in rel.parts:
        probe = probe / part
        if probe.is_symlink():
            raise SolveError("SYMLINK_REFUSED", f"Refusing symlink path: {rel}")
    return path


def read_safe_text(workspace: Path, candidate: str | os.PathLike[str], max_bytes: int = MAX_FILE_BYTES) -> SafeText:
    path = resolve_bounded_path(workspace, candidate)
    if path.suffix.lower() not in SAFE_EXTENSIONS:
        raise SolveError("UNSUPPORTED_FILE", f"Unsupported text type: {path.suffix or '<none>'}")
    try:
        mode = path.stat().st_mode
    except OSError as exc:
        raise SolveError("FILE_UNREADABLE", f"Cannot stat file: {path}") from exc
    if not stat.S_ISREG(mode):
        raise SolveError("SPECIAL_FILE_REFUSED", f"Not a regular file: {path}")
    size = path.stat().st_size
    if size > max_bytes:
        raise SolveError("FILE_TOO_LARGE", f"File is {size} bytes; limit is {max_bytes}")
    try:
        data = path.read_bytes()
        text = data.decode("utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise SolveError("FILE_UNREADABLE", f"Cannot read UTF-8 text: {path}") from exc
    return SafeText(path, str(path.relative_to(workspace)), text, sha256_bytes(data))


def iter_safe_files(workspace: Path, source: str | os.PathLike[str]) -> tuple[list[Path], list[dict[str, str]]]:
    root = resolve_bounded_path(workspace, source)
    candidates = [root] if root.is_file() else sorted(root.rglob("*"))
    accepted: list[Path] = []
    skipped: list[dict[str, str]] = []
    for path in candidates:
        rel = str(path.relative_to(workspace)) if path.is_absolute() else str(path)
        if path.is_symlink():
            skipped.append({"path": rel, "reason": "SYMLINK_REFUSED"})
            continue
        if not path.is_file():
            continue
        if _has_forbidden_part(path.relative_to(workspace)):
            skipped.append({"path": rel, "reason": "FORBIDDEN_PATH"})
            continue
        if path.suffix.lower() not in SAFE_EXTENSIONS:
            skipped.append({"path": rel, "reason": "UNSUPPORTED_FILE"})
            continue
        if path.stat().st_size > MAX_FILE_BYTES:
            skipped.append({"path": rel, "reason": "FILE_TOO_LARGE"})
            continue
        if not stat.S_ISREG(path.stat().st_mode):
            skipped.append({"path": rel, "reason": "SPECIAL_FILE_REFUSED"})
            continue
        accepted.append(path)
    return accepted, skipped


def json_ready_error(exc: Exception) -> dict[str, Any]:
    if isinstance(exc, SolveError):
        return {"status": "ERROR", "error": exc.code, "message": str(exc), "details": exc.details}
    return {"status": "ERROR", "error": "INTERNAL_ERROR", "message": str(exc)}


def chunks(items: Iterable[Any], size: int) -> Iterable[list[Any]]:
    batch: list[Any] = []
    for item in items:
        batch.append(item)
        if len(batch) >= size:
            yield batch
            batch = []
    if batch:
        yield batch
