#!/bin/bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT_DIR"

CONFIG_PATH="$ROOT_DIR/trackhub/config.json"
if [ ! -f "$CONFIG_PATH" ]; then
  CONFIG_PATH="$ROOT_DIR/trackhub/config.example.json"
fi

mapfile -t START_SCRIPTS < <(
  TRACKHUB_DIR="$ROOT_DIR/trackhub" python3 - <<'PY'
import os
import sys

sys.path.insert(0, os.environ["TRACKHUB_DIR"])
from config import load_config

config = load_config()

seen = set()
for env in config.get("environments", []):
    for app in env.get("apps", []):
        script = str(app.get("start_script", "")).strip()
        if not script or script in seen:
            continue
        seen.add(script)
        print(script)
PY
)

PIDS=()
MAIN_PID=""

cleanup() {
  for PID in "${PIDS[@]}"; do
    if [ -n "$PID" ] && kill -0 "$PID" 2>/dev/null; then
      kill "$PID" 2>/dev/null || true
    fi
  done
}

trap cleanup INT TERM EXIT

for script in "${START_SCRIPTS[@]}"; do
  if [ -z "$script" ]; then
    continue
  fi
  if [ ! -x "$ROOT_DIR/$script" ]; then
    echo "Skipping non-executable start script: $script"
    continue
  fi
  echo "Starting subservice: $script"
  "$ROOT_DIR/$script" >/dev/null 2>&1 &
  PIDS+=("$!")
  sleep 1
done

cd "$ROOT_DIR/trackhub"
./run.sh &
MAIN_PID="$!"
PIDS+=("$MAIN_PID")
wait "$MAIN_PID"
