#!/usr/bin/env python3
"""Refresh PUBLIC_REPO_MANIFEST.json + SHA256SUMS.txt for this tree.

P0 shipped both files without an in-tree generator, so every later content
change (the P1 host-activation delivery: hook, installer, self-test, the two
double-click installers) made ``tests/test_package.py`` red.  This tool
regenerates both artifacts from what is actually on disk, and it first proves
it can reproduce the *previous* tree hash with the documented algorithm — if
the formula cannot be reproduced the tool refuses to write and says so.

Usage:
    python3 tools/build_public_manifest.py            # verify formula + refresh
    python3 tools/build_public_manifest.py --check    # verify only, write nothing
    python3 tools/build_public_manifest.py --json
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
import time
from pathlib import Path
from typing import Any, Dict, List

ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = ROOT / "PUBLIC_REPO_MANIFEST.json"
CHECKSUMS_PATH = ROOT / "SHA256SUMS.txt"
EXCLUDED_NAMES = {MANIFEST_PATH.name, CHECKSUMS_PATH.name, "MANIFEST.json"}
EXCLUDED_DIRS = {"evidence", "dist", ".git", "__pycache__", ".pytest_cache", ".mypy_cache"}
EXCLUDED_SUFFIXES = (".pyc", ".pyo", ".DS_Store")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    digest.update(path.read_bytes())
    return digest.hexdigest()


def payload_paths() -> List[Path]:
    collected: List[Path] = []
    for dirpath, dirnames, filenames in os.walk(ROOT):
        dirnames[:] = sorted(d for d in dirnames if d not in EXCLUDED_DIRS)
        for name in sorted(filenames):
            relative = (Path(dirpath) / name).relative_to(ROOT).as_posix()
            if relative in EXCLUDED_NAMES or name.endswith(EXCLUDED_SUFFIXES) or name.endswith(".bak"):
                continue
            collected.append(Path(dirpath) / name)
    return sorted(collected, key=lambda value: value.relative_to(ROOT).as_posix())


def mode_of(path: Path) -> str:
    return "0755" if os.access(path, os.X_OK) else "0644"


def rows_for(paths: List[Path]) -> List[Dict[str, Any]]:
    return [
        {
            "path": path.relative_to(ROOT).as_posix(),
            "sha256": sha256_file(path),
            "bytes": path.stat().st_size,
            "mode": mode_of(path),
        }
        for path in paths
    ]


def tree_hash(rows: List[Dict[str, Any]]) -> str:
    blob = "".join(
        "%s\0%s\0%s\0%s\n" % (row["path"], row["sha256"], row["bytes"], row["mode"]) for row in rows
    )
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="verify the formula, write nothing")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    previous = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    previous_rows = previous["files"]
    claimed = previous["payload_tree_sha256"]

    reproduced = tree_hash(previous_rows)
    formula_matches = reproduced == claimed

    current_rows = rows_for(payload_paths())
    added = sorted(
        set(row["path"] for row in current_rows) - set(row["path"] for row in previous_rows)
    )
    removed = sorted(
        set(row["path"] for row in previous_rows) - set(row["path"] for row in current_rows)
    )
    changed = sorted(
        row["path"]
        for row in current_rows
        if row["path"] in {r["path"] for r in previous_rows}
        and row["sha256"] != {r["path"]: r["sha256"] for r in previous_rows}[row["path"]]
    )
    payload_tree_sha256 = tree_hash(current_rows)

    report: Dict[str, Any] = {
        "schema_version": "solve-lite.public-manifest-refresh.v1",
        "tree_hash_formula": (previous.get("payload_tree_hash_algorithm") or "").strip(),
        "formula_reproduced": formula_matches,
        "previous_payload_tree_sha256": claimed,
        "reproduced_payload_tree_sha256": reproduced,
        "payload_file_count": len(current_rows),
        "new_files": added,
        "removed_files": removed,
        "changed_files": changed,
        "payload_tree_sha256": payload_tree_sha256,
        "written": False,
    }

    if not formula_matches:
        report["status"] = "REFUSED_FORMULA_NOT_REPRODUCED"
        print(json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False))
        return 2

    if args.check:
        report["status"] = "VERIFIED_NO_WRITE"
        print(json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False) if args.json
              else "FORMULA_REPRODUCED=PASS payload_files=%d" % len(current_rows))
        return 0

    stamp = time.strftime("%Y%m%d%H%M%S", time.localtime())
    evidence_dir = os.environ.get("SOLVE_LITE_P1_EVIDENCE")
    if evidence_dir:
        target = Path(evidence_dir)
        target.mkdir(parents=True, exist_ok=True)
        shutil.copy2(MANIFEST_PATH, target / ("PUBLIC_REPO_MANIFEST.json.bak-%s" % stamp))
        shutil.copy2(CHECKSUMS_PATH, target / ("SHA256SUMS.txt.bak-%s" % stamp))

    document = {key: value for key, value in previous.items() if key != "files"}
    document["files"] = current_rows
    document["payload_file_count"] = len(current_rows)
    document["payload_tree_sha256"] = payload_tree_sha256
    MANIFEST_PATH.write_text(
        json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    manifest_digest = sha256_file(MANIFEST_PATH)
    lines = ["%s  %s" % (row["sha256"], row["path"]) for row in current_rows]
    lines.append("%s  %s" % (manifest_digest, MANIFEST_PATH.name))
    CHECKSUMS_PATH.write_text("".join(line + "\n" for line in lines), encoding="utf-8")

    report["written"] = True
    report["status"] = "REFRESHED"
    report["manifest_sha256"] = manifest_digest
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False))
    else:
        print("FORMULA_REPRODUCED=PASS")
        print("PAYLOAD_FILES=%d" % len(current_rows))
        print("NEW_FILES=%d CHANGED_FILES=%d REMOVED_FILES=%d" % (len(added), len(changed), len(removed)))
        print("PAYLOAD_TREE_SHA256=%s" % payload_tree_sha256)
        print("SHA256SUMS_LINES=%d" % len(lines))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
