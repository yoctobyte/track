#!/bin/bash
set -euo pipefail

DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$DIR"

VENV="$DIR/venv"
INSTANCE="${DEVICECONTROL_INSTANCE:-default}"
PID_FILE="$DIR/.devicecontrol-${INSTANCE}.pid"
HOST="${DEVICECONTROL_HOST:-0.0.0.0}"
PORT="${DEVICECONTROL_PORT:-5021}"
ENVIRONMENT="${DEVICECONTROL_ENVIRONMENT:-testing}"
DATA_DIR="${DEVICECONTROL_DATA_DIR:-$DIR/data}"

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
            echo "Stopping existing DeviceControl app (PID $OLD_PID)..."
            kill "$OLD_PID"
        fi
    done < "$PID_FILE"
    sleep 1
    rm -f "$PID_FILE"
fi

fuser -k "$PORT/tcp" 2>/dev/null || true

if [ ! -d "$VENV" ]; then
    echo "Creating virtual environment..."
    python3 -m venv "$VENV"
fi

echo "Checking dependencies..."
"$VENV/bin/pip" install -q -r "$DIR/requirements.txt"

mkdir -p "$DATA_DIR/environments/$ENVIRONMENT/run_logs" "$DATA_DIR/environments/$ENVIRONMENT/screenshots"
if [ ! -f "$DATA_DIR/environments/$ENVIRONMENT/inventory.ini" ]; then
    cp "$DIR/data/environments/testing/inventory.ini" "$DATA_DIR/environments/$ENVIRONMENT/inventory.ini"
fi

export DEVICECONTROL_ENVIRONMENT="$ENVIRONMENT"
export DEVICECONTROL_DATA_DIR="$DATA_DIR"

echo "devicecontrol instance: $INSTANCE"
echo "devicecontrol environment: $ENVIRONMENT"
echo "devicecontrol data dir: $DATA_DIR"
echo "Starting DeviceControl on http://$HOST:$PORT/..."

rm -f "$PID_FILE"
"$VENV/bin/python" - <<'PY' &
import os

from app import create_app

create_app().run(
    debug=False,
    use_reloader=False,
    host=os.environ.get("DEVICECONTROL_HOST", "0.0.0.0"),
    port=int(os.environ.get("DEVICECONTROL_PORT", "5021")),
)
PY
PID=$!
echo "$PID" > "$PID_FILE"
wait "$PID"
