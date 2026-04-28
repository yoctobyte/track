#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
APP_DIR="$ROOT_DIR/tracksync"
VENV="$APP_DIR/venv"

if [[ ! -d "$VENV" ]]; then
  python3 -m venv "$VENV"
fi

"$VENV/bin/pip" install -q -r "$APP_DIR/requirements.txt"

python3 -m json.tool "$ROOT_DIR/trackhub/config.json" >/dev/null
python3 -m py_compile "$ROOT_DIR/trackhub/config.py" "$APP_DIR/app.py" "$APP_DIR/sync_core.py"
bash -n "$APP_DIR/run.sh"

git -C "$ROOT_DIR" check-ignore -q tracksync/data/config.json
git -C "$ROOT_DIR" check-ignore -q tracksync/venv/pyvenv.cfg
git -C "$ROOT_DIR" check-ignore -q tracksync/.tracksync.pid
! git -C "$ROOT_DIR" check-ignore -q tracksync/app.py
! git -C "$ROOT_DIR" check-ignore -q tracksync/sync_core.py
! git -C "$ROOT_DIR" check-ignore -q tracksync/templates/index.html
[[ -z "$(git -C "$ROOT_DIR" ls-files tracksync/data/config.json tracksync/venv/pyvenv.cfg tracksync/.tracksync.pid)" ]]

PYTHONPATH="$APP_DIR" "$VENV/bin/python" "$APP_DIR/tests_local.py"

echo "tracksync local tests passed"
