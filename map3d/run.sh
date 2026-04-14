#!/bin/bash
# Launch map3d Flask app
# Auto-creates venv if missing, kills any existing instance, starts fresh

set -e

DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$DIR"

VENV="$DIR/venv"
PID_FILE="$DIR/.map3d.pid"
HOST="${MAP3D_HOST:-0.0.0.0}"
HTTP_PORT="${MAP3D_PORT_HTTP:-5001}"
HTTPS_PORT="${MAP3D_PORT_HTTPS:-5444}"
ENABLE_HTTP="${MAP3D_ENABLE_HTTP:-1}"
ENABLE_HTTPS="${MAP3D_ENABLE_HTTPS:-1}"

if [ "$ENABLE_HTTP" = "0" ] && [ "$ENABLE_HTTPS" = "0" ]; then
    echo "Nothing to start: both MAP3D_ENABLE_HTTP and MAP3D_ENABLE_HTTPS are 0."
    exit 1
fi

# Kill existing instance
if [ -f "$PID_FILE" ]; then
    while IFS= read -r OLD_PID; do
        if [ -n "$OLD_PID" ] && kill -0 "$OLD_PID" 2>/dev/null; then
            echo "Stopping existing map3d (PID $OLD_PID)..."
            kill "$OLD_PID"
        fi
    done < "$PID_FILE"
    sleep 1
    rm -f "$PID_FILE"
fi

# Also kill anything on our ports
if [ "$ENABLE_HTTP" != "0" ]; then
    fuser -k "$HTTP_PORT/tcp" 2>/dev/null || true
fi
if [ "$ENABLE_HTTPS" != "0" ]; then
    fuser -k "$HTTPS_PORT/tcp" 2>/dev/null || true
fi

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

if [ -z "${MAP3D_PASSWORD:-}" ]; then
    echo "MAP3D_PASSWORD not set; using default dev password: map3d__ok!aY3"
fi

start_server() {
    local port="$1"
    local ssl_mode="$2"
    "$VENV/bin/python" -c "
from app import create_app
create_app().run(
    debug=False,
    use_reloader=False,
    port=$port,
    host='$HOST',
    ssl_context=$ssl_mode,
)
" &
    echo $! >> "$PID_FILE"
}

rm -f "$PID_FILE"

if [ "$ENABLE_HTTP" != "0" ]; then
    echo "Starting HTTP on http://$HOST:$HTTP_PORT..."
    start_server "$HTTP_PORT" "None"
fi

if [ "$ENABLE_HTTPS" != "0" ]; then
    echo "Starting HTTPS on https://$HOST:$HTTPS_PORT..."
    start_server "$HTTPS_PORT" "'adhoc'"
    echo "If your phone warns about the certificate, accept the local dev certificate to proceed."
fi

echo "map3d running"
if [ "$ENABLE_HTTP" != "0" ]; then
    echo "HTTP:  http://$HOST:$HTTP_PORT/"
fi
if [ "$ENABLE_HTTPS" != "0" ]; then
    echo "HTTPS: https://$HOST:$HTTPS_PORT/"
fi

# Wait for the server process so ctrl-c works
wait
rm -f "$PID_FILE"
