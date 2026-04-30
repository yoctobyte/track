#!/bin/bash
set -euo pipefail

DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$DIR"

VENV="$DIR/venv"
PID_FILE="$DIR/.netinventory-host.pid"
HOST="${NETINVENTORY_HOST_BIND:-127.0.0.1}"
PORT="${NETINVENTORY_HOST_PORT:-8888}"

cleanup() {
  if [ -f "$PID_FILE" ]; then
    while IFS= read -r OLD_PID; do
      if [ -n "$OLD_PID" ] && kill -0 "$OLD_PID" 2>/dev/null; then
        kill "$OLD_PID" 2>/dev/null || true
      fi
    done < "$PID_FILE"
    rm -f "$PID_FILE"
  fi
}

trap cleanup INT TERM EXIT

if [ -f "$PID_FILE" ]; then
  while IFS= read -r OLD_PID; do
    if [ -n "$OLD_PID" ] && kill -0 "$OLD_PID" 2>/dev/null; then
      echo "Stopping existing NetInventory Host app (PID $OLD_PID)..."
      kill "$OLD_PID"
    fi
  done < "$PID_FILE"
  rm -f "$PID_FILE"
fi

echo "Killing any existing instance on port $PORT..."
fuser -k "$PORT/tcp" 2>/dev/null || true

if [ ! -d "$VENV" ]; then
  echo "Creating virtual environment..."
  python3 -m venv "$VENV"
fi

echo "Checking NetInventory Host requirements..."
"$VENV/bin/pip" install -q -r requirements.txt

export PYTHONPATH="$DIR/..:${PYTHONPATH:-}"
export NETINVENTORY_HOST_BIND="$HOST"
export NETINVENTORY_HOST_PORT="$PORT"

echo "Starting NetInventory Host on http://$HOST:$PORT/..."
"$VENV/bin/python" run.py > app.log 2>&1 &
PID=$!
echo "$PID" > "$PID_FILE"
echo "NetInventory Host started with PID $PID. Logs: app.log"
wait "$PID"
