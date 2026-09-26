#!/usr/bin/env python3
"""Launch the frozen rollback-wrapped adapter uninstaller."""

from __future__ import annotations

import sys

from _dispatch import run


raise SystemExit(run("uninstall", sys.argv[1:]))
