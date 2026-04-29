#!/bin/bash
set -euo pipefail

cd "$(dirname "$0")"
PYTHON="${PYTHON:-python3}"
if [ -x "venv/bin/python" ]; then
  PYTHON="venv/bin/python"
fi

"$PYTHON" tests_local.py
