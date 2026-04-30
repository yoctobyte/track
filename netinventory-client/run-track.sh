#!/bin/bash
set -euo pipefail

DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$DIR"

VENV="$DIR/venv"
HOST="${NETINVENTORY_UI_HOST:-127.0.0.1}"
PORT="${NETINVENTORY_UI_PORT:-8889}"
PID_FILE="$DIR/.netinventory-ui.pid"
BACKGROUND="${NETINVENTORY_BACKGROUND:-0}"
SKIP_SUDO="${NETINVENTORY_SKIP_SUDO:-0}"

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

# Standalone client wants root for Wi-Fi scans, full ARP, link-state changes,
# raw packet captures. We don't run the whole UI as root (that would mess up
# file ownership in $HOME). Instead we cache sudo credentials so the python
# process can shell out to `sudo -n iw scan` etc. without re-prompting.
if [ "$SKIP_SUDO" != "1" ] && [ "$EUID" -ne 0 ]; then
  if command -v sudo >/dev/null 2>&1; then
    echo
    echo "NetInventory needs root for full Wi-Fi scans, ARP discovery, and"
    echo "raw network probes. Caching sudo credentials..."
    echo "(set NETINVENTORY_SKIP_SUDO=1 to skip; client still works unprivileged.)"
    if ! sudo -v; then
      echo "Continuing without elevated privileges. Some features (Wi-Fi scan,"
      echo "full ARP) will be unavailable."
    else
      # Keep the sudo timestamp warm in the background while the UI runs.
      ( while kill -0 "$$" 2>/dev/null; do sudo -n -v 2>/dev/null || true; sleep 60; done ) &
      SUDO_KEEPALIVE_PID=$!
      trap '[ -n "${SUDO_KEEPALIVE_PID:-}" ] && kill "$SUDO_KEEPALIVE_PID" 2>/dev/null || true' EXIT
    fi
  else
    echo "sudo not available; running unprivileged. Wi-Fi scan and full ARP disabled."
  fi
fi

export NETINV_PUBLIC_PATH="${NETINV_PUBLIC_PATH:-/}"

echo "Starting NetInventory client hub on http://$HOST:$PORT/..."
if [ "$BACKGROUND" = "1" ]; then
  if command -v setsid >/dev/null 2>&1; then
    NETINV_UI_BIND="$HOST:$PORT" setsid "$VENV/bin/netinv" hub-web > netinventory-ui.log 2>&1 < /dev/null &
  else
    NETINV_UI_BIND="$HOST:$PORT" nohup "$VENV/bin/netinv" hub-web > netinventory-ui.log 2>&1 < /dev/null &
  fi
  PID=$!
  echo "$PID" > "$PID_FILE"
  echo "NetInventory client hub started with PID $PID. Logs: netinventory-ui.log"
else
  rm -f "$PID_FILE"
  exec env NETINV_UI_BIND="$HOST:$PORT" "$VENV/bin/netinv" hub-web
fi
