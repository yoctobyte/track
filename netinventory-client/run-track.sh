#!/bin/bash
set -euo pipefail

DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$DIR"

VENV="$DIR/venv"
HOST="${NETINVENTORY_UI_HOST:-127.0.0.1}"
PORT="${NETINVENTORY_UI_PORT:-8889}"
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

if [ ! -x "$VENV/bin/python" ] || [ ! -x "$VENV/bin/pip" ] || ! "$VENV/bin/python" -m pip --version >/dev/null 2>&1; then
  if [ -d "$VENV" ]; then
    echo "Recreating broken NetInventory virtual environment..."
    rm -rf "$VENV"
  fi
  echo "Creating virtual environment..."
  python3 -m venv "$VENV"
fi

echo "Checking NetInventory dependencies..."
"$VENV/bin/python" -m pip install -q -e .

export NETINV_PUBLIC_PATH="${NETINV_PUBLIC_PATH:-/netinventory-client/}"

echo "Starting NetInventory client hub on http://$HOST:$PORT/..."
if command -v setsid >/dev/null 2>&1; then
  NETINV_UI_BIND="$HOST:$PORT" setsid "$VENV/bin/netinv" hub-web > netinventory-ui.log 2>&1 < /dev/null &
else
  NETINV_UI_BIND="$HOST:$PORT" nohup "$VENV/bin/netinv" hub-web > netinventory-ui.log 2>&1 < /dev/null &
fi
PID=$!
echo "$PID" > "$PID_FILE"
echo "NetInventory client hub started with PID $PID. Logs: netinventory-ui.log"
