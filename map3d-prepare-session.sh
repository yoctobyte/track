#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MAP3D_DIR="$ROOT_DIR/map3d"
DEFAULT_DATA_DIR="$MAP3D_DIR/data"
DATA_DIR="${MAP3D_DATA_DIR:-$DEFAULT_DATA_DIR}"
ENV_NAME=""
ARGS=()

usage() {
  cat <<'EOF'
Usage:
  ./map3d-prepare-session.sh
  ./map3d-prepare-session.sh --environment museum
  ./map3d-prepare-session.sh --environment museum --building ij --location patch
  ./map3d-prepare-session.sh --session 0123
  ./map3d-prepare-session.sh --tag burst

Options:
  --environment NAME   Use map3d/data/environments/NAME as the data dir.
  --session ID         Prepare one specific session.
  --building TEXT      Filter by building name fragment.
  --location TEXT      Filter by location name fragment.
  --tag TEXT           Filter by tag fragment.
  --list               List matching jobs instead of preparing them.
  --name NAME          Output reconstruction-set name.
  --force              Replace existing prepared set and extracted frames.
  --candidate-fps N    Override candidate extraction fps.
  --target-fps N       Override selected kept fps target.
  --help               Show this help.
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --environment|--env)
      ENV_NAME="${2:-}"
      shift 2
      ;;
    --help|-h)
      usage
      exit 0
      ;;
    *)
      ARGS+=("$1")
      shift
      ;;
  esac
done

if [[ -n "$ENV_NAME" ]]; then
  DATA_DIR="$MAP3D_DIR/data/environments/$ENV_NAME"
fi

export MAP3D_DATA_DIR="$(realpath -m "$DATA_DIR")"

PYTHON_BIN="$MAP3D_DIR/venv/bin/python"
if [[ ! -x "$PYTHON_BIN" ]]; then
  PYTHON_BIN="python3"
fi

"$PYTHON_BIN" "$MAP3D_DIR/prepare_session.py" "${ARGS[@]}"
