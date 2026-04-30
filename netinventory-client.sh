#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CLIENT_DIR="$ROOT_DIR/netinventory-client"

HOST="${NETINVENTORY_UI_HOST:-127.0.0.1}"
PORT="${NETINVENTORY_UI_PORT:-8889}"
TRACK_BASE_URL="${TRACK_BASE_URL:-https://track.praktijkpioniers.com}"

export NETINVENTORY_UI_HOST="$HOST"
export NETINVENTORY_UI_PORT="$PORT"
export TRACK_BASE_URL
export NETINV_PUBLIC_PATH="${NETINV_PUBLIC_PATH:-/}"

if [ ! -x "$CLIENT_DIR/run-track.sh" ]; then
  echo "NetInventory Client launcher missing: $CLIENT_DIR/run-track.sh" >&2
  exit 1
fi

cat <<EOF
Starting standalone NetInventory Client.

Local UI:
  http://$HOST:$PORT/

Remote TRACK host for future sync/upload:
  $TRACK_BASE_URL

This does not start the TRACK umbrella app.
EOF

"$CLIENT_DIR/run-track.sh"
