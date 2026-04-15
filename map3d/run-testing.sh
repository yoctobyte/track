#!/bin/bash
set -euo pipefail

DIR="$(cd "$(dirname "$0")" && pwd)"

export MAP3D_INSTANCE="${MAP3D_INSTANCE:-testing}"
export MAP3D_PORT_HTTP="${MAP3D_PORT_HTTP:-5001}"
export MAP3D_PORT_HTTPS="${MAP3D_PORT_HTTPS:-5444}"

exec "$DIR/run.sh"
