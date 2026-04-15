#!/bin/bash
set -euo pipefail

DIR="$(cd "$(dirname "$0")" && pwd)"

export MAP3D_INSTANCE="${MAP3D_INSTANCE:-lab}"
export MAP3D_PORT_HTTP="${MAP3D_PORT_HTTP:-5012}"
export MAP3D_PORT_HTTPS="${MAP3D_PORT_HTTPS:-5455}"
export MAP3D_DATA_DIR="${MAP3D_DATA_DIR:-$DIR/data/environments/lab}"

exec "$DIR/run.sh"
