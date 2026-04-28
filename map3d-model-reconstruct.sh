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
  ./map3d-model-reconstruct.sh
  ./map3d-model-reconstruct.sh --environment museum --backend hyworld
  ./map3d-model-reconstruct.sh --environment museum --session 0001
  ./map3d-model-reconstruct.sh --environment museum --building waterlinie --location technische

Options:
  --environment NAME  Use map3d/data/environments/NAME as the data dir.
  --help              Show this help.

Everything else is forwarded to map3d/model_reconstruct.py.
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

"$PYTHON_BIN" "$MAP3D_DIR/model_reconstruct.py" "${ARGS[@]}"
