#!/usr/bin/env python3
"""Host/adapter lifecycle for the Codex Desktop plugin (install, doctor, uninstall).

The asset side of the install lives in tools/installer.py (Lite base + DLC
components); this wrapper only drives the frozen desktop adapter.

  python3 tools/adapter.py doctor
  python3 tools/adapter.py install --dry-run
  python3 tools/adapter.py install --apply
  python3 tools/adapter.py uninstall --yes
"""

from __future__ import annotations

import sys

from _dispatch import run

COMMANDS = {"doctor", "install", "uninstall"}


def main() -> int:
    if len(sys.argv) < 2 or sys.argv[1] not in COMMANDS:
        print(__doc__)
        return 2
    return run(sys.argv[1], sys.argv[2:])


if __name__ == "__main__":
    raise SystemExit(main())
