"""Process / footprint metering used by the DLC gates (no third-party deps)."""

from __future__ import annotations

import os
from pathlib import Path


def open_fds_to(target: "Path | str") -> int:
    """Count this process' open file descriptors pointing inside ``target``."""
    import os
    from pathlib import Path as _Path

    root = str(_Path(target).resolve())
    count = 0
    for entry in os.listdir("/dev/fd"):
        try:
            resolved = os.path.realpath(f"/dev/fd/{entry}")
        except OSError:
            continue
        if resolved.startswith(root):
            count += 1
    return count


def rss_bytes(pid: int | None = None) -> int:
    """Resident set size of a process in bytes (``ps`` on macOS/Linux)."""
    import subprocess

    target = str(pid if pid is not None else os.getpid())
    out = subprocess.run(
        ["ps", "-o", "rss=", "-p", target],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    return int(out.split()[0]) * 1024


def peak_rss_bytes() -> int:
    """High-water RSS of this process in bytes (macOS reports bytes, Linux KiB)."""
    import resource
    import sys

    value = int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    return value if sys.platform == "darwin" else value * 1024


def fd_paths() -> list[str]:
    """Open file descriptors of this process as resolved paths (macOS/Linux)."""
    resolved = []
    for name in os.listdir("/dev/fd"):
        try:
            resolved.append(os.path.realpath(f"/dev/fd/{name}"))
        except OSError:
            continue
    return resolved


def open_fds_for(path: Path | str) -> int:
    """How many descriptors of this process point at ``path``."""
    target = os.path.realpath(str(path))
    return sum(1 for item in fd_paths() if item == target)


def dir_bytes(path: Path | str) -> int:
    total = 0
    for item in Path(path).rglob("*"):
        if item.is_file() and not item.is_symlink():
            total += item.stat().st_size
    return total


def mb(value: int) -> float:
    return round(value / (1024 * 1024), 2)
