#!/bin/bash
set -euo pipefail

DIR="$(cd "$(dirname "$0")" && pwd)"
export DEVICECONTROL_INSTANCE=lab
export DEVICECONTROL_ENVIRONMENT=lab
export DEVICECONTROL_PORT="${DEVICECONTROL_PORT:-5032}"
export DEVICECONTROL_DATA_DIR="${DEVICECONTROL_DATA_DIR:-$DIR/data}"
exec "$DIR/run.sh"
