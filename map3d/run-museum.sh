#!/bin/bash
set -euo pipefail

DIR="$(cd "$(dirname "$0")" && pwd)"

export MAP3D_INSTANCE="${MAP3D_INSTANCE:-museum}"
export MAP3D_PORT_HTTP="${MAP3D_PORT_HTTP:-5011}"
export MAP3D_PORT_HTTPS="${MAP3D_PORT_HTTPS:-5454}"
export MAP3D_DATA_DIR="${MAP3D_DATA_DIR:-$DIR/data/environments/museum}"

exec "$DIR/run.sh"
