#!/bin/bash
set -euo pipefail

DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$DIR"

VENV="$DIR/venv"
PORT="${NETINVENTORY_UI_PORT:-8888}"
HOST="${NETINVENTORY_UI_HOST:-127.0.0.1}"

echo "Killing any existing NetInventory UI on port $PORT..."
fuser -k "$PORT/tcp" 2>/dev/null || true

if [ ! -d "$VENV" ]; then
  echo "Creating virtual environment..."
  python3 -m venv "$VENV"
fi

echo "Checking NetInventory UI dependencies..."
"$VENV/bin/pip" install -q Flask

echo "Starting NetInventory UI on http://$HOST:$PORT/..."
nohup "$VENV/bin/python" -c "
import pathlib
import sys

root = pathlib.Path('$DIR')
sys.path.insert(0, str(root / 'ui'))
from app import app
app.run(host='$HOST', port=$PORT, debug=False)
" > netinventory-ui.log 2>&1 &

PID=$!
echo "NetInventory UI started with PID $PID. Logs: netinventory-ui.log"
