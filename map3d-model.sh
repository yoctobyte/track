#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MAP3D_DIR="$ROOT_DIR/map3d"
ENV_FILE="$MAP3D_DIR/model-backends.env"
EXAMPLE_ENV_FILE="$MAP3D_DIR/model-backends.example.env"
PREPARE_SCRIPT="$ROOT_DIR/map3d-model-reconstruct.sh"

usage() {
  cat <<'EOF'
Usage:
  ./map3d-model.sh install --backend hyworld [options]
  ./map3d-model.sh prepare --backend hyworld --environment museum --session 0001
  ./map3d-model.sh run --backend hyworld --environment museum --session 0001
  ./map3d-model.sh all --backend hyworld --environment museum --session 0001
  ./map3d-model.sh status --environment museum --session 0001

Subcommands:
  install   Clone/configure a backend locally and record paths in map3d/model-backends.env
  prepare   Create the experimental backend workspace inside TRACK
  run       Execute the prepared backend workspace
  all       Prepare then run
  status    Show backend config and prepared workspaces

Global options:
  --backend NAME       hyworld or lyra
  --environment NAME   Use map3d/data/environments/NAME as the data dir
  --session ID         Session id to target
  --building TEXT      Filter by building fragment (prepare/all)
  --location TEXT      Filter by location fragment (prepare/all)
  --tag TEXT           Filter by tag fragment (prepare/all)
  --force              Replace existing prepared workspace / rerun where supported

Install options:
  --repo-dir DIR       Target checkout dir (default under external-models/)
  --python BIN         Python binary to use for venv creation
  --skip-torch         Skip torch installation
  --skip-flash-attn    Skip flash-attn installation
  --skip-requirements  Skip requirements.txt installation
  --small-vram         Use safer HY-World defaults for low-VRAM GPUs when preparing/running

Notes:
  - HY-World is fully wired.
  - Lyra install/run is not automated yet; install prepares config only.
EOF
}

die() {
  printf 'ERROR: %s\n' "$*" >&2
  exit 1
}

log() {
  printf '[model] %s\n' "$*"
}

python_version_string() {
  local py_bin="$1"
  "$py_bin" - <<'PY'
import sys
print(f"{sys.version_info.major}.{sys.version_info.minor}")
PY
}

pick_default_python() {
  local backend="$1"
  if [[ "$backend" == "hyworld" ]] && command -v python3.10 >/dev/null 2>&1; then
    printf 'python3.10\n'
  else
    printf 'python3\n'
  fi
}

ensure_env_file() {
  if [[ ! -f "$ENV_FILE" ]]; then
    cp "$EXAMPLE_ENV_FILE" "$ENV_FILE"
    log "Created $ENV_FILE from example."
  fi
}

load_env() {
  if [[ -f "$ENV_FILE" ]]; then
    # shellcheck disable=SC1090
    source "$ENV_FILE"
  fi
}

set_env_var() {
  local key="$1"
  local value="$2"
  ensure_env_file
  if grep -q "^${key}=" "$ENV_FILE"; then
    python3 - "$ENV_FILE" "$key" "$value" <<'PY'
from pathlib import Path
import sys
path = Path(sys.argv[1])
key = sys.argv[2]
value = sys.argv[3]
lines = path.read_text(encoding="utf-8").splitlines()
out = []
for line in lines:
    if line.startswith(f"{key}="):
        out.append(f"{key}={value}")
    else:
        out.append(line)
path.write_text("\n".join(out) + "\n", encoding="utf-8")
PY
  else
    printf '%s=%s\n' "$key" "$value" >> "$ENV_FILE"
  fi
}

subcommand="${1:-}"
if [[ -z "$subcommand" || "$subcommand" == "--help" || "$subcommand" == "-h" ]]; then
  usage
  exit 0
fi
shift || true

BACKEND=""
ENVIRONMENT=""
SESSION_ID=""
BUILDING_FILTER=""
LOCATION_FILTER=""
TAG_FILTER=""
FORCE=0
REPO_DIR=""
PYTHON_BIN=""
SKIP_TORCH=0
SKIP_FLASH_ATTN=0
SKIP_REQUIREMENTS=0
SMALL_VRAM=0
PASSTHRU_ARGS=()

