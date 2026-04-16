#!/bin/bash
set -euo pipefail

DIR="$(cd "$(dirname "$0")" && pwd)"
export NETINVENTORY_HOST_INSTANCE=lab
export NETINVENTORY_HOST_PORT="${NETINVENTORY_HOST_PORT:-8892}"
export NETINVENTORY_HOST_DATA_DIR="${NETINVENTORY_HOST_DATA_DIR:-$DIR/data/environments/lab}"
exec "$DIR/run.sh"
