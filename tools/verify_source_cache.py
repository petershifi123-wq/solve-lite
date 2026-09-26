#!/usr/bin/env python3
"""Compare an authorized canonical plugin source with an installed cache."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

IGNORED_NAMES = {".DS_Store"}


def entries(root: Path) -> list[tuple[str, str, int]]:
    result = []
    for path in root.rglob("*"):
        if not path.is_file() or "__pycache__" in path.parts or path.suffix == ".pyc" or path.name in IGNORED_NAMES:
            continue
        result.append((path.relative_to(root).as_posix(), hashlib.sha256(path.read_bytes()).hexdigest(), path.stat().st_size))
    return sorted(result)


def tree_hash(rows: list[tuple[str, str, int]]) -> str:
    payload = "".join(f"{digest}  {path}\n" for path, digest, _ in rows)
    return hashlib.sha256(payload.encode()).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("cache", type=Path)
    args = parser.parse_args()
    source = entries(args.source.resolve())
    cache = entries(args.cache.resolve())
    passed = source == cache
    print(json.dumps({
        "SOURCE_CACHE_PARITY": "PASS" if passed else "FAIL",
        "SOURCE_CACHE_DIFF": 0 if passed else 1,
        "source_files": len(source),
        "cache_files": len(cache),
        "source_tree_sha256": tree_hash(source),
        "cache_tree_sha256": tree_hash(cache),
    }, indent=2, sort_keys=True))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