while [[ $# -gt 0 ]]; do
  case "$1" in
    --backend)
      BACKEND="${2:-}"
      shift 2
      ;;
    --environment|--env)
      ENVIRONMENT="${2:-}"
      shift 2
      ;;
    --session)
      SESSION_ID="${2:-}"
      shift 2
      ;;
    --building)
      BUILDING_FILTER="${2:-}"
      shift 2
      ;;
    --location)
      LOCATION_FILTER="${2:-}"
      shift 2
      ;;
    --tag)
      TAG_FILTER="${2:-}"
      shift 2
      ;;
    --force)
      FORCE=1
      shift
      ;;
    --repo-dir)
      REPO_DIR="${2:-}"
      shift 2
      ;;
    --python)
      PYTHON_BIN="${2:-}"
      shift 2
      ;;
    --skip-torch)
      SKIP_TORCH=1
      shift
      ;;
    --skip-flash-attn)
      SKIP_FLASH_ATTN=1
      shift
      ;;
    --skip-requirements)
      SKIP_REQUIREMENTS=1
      shift
      ;;
    --small-vram)
      SMALL_VRAM=1
      shift
      ;;
    --help|-h)
      usage
      exit 0
      ;;
    *)
      PASSTHRU_ARGS+=("$1")
      shift
      ;;
  esac
done

case "$subcommand" in
  install|prepare|run|all|status) ;;
  *)
    usage
    die "Unknown subcommand: $subcommand"
    ;;
esac

load_env

if [[ -z "$BACKEND" && "$subcommand" != "status" ]]; then
  die "--backend is required for $subcommand"
fi

if [[ -z "$REPO_DIR" ]]; then
  case "$BACKEND" in
    hyworld) REPO_DIR="$ROOT_DIR/external-models/HY-World-2.0" ;;
    lyra) REPO_DIR="$ROOT_DIR/external-models/lyra" ;;
  esac
fi

if [[ -z "$PYTHON_BIN" ]]; then
  PYTHON_BIN="$(pick_default_python "$BACKEND")"
fi

prepare_args=()
[[ -n "$ENVIRONMENT" ]] && prepare_args+=(--environment "$ENVIRONMENT")
[[ -n "$BACKEND" ]] && prepare_args+=(--backend "$BACKEND")
[[ -n "$SESSION_ID" ]] && prepare_args+=(--session "$SESSION_ID")
[[ -n "$BUILDING_FILTER" ]] && prepare_args+=(--building "$BUILDING_FILTER")
[[ -n "$LOCATION_FILTER" ]] && prepare_args+=(--location "$LOCATION_FILTER")
[[ -n "$TAG_FILTER" ]] && prepare_args+=(--tag "$TAG_FILTER")
[[ "$FORCE" -eq 1 ]] && prepare_args+=(--force)
[[ "$SMALL_VRAM" -eq 1 ]] && prepare_args+=(--small-vram)
if [[ "${#PASSTHRU_ARGS[@]}" -gt 0 ]]; then
  prepare_args+=("${PASSTHRU_ARGS[@]}")
fi

