from __future__ import annotations

import json
from pathlib import Path
from typing import Any


DEFAULT_IDENTITY = {
    "publisher": "Soulite Magic",
    "product": "solve lite",
    "version": "0.1.0",
    "build_id": "solve-lite-0.1.0-local",
    "payload_sha256": None,
    "fingerprint_status": "DEVELOPMENT_UNSEALED",
}


def current_identity() -> dict[str, Any]:
    path = Path(__file__).resolve().parents[2] / "assets" / "build_identity.json"
    if not path.is_file():
        return dict(DEFAULT_IDENTITY)
    value = json.loads(path.read_text(encoding="utf-8"))
    required = {"publisher", "product", "version", "build_id", "payload_sha256"}
    if not required <= set(value):
        raise RuntimeError("INVALID_BUILD_IDENTITY")
    return value
