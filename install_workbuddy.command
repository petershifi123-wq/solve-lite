#!/bin/bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
/usr/bin/python3 "$ROOT/tools/installer.py" --host workbuddy
/usr/bin/python3 "$ROOT/tools/startup_check.py" --root "$ROOT" --json
echo "FINAL_INSTALL_STATUS=PASS"
