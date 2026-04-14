#!/bin/bash
set -e

DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$DIR"

VENV="$DIR/venv"
PID_FILE="$DIR/.trackhub.pid"
PORT="$(python3 - <<'PY'
from config import load_config
print(load_config().get("port", 4600))
PY
)"

if [ -f "$PID_FILE" ]; then
  while IFS= read -r OLD_PID; do
    if [ -n "$OLD_PID" ] && kill -0 "$OLD_PID" 2>/dev/null; then
      echo "Stopping existing TRACK hub (PID $OLD_PID)..."
      kill "$OLD_PID"
    fi
  done < "$PID_FILE"
  rm -f "$PID_FILE"
fi

fuser -k "$PORT/tcp" 2>/dev/null || true

if [ ! -d "$VENV" ]; then
  echo "Creating virtual environment..."
  python3 -m venv "$VENV"
fi

echo "Checking dependencies..."
"$VENV/bin/pip" install -q -r requirements.txt

echo "Starting TRACK hub on port $PORT..."
"$VENV/bin/python" run.py &
echo $! > "$PID_FILE"

echo "TRACK hub running: http://127.0.0.1:$PORT/"
wait
