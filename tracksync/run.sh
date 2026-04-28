#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
APP_DIR="$ROOT_DIR/tracksync"
VENV="$APP_DIR/venv"
PORT="${TRACKSYNC_PORT:-5099}"

export TRACKSYNC_DATA_DIR="${TRACKSYNC_DATA_DIR:-$APP_DIR/data}"
export PYTHONPATH="$APP_DIR:${PYTHONPATH:-}"

cd "$APP_DIR"

if [[ ! -d "$VENV" ]]; then
  python3 -m venv "$VENV"
fi

"$VENV/bin/pip" install -q -r "$APP_DIR/requirements.txt"

exec "$VENV/bin/python" app.py --host "${TRACKSYNC_BIND:-0.0.0.0}" --port "$PORT"
