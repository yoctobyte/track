#!/bin/bash
set -euo pipefail

DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$DIR"

VENV="$DIR/venv"
PID_FILE="$DIR/.museumcontrol.pid"
PORT="$(python3 -c "import json; print(json.load(open('config.json')).get('port', 4575))" 2>/dev/null || echo 4575)"

cleanup() {
    if [ -f "$PID_FILE" ]; then
        while IFS= read -r PID; do
            if [ -n "$PID" ] && kill -0 "$PID" 2>/dev/null; then
                kill "$PID" 2>/dev/null || true
            fi
        done < "$PID_FILE"
        rm -f "$PID_FILE"
    fi
}

trap cleanup INT TERM EXIT

if [ -f "$PID_FILE" ]; then
    while IFS= read -r OLD_PID; do
        if [ -n "$OLD_PID" ] && kill -0 "$OLD_PID" 2>/dev/null; then
            echo "Stopping existing Museum Control app (PID $OLD_PID)..."
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

echo "Checking requirements..."
"$VENV/bin/pip" install -q -r requirements.txt

export FLASK_APP=run.py
export FLASK_ENV=production
if [ ! -f ".secret_key" ]; then
    echo "museum-kiosk-secret-key-$(date +%s)-$(openssl rand -hex 12)" > .secret_key
fi
export SECRET_KEY="$(cat .secret_key)"

echo "Starting Museum Kiosk Control app on port $PORT..."
"$VENV/bin/python" run.py > app.log 2>&1 &
PID=$!
echo "$PID" > "$PID_FILE"

echo "Application started with PID $PID. Logs can be found in app.log."
wait "$PID"
