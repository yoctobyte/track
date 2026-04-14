#!/bin/bash
set -euo pipefail

DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$DIR"

VENV="$DIR/venv"
HOST="${NETINVENTORY_UI_HOST:-127.0.0.1}"
PORT="${NETINVENTORY_UI_PORT:-8888}"
PID_FILE="$DIR/.netinventory-ui.pid"

echo "Stopping any existing NetInventory hub on port $PORT..."
fuser -k "$PORT/tcp" 2>/dev/null || true

if [ -f "$PID_FILE" ]; then
  while IFS= read -r OLD_PID; do
    if [ -n "$OLD_PID" ] && kill -0 "$OLD_PID" 2>/dev/null; then
      kill "$OLD_PID" 2>/dev/null || true
    fi
  done < "$PID_FILE"
  rm -f "$PID_FILE"
fi

if [ ! -d "$VENV" ]; then
  echo "Creating virtual environment..."
  python3 -m venv "$VENV"
fi

echo "Checking NetInventory dependencies..."
"$VENV/bin/pip" install -q -e .

echo "Starting NetInventory hub on http://$HOST:$PORT/..."
NETINV_UI_BIND="$HOST:$PORT" nohup "$VENV/bin/netinv" hub-web > netinventory-ui.log 2>&1 &
PID=$!
echo "$PID" > "$PID_FILE"
echo "NetInventory hub started with PID $PID. Logs: netinventory-ui.log"
