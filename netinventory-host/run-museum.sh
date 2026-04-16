#!/bin/bash
set -euo pipefail

DIR="$(cd "$(dirname "$0")" && pwd)"
export NETINVENTORY_HOST_INSTANCE=museum
export NETINVENTORY_HOST_PORT="${NETINVENTORY_HOST_PORT:-8891}"
export NETINVENTORY_HOST_DATA_DIR="${NETINVENTORY_HOST_DATA_DIR:-$DIR/data/environments/museum}"
exec "$DIR/run.sh"
