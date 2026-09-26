#!/usr/bin/env python3
"""Launch the frozen adapter doctor without changing its status semantics."""

from __future__ import annotations

import sys

from _dispatch import run


raise SystemExit(run("doctor", sys.argv[1:]))
