#!/usr/bin/env bash
set -euo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV="$APP_DIR/venv"
PORT="${QUICKTRACK_PORT:-5107}"

export QUICKTRACK_DATA_DIR="${QUICKTRACK_DATA_DIR:-$APP_DIR/data}"
export PYTHONPATH="$APP_DIR:$(dirname "$APP_DIR"):${PYTHONPATH:-}"

cd "$APP_DIR"

if [[ ! -d "$VENV" ]]; then
  python3 -m venv "$VENV"
fi

"$VENV/bin/pip" install -q -r "$APP_DIR/requirements.txt"

exec "$VENV/bin/python" app.py --host "${QUICKTRACK_BIND:-0.0.0.0}" --port "$PORT"
