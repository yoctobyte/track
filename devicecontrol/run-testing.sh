#!/bin/bash
set -euo pipefail

DIR="$(cd "$(dirname "$0")" && pwd)"
export DEVICECONTROL_INSTANCE=testing
export DEVICECONTROL_ENVIRONMENT=testing
export DEVICECONTROL_PORT="${DEVICECONTROL_PORT:-5021}"
export DEVICECONTROL_DATA_DIR="${DEVICECONTROL_DATA_DIR:-$DIR/data}"
exec "$DIR/run.sh"
