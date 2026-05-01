#!/bin/bash
set -euo pipefail

cd "$(dirname "$0")"
ROOT_DIR="$(cd .. && pwd)"
PYTHON="${PYTHON:-python3}"
if [ -x "venv/bin/python" ]; then
  PYTHON="venv/bin/python"
fi

PYTHONPATH="$ROOT_DIR:${PYTHONPATH:-}" "$PYTHON" tests_local.py