install_hyworld() {
  ensure_env_file
  mkdir -p "$(dirname "$REPO_DIR")"
  if [[ ! -d "$REPO_DIR/.git" ]]; then
    log "Cloning HY-World-2.0 into $REPO_DIR"
    git clone https://github.com/Tencent-Hunyuan/HY-World-2.0 "$REPO_DIR"
  else
    log "HY-World repo already present at $REPO_DIR"
  fi

  local venv_dir="$REPO_DIR/.venv"
  local target_pyver
  target_pyver="$("$PYTHON_BIN" - <<'PY'
import sys
print(f"{sys.version_info.major}.{sys.version_info.minor}")
PY
)"
  if [[ "$target_pyver" != "3.10" ]]; then
    log "HY-World upstream recommends Python 3.10; requested interpreter is Python $target_pyver"
  fi
  if [[ -x "$venv_dir/bin/python" ]]; then
    local existing_pyver
    existing_pyver="$(python_version_string "$venv_dir/bin/python")"
    if [[ "$existing_pyver" != "$target_pyver" ]]; then
      log "Existing HY-World venv uses Python $existing_pyver; recreating with Python $target_pyver"
      rm -rf "$venv_dir"
    fi
  fi
  if [[ ! -x "$venv_dir/bin/python" ]]; then
    log "Creating virtual environment at $venv_dir"
    "$PYTHON_BIN" -m venv "$venv_dir"
  fi

  local vpy="$venv_dir/bin/python"
  local vpip="$venv_dir/bin/pip"
  local pyver
  pyver="$(python_version_string "$vpy")"
  "$vpip" install --upgrade pip wheel setuptools
  if [[ "$pyver" != "3.10" ]]; then
    log "HY-World upstream recommends Python 3.10; current venv is Python $pyver"
  fi
  if [[ "$SKIP_TORCH" -eq 0 ]]; then
    log "Installing torch/cu124 as recommended by HY-World"
    "$vpip" install torch==2.4.0 torchvision==0.19.0 --index-url https://download.pytorch.org/whl/cu124
  fi
  if [[ "$SKIP_REQUIREMENTS" -eq 0 ]]; then
    log "Installing HY-World requirements"
    if [[ "$pyver" == "3.10" ]]; then
      "$vpip" install -r "$REPO_DIR/requirements.txt"
    else
      local filtered_requirements="$REPO_DIR/.track-requirements-py${pyver/./}.txt"
      python3 - "$REPO_DIR/requirements.txt" "$filtered_requirements" <<'PY'
from pathlib import Path
import sys
src = Path(sys.argv[1])
dst = Path(sys.argv[2])
lines = src.read_text(encoding="utf-8").splitlines()
filtered = []
for line in lines:
    stripped = line.strip()
    if stripped.startswith("gsplat @ "):
        continue
    filtered.append(line)
dst.write_text("\n".join(filtered) + "\n", encoding="utf-8")
PY
      log "Installing filtered HY-World requirements for Python $pyver (without pinned cp310 gsplat wheel)"
      "$vpip" install -r "$filtered_requirements"
      log "Installing gsplat separately for Python $pyver"
      "$vpip" install gsplat==1.5.3
    fi
  fi
  if [[ "$SKIP_FLASH_ATTN" -eq 0 ]]; then
    log "Installing flash-attn (fallback path; upstream also documents FlashAttention-3 build)"
    "$vpip" install flash-attn --no-build-isolation || log "flash-attn install failed; you can retry manually later"
  fi
  set_env_var HYWORLD_REPO "$REPO_DIR"
  set_env_var HYWORLD_PYTHON "$vpy"
  set_env_var HYWORLD_USE_CAMERA_PRIOR "${HYWORLD_USE_CAMERA_PRIOR:-1}"
  set_env_var HYWORLD_NPROC_PER_NODE "${HYWORLD_NPROC_PER_NODE:-2}"
  set_env_var HYWORLD_DISABLE_FLASH_ATTN "${HYWORLD_DISABLE_FLASH_ATTN:-1}"
  log "HY-World configured in $ENV_FILE"
}

install_lyra() {
  ensure_env_file
  mkdir -p "$(dirname "$REPO_DIR")"
  if [[ ! -d "$REPO_DIR/.git" ]]; then
    log "Cloning Lyra into $REPO_DIR"
    git clone https://github.com/nv-tlabs/lyra "$REPO_DIR"
  else
    log "Lyra repo already present at $REPO_DIR"
  fi
  local venv_dir="$REPO_DIR/.venv"
  if [[ ! -x "$venv_dir/bin/python" ]]; then
    log "Creating virtual environment at $venv_dir"
    "$PYTHON_BIN" -m venv "$venv_dir"
  fi
  local vpy="$venv_dir/bin/python"
  local vpip="$venv_dir/bin/pip"
  "$vpip" install --upgrade pip wheel setuptools
  if [[ -f "$REPO_DIR/requirements.txt" && "$SKIP_REQUIREMENTS" -eq 0 ]]; then
    "$vpip" install -r "$REPO_DIR/requirements.txt" || log "Lyra requirements install may need manual follow-up"
  fi
  set_env_var LYRA_REPO "$REPO_DIR"
  set_env_var LYRA_PYTHON "$vpy"
  log "Lyra repo configured in $ENV_FILE (execution still manual/placeholder in TRACK)"
}

