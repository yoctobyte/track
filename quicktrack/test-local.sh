#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
APP_DIR="$ROOT_DIR/quicktrack"
VENV="$APP_DIR/venv"

if [[ ! -d "$VENV" ]]; then
  python3 -m venv "$VENV"
fi

"$VENV/bin/pip" install -q -r "$APP_DIR/requirements.txt"

python3 -m py_compile "$APP_DIR/app.py"
bash -n "$APP_DIR/run.sh"

git -C "$ROOT_DIR" check-ignore -q quicktrack/data/records/example.json
git -C "$ROOT_DIR" check-ignore -q quicktrack/data/photos/example.jpg
git -C "$ROOT_DIR" check-ignore -q quicktrack/venv/pyvenv.cfg
git -C "$ROOT_DIR" check-ignore -q quicktrack/data/.quicktrack-secret-key
! git -C "$ROOT_DIR" check-ignore -q quicktrack/app.py
! git -C "$ROOT_DIR" check-ignore -q quicktrack/templates/index.html

PYTHONPATH="$APP_DIR" "$VENV/bin/python" "$APP_DIR/tests_local.py"

echo "quicktrack local tests passed"
