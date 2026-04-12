#!/bin/bash
# Launch map3d Flask app
# Auto-creates venv if missing, kills any existing instance, starts fresh

set -e

DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$DIR"

VENV="$DIR/venv"
PID_FILE="$DIR/.map3d.pid"
PORT="${MAP3D_PORT:-5000}"
HOST="${MAP3D_HOST:-0.0.0.0}"

# Kill existing instance
if [ -f "$PID_FILE" ]; then
    OLD_PID=$(cat "$PID_FILE")
    if kill -0 "$OLD_PID" 2>/dev/null; then
        echo "Stopping existing map3d (PID $OLD_PID)..."
        kill "$OLD_PID"
        sleep 1
    fi
    rm -f "$PID_FILE"
fi

# Also kill anything on our port
fuser -k "$PORT/tcp" 2>/dev/null || true

# Create venv if missing
if [ ! -d "$VENV" ]; then
    echo "Creating virtual environment..."
    python3 -m venv "$VENV"
fi

# Install/update dependencies
echo "Checking dependencies..."
"$VENV/bin/pip" install -q -r "$DIR/requirements.txt"

# Ensure data directories exist
mkdir -p "$DIR/data/originals" "$DIR/data/previews" "$DIR/data/extracted_frames"
mkdir -p "$DIR/data/derived/features" "$DIR/data/derived/matches" "$DIR/data/derived/reconstructions"

echo "Starting map3d on $HOST:$PORT..."
"$VENV/bin/python" -c "
from app import create_app
create_app().run(debug=True, port=$PORT, host='$HOST')
" &

echo $! > "$PID_FILE"
echo "map3d running (PID $!, port $PORT)"
echo "http://$HOST:$PORT/"

# Wait for the server process so ctrl-c works
wait
rm -f "$PID_FILE"
