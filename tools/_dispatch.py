#!/usr/bin/env python3
"""Dispatch a lifecycle command to the frozen Solve Lite adapter."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

COMMAND_CAPABILITIES = {"doctor": (None, ()), "install": ("--apply", ("--dry-run",)), "uninstall": (None, ())}


def run(command: str, arguments: list[str]) -> int:
    root = Path(__file__).resolve().parents[1]
    adapter = root / "plugins" / "solve-lite" / "scripts" / "codex_desktop_adapter.py"
    if not adapter.is_file():
        raise SystemExit("PACKAGE_ADAPTER_MISSING")
    strip_flag, default_arguments = COMMAND_CAPABILITIES.get(command, (None, ()))
    disable_defaults = strip_flag in arguments
    arguments = [value for value in arguments if value != strip_flag]
    arguments.extend(value for value in (() if disable_defaults else default_arguments) if value not in arguments)
    return subprocess.call([sys.executable, str(adapter), command, *arguments])