run_backend_workspace() {
  local backend="$1"
  local session_num
  session_num="$(printf '%04d' "$SESSION_ID")"
  local env_data_dir="$MAP3D_DIR/data"
  [[ -n "$ENVIRONMENT" ]] && env_data_dir="$MAP3D_DIR/data/environments/$ENVIRONMENT"
  local workspace="$env_data_dir/derived/model_reconstructions/session_${session_num}/${backend}"
  local run_script="$workspace/scripts/run-backend.sh"
  [[ -x "$run_script" ]] || die "Run script not found: $run_script. Prepare the backend first."

  case "$backend" in
    hyworld)
      [[ -n "${HYWORLD_REPO:-}" ]] || die "HYWORLD_REPO is not configured in $ENV_FILE"
      [[ -n "${HYWORLD_PYTHON:-}" ]] || die "HYWORLD_PYTHON is not configured in $ENV_FILE"
      HYWORLD_REPO="$HYWORLD_REPO" \
      HYWORLD_PYTHON="$HYWORLD_PYTHON" \
      HYWORLD_USE_CAMERA_PRIOR="${HYWORLD_USE_CAMERA_PRIOR:-1}" \
      HYWORLD_NPROC_PER_NODE="${HYWORLD_NPROC_PER_NODE:-2}" \
      HYWORLD_DISABLE_FLASH_ATTN="${HYWORLD_DISABLE_FLASH_ATTN:-1}" \
      "$run_script"
      ;;
    lyra)
      [[ -n "${LYRA_REPO:-}" ]] || die "LYRA_REPO is not configured in $ENV_FILE"
      [[ -n "${LYRA_PYTHON:-}" ]] || die "LYRA_PYTHON is not configured in $ENV_FILE"
      LYRA_REPO="$LYRA_REPO" \
      LYRA_PYTHON="$LYRA_PYTHON" \
      "$run_script"
      ;;
    *)
      die "Unsupported backend: $backend"
      ;;
  esac
}

show_status() {
  local data_dir="$MAP3D_DIR/data"
  [[ -n "$ENVIRONMENT" ]] && data_dir="$MAP3D_DIR/data/environments/$ENVIRONMENT"
  echo "Config file: $ENV_FILE"
  if [[ -f "$ENV_FILE" ]]; then
    echo "Configured backends:"
    [[ -n "${HYWORLD_REPO:-}" ]] && echo "  hyworld repo:  $HYWORLD_REPO"
    [[ -n "${HYWORLD_PYTHON:-}" ]] && echo "  hyworld python: $HYWORLD_PYTHON"
    [[ -n "${HYWORLD_DISABLE_FLASH_ATTN:-}" ]] && echo "  hyworld disable flash-attn: $HYWORLD_DISABLE_FLASH_ATTN"
    [[ -n "${LYRA_REPO:-}" ]] && echo "  lyra repo:     $LYRA_REPO"
    [[ -n "${LYRA_PYTHON:-}" ]] && echo "  lyra python:   $LYRA_PYTHON"
  else
    echo "No local backend config yet. See $EXAMPLE_ENV_FILE"
  fi
  local root="$data_dir/derived/model_reconstructions"
  if [[ -d "$root" ]]; then
    echo
    echo "Prepared model workspaces:"
    find "$root" -maxdepth 3 -name job.json | sort
  fi
}

case "$subcommand" in
  install)
    case "$BACKEND" in
      hyworld) install_hyworld ;;
      lyra) install_lyra ;;
      *) die "Unsupported backend: $BACKEND" ;;
    esac
    ;;
  prepare)
    "$PREPARE_SCRIPT" "${prepare_args[@]}"
    ;;
  run)
    [[ -n "$SESSION_ID" ]] || die "--session is required for run"
    run_backend_workspace "$BACKEND"
    ;;
  all)
    "$PREPARE_SCRIPT" "${prepare_args[@]}"
    [[ -n "$SESSION_ID" ]] || die "--session is required for all"
    run_backend_workspace "$BACKEND"
    ;;
  status)
    show_status
    ;;
esac
