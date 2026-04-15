#!/bin/bash
set -euo pipefail

DIR="$(cd "$(dirname "$0")" && pwd)"
export DEVICECONTROL_INSTANCE=museum
export DEVICECONTROL_ENVIRONMENT=museum
export DEVICECONTROL_PORT="${DEVICECONTROL_PORT:-5031}"
export DEVICECONTROL_DATA_DIR="${DEVICECONTROL_DATA_DIR:-$DIR/data}"
exec "$DIR/run.sh"
