#!/usr/bin/env python3
"""Launch the frozen adapter installer; dry-run unless --apply is explicit."""

from __future__ import annotations

import sys

from _dispatch import run


raise SystemExit(run("install", sys.argv[1:]))
