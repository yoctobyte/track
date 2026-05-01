#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CLIENT_DIR="$ROOT_DIR/netinventory-client"

HOST="${NETINVENTORY_UI_HOST:-127.0.0.1}"
PORT="${NETINVENTORY_UI_PORT:-8889}"
TRACK_BASE_URL="${TRACK_BASE_URL:-}"
TRACK_GITHUB_REPO="${TRACK_GITHUB_REPO:-git@github.com:yoctobyte/track.git}"
LOCAL_URL="http://$HOST:$PORT/"

export NETINVENTORY_UI_HOST="$HOST"
export NETINVENTORY_UI_PORT="$PORT"
export TRACK_BASE_URL
export TRACK_GITHUB_REPO
export NETINV_PUBLIC_PATH="${NETINV_PUBLIC_PATH:-/}"

if [ ! -x "$CLIENT_DIR/run-track.sh" ]; then
  echo "NetInventory Client launcher missing: $CLIENT_DIR/run-track.sh" >&2
  exit 1
fi

cat <<EOF
Starting standalone NetInventory Client.

Local UI:
  $LOCAL_URL

Repository used by generated bootstrap scripts:
  $TRACK_GITHUB_REPO

This does not start the TRACK umbrella app.
EOF

if [ -n "$TRACK_BASE_URL" ]; then
  cat <<EOF

Remote TRACK host for future sync/upload:
  $TRACK_BASE_URL
EOF
else
  cat <<EOF

Remote TRACK host for future sync/upload:
  not configured; set TRACK_BASE_URL when an admin provides one
EOF
fi

open_browser() {
  if [ "${NETINVENTORY_OPEN_BROWSER:-1}" = "0" ]; then
    return 0
  fi
  (
    sleep "${NETINVENTORY_BROWSER_DELAY:-2}"
    if command -v xdg-open >/dev/null 2>&1; then
      xdg-open "$LOCAL_URL" >/dev/null 2>&1 || true
    elif command -v sensible-browser >/dev/null 2>&1; then
      sensible-browser "$LOCAL_URL" >/dev/null 2>&1 || true
    elif command -v gio >/dev/null 2>&1; then
      gio open "$LOCAL_URL" >/dev/null 2>&1 || true
    fi
  ) &
}

open_browser
"$CLIENT_DIR/run-track.sh"
