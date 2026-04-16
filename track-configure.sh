#!/bin/bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")" && pwd)"
exec python3 "$ROOT_DIR/track-configure.py" "$@"
