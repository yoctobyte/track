#!/bin/bash

# NetInventory Hybrid Launcher
# Phase 2 - Go (Collector) + Python (UI/Analysis)

set -e

# Configuration
UI_PORT=8888
SNAP_DIR="data/snapshots"

# 0. Cleanup existing instances
echo ">>> cleaning up old instances..."
pkill -f "./netinv" || true
pkill -f "python3 ui/app.py" || true

# 1. Setup Python Virtual Environment
if [ ! -d "venv" ]; then
    echo ">>> Creating virtual environment..."
    python3 -m venv venv
fi
source venv/bin/activate
pip install Flask > /dev/null 2>&1

# 2. Build Go Engine
echo ">>> Building Go Engine..."
go build -o netinv ./cmd/netinv/main.go

# 3. Set Capabilities (Auto-sudo)
echo ">>> Please enter sudo password to grant network capabilities:"
sudo setcap cap_net_raw,cap_net_admin=eip ./netinv

# 4. Handle cleanup on exit
cleanup() {
    echo -e "\n>>> Shutting down..."
    kill $GO_PID $PY_PID 2>/dev/null
    exit 0
}
trap cleanup SIGINT SIGTERM

# 5. Start Go Engine in background
echo ">>> Starting Go Engine (data collector) -> netinv.log..."
./netinv > netinv.log 2>&1 &
GO_PID=$!

# 6. Start Python UI
echo ">>> Starting Python Flask UI on port $UI_PORT..."
python3 ui/app.py &
PY_PID=$!

echo -e "\n>>> \033[1;32mNetInventory is running!\033[0m"
echo -e ">>> UI URL: \033[1;34mhttp://localhost:$UI_PORT\033[0m"
echo ">>> Press Ctrl+C to stop both processes."

# Wait for background processes
wait
