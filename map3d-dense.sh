#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MAP3D_DIR="$ROOT_DIR/map3d"
DEFAULT_DATA_DIR="$MAP3D_DIR/data"
DATA_DIR="${MAP3D_DATA_DIR:-$DEFAULT_DATA_DIR}"
JOBS_SCRIPT="$ROOT_DIR/map3d-jobs.sh"
SIMPLIFY_MESH_SCRIPT="$MAP3D_DIR/simplify_mesh.py"

usage() {
  cat <<'EOF'
Usage:
  ./map3d-dense.sh
  ./map3d-dense.sh --environment museum
  ./map3d-dense.sh --environment museum --session 0001
  ./map3d-dense.sh --environment museum --building waterlinie --location technische
  ./map3d-dense.sh --workspace /absolute/workspace/path

Options:
  --environment NAME  Use map3d/data/environments/NAME as the data dir.
  --session ID        Dense-process one specific reconstructed session workspace.
  --workspace DIR     Dense-process one explicit reconstruction workspace.
  --building TEXT     Filter by building name fragment.
  --location TEXT     Filter by location name fragment.
  --tag TEXT          Filter by tag fragment.
  --list              List matching reconstructed workspaces and exit.
  --model ID          Sparse model directory name under sparse/ (default: best model)
  --quality LEVEL     Dense quality preset: low, medium, high. Default: low
  --cpu-only          Force CPU mode even if colmap-cuda exists
  --force             Replace existing dense outputs instead of resuming them
  --help              Show this help

What this does:
  1. picks a sparse model from an existing reconstruction workspace
  2. runs image_undistorter
  3. runs patch_match_stereo
  4. runs stereo_fusion
  5. runs poisson_mesher

Outputs:
  <workspace>/dense/
    images/
    sparse/
    stereo/
    fused.ply
    meshed-poisson.ply
    meshed-web.ply
EOF
}

log() {
  printf '\n[%s] %s\n' "$(date '+%H:%M:%S')" "$*"
}

die() {
  printf '\nERROR: %s\n' "$*" >&2
  exit 1
}

run_with_progress() {
  local label="$1"
  shift
  local line=""
  local progress_active=0
  local current=0
  local total=0
  local percent=0
  set +e
  "$@" 2>&1 | while IFS= read -r line; do
    if [[ "$line" =~ Fusing\ image\ \[([0-9]+)/([0-9]+)\] ]]; then
      current="${BASH_REMATCH[1]}"
      total="${BASH_REMATCH[2]}"
      percent=$(( current * 100 / total ))
      printf '\r[%s] %s/%s (%s%%)' "$label" "$current" "$total" "$percent"
      progress_active=1
      continue
    fi
    if [[ "$line" =~ Processing\ image\ \[([0-9]+)/([0-9]+)\] ]]; then
      current="${BASH_REMATCH[1]}"
      total="${BASH_REMATCH[2]}"
      percent=$(( current * 100 / total ))
      printf '\r[%s] %s/%s (%s%%)' "$label" "$current" "$total" "$percent"
      progress_active=1
      continue
    fi
    if [[ "$progress_active" -eq 1 ]]; then
      printf '\n'
      progress_active=0
    fi
    printf '%s\n' "$line"
  done
  local cmd_status=${PIPESTATUS[0]}
  set -e
  return "$cmd_status"
}

pick_colmap_bin() {
  local local_cuda_bin="$ROOT_DIR/tmp-colmap-build/pkgroot/opt/colmap-cuda/bin/colmap"
  if [[ "$CPU_ONLY" -eq 0 ]] && command -v colmap-cuda >/dev/null 2>&1; then
    COLMAP_BIN="colmap-cuda"
    USE_GPU=1
  elif [[ "$CPU_ONLY" -eq 0 ]] && [[ -x "$local_cuda_bin" ]]; then
    COLMAP_BIN="$local_cuda_bin"
    USE_GPU=1
  else
    COLMAP_BIN="colmap"
    USE_GPU=0
  fi
}

parse_int() {
  printf '%s' "$1" | sed -n 's/.*: \([0-9][0-9]*\).*/\1/p' | head -n 1
}

ply_vertex_count() {
  local ply_path="$1"
  [[ -f "$ply_path" ]] || {
    printf '0\n'
    return
  }
  python3 - "$ply_path" <<'PY'
from pathlib import Path
import sys

path = Path(sys.argv[1])
count = 0
with path.open("rb") as handle:
    for raw in handle:
        line = raw.decode("ascii", "replace").strip()
        if line.startswith("element vertex "):
            count = int(line.split()[-1])
        if line == "end_header":
            break
print(count)
PY
}

ply_face_count() {
  local ply_path="$1"
  [[ -f "$ply_path" ]] || {
    printf '0\n'
    return
  }
  python3 - "$ply_path" <<'PY'
from pathlib import Path
import sys

path = Path(sys.argv[1])
count = 0
with path.open("rb") as handle:
    for raw in handle:
        line = raw.decode("ascii", "replace").strip()
        if line.startswith("element face "):
            count = int(line.split()[-1])
        if line == "end_header":
            break
print(count)
PY
}

best_sparse_model() {
  local sparse_root="$1"
  local best_dir=""
  local best_images="-1"
  local best_points="-1"
  local dir
  for dir in "$sparse_root"/*; do
    [[ -d "$dir" ]] || continue
    [[ -f "$dir/images.bin" ]] || continue
    local analyzer_output
    analyzer_output="$("$COLMAP_BIN" model_analyzer --path "$dir" 2>&1 || true)"
    local registered
    local points
    registered="$(parse_int "$(printf '%s\n' "$analyzer_output" | grep 'Registered images:' || true)")"
    points="$(parse_int "$(printf '%s\n' "$analyzer_output" | grep 'Points:' || true)")"
    [[ -n "$registered" ]] || registered=0
    [[ -n "$points" ]] || points=0
    if (( registered > best_images || (registered == best_images && points > best_points) )); then
      best_images="$registered"
      best_points="$points"
      best_dir="$dir"
    fi
  done
  [[ -n "$best_dir" ]] || return 1
  printf '%s\n' "$best_dir"
}

ENV_NAME=""
SESSION_ID=""
WORKSPACE_DIR=""
BUILDING_FILTER=""
LOCATION_FILTER=""
TAG_FILTER=""
LIST_ONLY=0
MODEL_ID=""
QUALITY="low"
CPU_ONLY=0
FORCE=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --environment|--env)
      ENV_NAME="${2:-}"
      shift 2
      ;;
    --session)
      SESSION_ID="${2:-}"
      shift 2
      ;;
    --workspace)
      WORKSPACE_DIR="${2:-}"
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
    --list)
      LIST_ONLY=1
      shift
      ;;
    --model)
      MODEL_ID="${2:-}"
      shift 2
      ;;
    --quality)
      QUALITY="${2:-}"
      shift 2
      ;;
    --cpu-only)
      CPU_ONLY=1
      shift
      ;;
    --force)
      FORCE=1
      shift
      ;;
    --help|-h)
      usage
      exit 0
      ;;
    *)
      die "Unknown argument: $1"
      ;;
  esac
done

[[ -d "$MAP3D_DIR" ]] || die "Expected map3d directory at $MAP3D_DIR"

if [[ -n "$ENV_NAME" ]]; then
  DATA_DIR="$MAP3D_DIR/data/environments/$ENV_NAME"
fi
export MAP3D_DATA_DIR="$(realpath -m "$DATA_DIR")"
DEFAULT_RECON_BASE="$MAP3D_DATA_DIR/derived/reconstructions"
DEFAULT_SET_BASE="$MAP3D_DATA_DIR/derived/reconstruction_sets"

case "$QUALITY" in
  low)
    MAX_IMAGE_SIZE=1200
    PATCHMATCH_WINDOW_RADIUS=4
    PATCHMATCH_NUM_SAMPLES=8
    PATCHMATCH_NUM_ITERATIONS=3
    PATCHMATCH_GEOM_CONSISTENCY=1
    PATCHMATCH_FILTER_MIN_NCC=0.08
    STEREO_FUSION_MIN_PIXELS=5
    POISSON_DEPTH=10
    POISSON_TRIM=12
    ;;
  medium)
    MAX_IMAGE_SIZE=1600
    PATCHMATCH_WINDOW_RADIUS=5
    PATCHMATCH_NUM_SAMPLES=12
    PATCHMATCH_NUM_ITERATIONS=4
    PATCHMATCH_GEOM_CONSISTENCY=1
    PATCHMATCH_FILTER_MIN_NCC=0.1
    STEREO_FUSION_MIN_PIXELS=5
    POISSON_DEPTH=11
    POISSON_TRIM=10
    ;;
  high)
    MAX_IMAGE_SIZE=2400
    PATCHMATCH_WINDOW_RADIUS=5
    PATCHMATCH_NUM_SAMPLES=15
    PATCHMATCH_NUM_ITERATIONS=5
    PATCHMATCH_GEOM_CONSISTENCY=1
    PATCHMATCH_FILTER_MIN_NCC=0.1
    STEREO_FUSION_MIN_PIXELS=4
    POISSON_DEPTH=12
    POISSON_TRIM=9
    ;;
  *)
    die "Unknown quality preset: $QUALITY (use low, medium, or high)"
    ;;
esac

if [[ -n "$SESSION_ID" && -n "$WORKSPACE_DIR" ]]; then
  die "Use either --session or --workspace, not both."
fi

if [[ "$LIST_ONLY" -eq 1 ]]; then
  JOB_ARGS=(--need any)
  [[ -n "$ENV_NAME" ]] && JOB_ARGS=(--environment "$ENV_NAME" "${JOB_ARGS[@]}")
  [[ -n "$BUILDING_FILTER" ]] && JOB_ARGS+=(--building "$BUILDING_FILTER")
  [[ -n "$LOCATION_FILTER" ]] && JOB_ARGS+=(--location "$LOCATION_FILTER")
  [[ -n "$TAG_FILTER" ]] && JOB_ARGS+=(--tag "$TAG_FILTER")
  "$JOBS_SCRIPT" "${JOB_ARGS[@]}"
  exit 0
fi

if [[ -n "$SESSION_ID" ]]; then
  RUN_NAME="session_$(printf '%04d' "$SESSION_ID")"
  WORKSPACE_DIR="$DEFAULT_RECON_BASE/$RUN_NAME"
elif [[ -z "$WORKSPACE_DIR" ]]; then
  JOB_ARGS=(--need any --ids-only)
  [[ -n "$ENV_NAME" ]] && JOB_ARGS=(--environment "$ENV_NAME" "${JOB_ARGS[@]}")
  [[ -n "$BUILDING_FILTER" ]] && JOB_ARGS+=(--building "$BUILDING_FILTER")
  [[ -n "$LOCATION_FILTER" ]] && JOB_ARGS+=(--location "$LOCATION_FILTER")
  [[ -n "$TAG_FILTER" ]] && JOB_ARGS+=(--tag "$TAG_FILTER")
  mapfile -t SESSION_IDS < <("$JOBS_SCRIPT" "${JOB_ARGS[@]}")
  FILTERED_SESSION_IDS=()
  for sid in "${SESSION_IDS[@]}"; do
    run_name="session_$(printf '%04d' "$sid")"
    if [[ -d "$DEFAULT_RECON_BASE/$run_name/sparse" ]]; then
      FILTERED_SESSION_IDS+=("$sid")
    fi
  done
  SESSION_IDS=("${FILTERED_SESSION_IDS[@]}")
  if [[ "${#SESSION_IDS[@]}" -eq 0 ]]; then
    log "No matching reconstructed jobs."
    exit 0
  fi
  for sid in "${SESSION_IDS[@]}"; do
    log "Dense processing job session $sid"
    child_args=()
    [[ -n "$ENV_NAME" ]] && child_args+=(--environment "$ENV_NAME")
    child_args+=(--session "$sid" --quality "$QUALITY")
    [[ "$FORCE" -eq 1 ]] && child_args+=(--force)
    [[ "$CPU_ONLY" -eq 1 ]] && child_args+=(--cpu-only)
    [[ -n "$MODEL_ID" ]] && child_args+=(--model "$MODEL_ID")
    "$0" "${child_args[@]}"
  done
  exit 0
fi

WORKSPACE_DIR="$(realpath -m "$WORKSPACE_DIR")"
RUN_NAME="$(basename "$WORKSPACE_DIR")"
[[ -d "$WORKSPACE_DIR" ]] || die "Reconstruction workspace does not exist: $WORKSPACE_DIR"

pick_colmap_bin

SPARSE_ROOT="$WORKSPACE_DIR/sparse"
[[ -d "$SPARSE_ROOT" ]] || die "No sparse directory found in workspace: $SPARSE_ROOT"

if [[ -n "$MODEL_ID" ]]; then
  SPARSE_MODEL_DIR="$SPARSE_ROOT/$MODEL_ID"
  [[ -d "$SPARSE_MODEL_DIR" ]] || die "Sparse model not found: $SPARSE_MODEL_DIR"
else
  SPARSE_MODEL_DIR="$(best_sparse_model "$SPARSE_ROOT")" || die "No usable sparse model found in $SPARSE_ROOT"
  MODEL_ID="$(basename "$SPARSE_MODEL_DIR")"
fi

IMAGES_DIR="$DEFAULT_SET_BASE/$RUN_NAME/images"
[[ -d "$IMAGES_DIR" ]] || die "Could not infer image directory at $IMAGES_DIR"
IMAGES_DIR="$(realpath -m "$IMAGES_DIR")"
IMAGE_COUNT="$(find -L "$IMAGES_DIR" -maxdepth 1 \( -type f -o -type l \) \( -iname '*.jpg' -o -iname '*.jpeg' -o -iname '*.png' \) | wc -l | tr -d ' ')"

DENSE_DIR="$WORKSPACE_DIR/dense"
FUSED_PLY="$DENSE_DIR/fused.ply"
POISSON_PLY="$DENSE_DIR/meshed-poisson.ply"
DELAUNAY_PLY="$DENSE_DIR/meshed-delaunay.ply"
WEB_PLY="$DENSE_DIR/meshed-web.ply"
LOG_PATH="$WORKSPACE_DIR/dense.log"

if [[ -d "$DENSE_DIR/images" ]]; then
  DENSE_IMAGE_COUNT="$(find -L "$DENSE_DIR/images" -maxdepth 1 \( -type f -o -type l \) | wc -l | tr -d ' ')"
  if [[ "${DENSE_IMAGE_COUNT:-0}" -gt 0 && "${DENSE_IMAGE_COUNT:-0}" -ne "$IMAGE_COUNT" ]]; then
    log "Prepared set changed (${DENSE_IMAGE_COUNT} -> ${IMAGE_COUNT} dense images); resetting dense workspace."
    rm -rf "$DENSE_DIR"
  fi
fi

if [[ -e "$DENSE_DIR" && "$FORCE" -eq 1 ]]; then
  log "Removing existing dense output: $DENSE_DIR"
  rm -rf "$DENSE_DIR"
fi

mkdir -p "$DENSE_DIR"
exec > >(tee -a "$LOG_PATH") 2>&1

log "map3d dense reconstruction helper"
log "Repo root: $ROOT_DIR"
log "COLMAP binary: $COLMAP_BIN"
log "GPU mode: $USE_GPU"
log "Workspace: $WORKSPACE_DIR"
log "Images directory: $IMAGES_DIR"
log "Sparse model: $SPARSE_MODEL_DIR"
log "Dense output: $DENSE_DIR"
if [[ -d "$DENSE_DIR" ]]; then
  log "Resume mode: reusing any existing undistortion, depth maps, fused cloud, or mesh in this workspace."
fi
log "Quality preset: $QUALITY"
log "Max image size: $MAX_IMAGE_SIZE"
log "PatchMatch window radius: $PATCHMATCH_WINDOW_RADIUS"
log "PatchMatch samples: $PATCHMATCH_NUM_SAMPLES"
log "PatchMatch iterations: $PATCHMATCH_NUM_ITERATIONS"
log "PatchMatch filter min NCC: $PATCHMATCH_FILTER_MIN_NCC"
log "Poisson depth: $POISSON_DEPTH"
log "Poisson trim: $POISSON_TRIM"

if [[ "$USE_GPU" -eq 0 ]]; then
  log "GPU note: using CPU COLMAP. Dense stereo will be much slower."
fi

if [[ -d "$DENSE_DIR/images" && -d "$DENSE_DIR/sparse" ]]; then
  log "Step 1/4: image undistortion already present, reusing $DENSE_DIR"
else
  log "Step 1/4: image undistortion"
  run_with_progress "image undistorter" \
    "$COLMAP_BIN" image_undistorter \
    --image_path "$IMAGES_DIR" \
    --input_path "$SPARSE_MODEL_DIR" \
    --output_path "$DENSE_DIR" \
    --output_type COLMAP \
    --max_image_size "$MAX_IMAGE_SIZE"
fi

count_dense_outputs() {
  local subdir="$1"
  find "$DENSE_DIR/stereo/$subdir" -type f 2>/dev/null | wc -l | tr -d '[:space:]'
}

run_patch_match() {
  local mode="$1"
  local geom_consistency="$2"

  rm -rf "$DENSE_DIR/stereo/depth_maps" "$DENSE_DIR/stereo/normal_maps" "$DENSE_DIR/stereo/consistency_graphs"
  mkdir -p "$DENSE_DIR/stereo/depth_maps" "$DENSE_DIR/stereo/normal_maps" "$DENSE_DIR/stereo/consistency_graphs"

  log "Step 2/4: dense stereo ($mode)"
  run_with_progress "patch match $mode" \
    "$COLMAP_BIN" patch_match_stereo \
    --workspace_path "$DENSE_DIR" \
    --workspace_format COLMAP \
    --PatchMatchStereo.gpu_index "$([[ "$USE_GPU" -eq 1 ]] && printf '0' || printf '-1')" \
    --PatchMatchStereo.max_image_size "$MAX_IMAGE_SIZE" \
    --PatchMatchStereo.window_radius "$PATCHMATCH_WINDOW_RADIUS" \
    --PatchMatchStereo.num_samples "$PATCHMATCH_NUM_SAMPLES" \
    --PatchMatchStereo.num_iterations "$PATCHMATCH_NUM_ITERATIONS" \
    --PatchMatchStereo.geom_consistency "$geom_consistency" \
    --PatchMatchStereo.filter 1 \
    --PatchMatchStereo.filter_min_ncc "$PATCHMATCH_FILTER_MIN_NCC" \
    --PatchMatchStereo.filter_min_num_consistent 2 \
    --PatchMatchStereo.write_consistency_graph "$geom_consistency"

  local depth_count
  local normal_count
  local graph_count
  depth_count="$(count_dense_outputs depth_maps)"
  normal_count="$(count_dense_outputs normal_maps)"
  graph_count="$(count_dense_outputs consistency_graphs)"
  log "PatchMatch output ($mode): depth_maps=$depth_count normal_maps=$normal_count consistency_graphs=$graph_count"

  [[ "$depth_count" -gt 0 && "$normal_count" -gt 0 ]]
}

run_fusion() {
  local input_type="$1"
  local mode="$2"

  rm -f "$FUSED_PLY" "$FUSED_PLY.vis" "$POISSON_PLY" "$DELAUNAY_PLY"

  log "Step 3/4: stereo fusion ($mode)"
  run_with_progress "fusion $mode" \
    "$COLMAP_BIN" stereo_fusion \
    --workspace_path "$DENSE_DIR" \
    --workspace_format COLMAP \
    --input_type "$input_type" \
    --StereoFusion.min_num_pixels "$STEREO_FUSION_MIN_PIXELS" \
    --output_path "$FUSED_PLY"

  [[ -f "$FUSED_PLY" ]] || die "Dense fusion finished without producing $FUSED_PLY"
}

run_mode=""
FUSED_VERTEX_COUNT=0
if [[ -f "$FUSED_PLY" ]]; then
  FUSED_VERTEX_COUNT="$(ply_vertex_count "$FUSED_PLY")"
  if [[ "$FUSED_VERTEX_COUNT" -gt 0 ]]; then
    log "Step 2-3/4: fused cloud already present, reusing $FUSED_PLY"
  else
    rm -f "$FUSED_PLY" "$FUSED_PLY.vis"
  fi
fi

if [[ "${FUSED_VERTEX_COUNT:-0}" -le 0 ]]; then
  existing_depth_count="$(count_dense_outputs depth_maps)"
  existing_normal_count="$(count_dense_outputs normal_maps)"
  existing_graph_count="$(count_dense_outputs consistency_graphs)"
  if [[ "$existing_depth_count" -gt 0 && "$existing_normal_count" -gt 0 ]]; then
    if [[ "$existing_graph_count" -gt 0 ]]; then
      existing_input_type="geometric"
    else
      existing_input_type="photometric"
    fi
    run_mode="existing-$existing_input_type"
    log "Step 2/4: reusing existing PatchMatch outputs"
    run_fusion "$existing_input_type" "$run_mode"
  elif run_patch_match geometric "$PATCHMATCH_GEOM_CONSISTENCY"; then
    run_mode="geometric"
    run_fusion geometric "$run_mode"
  else
    log "Geometric PatchMatch produced no depth maps; retrying photometric fallback."
    if run_patch_match photometric 0; then
      run_mode="photometric"
      run_fusion photometric "$run_mode"
    else
      die "PatchMatch produced no depth maps in geometric or photometric mode. Check $LOG_PATH."
    fi
  fi
fi

[[ -f "$FUSED_PLY" ]] || die "Dense fusion finished without producing $FUSED_PLY"

FUSED_VERTEX_COUNT="$(ply_vertex_count "$FUSED_PLY")"
[[ -n "$FUSED_VERTEX_COUNT" ]] || FUSED_VERTEX_COUNT=0
if [[ "$FUSED_VERTEX_COUNT" -le 0 ]]; then
  if [[ "$run_mode" != "photometric" ]]; then
    log "Geometric fusion produced zero points; retrying photometric fallback."
    if run_patch_match photometric 0; then
      run_mode="photometric"
      run_fusion photometric "$run_mode"
      FUSED_VERTEX_COUNT="$(python3 - "$FUSED_PLY" <<'PY'
from pathlib import Path
import sys
path = Path(sys.argv[1])
count = 0
with path.open('rb') as handle:
    for raw in handle:
        line = raw.decode('ascii', 'replace').strip()
        if line.startswith('element vertex '):
            count = int(line.split()[-1])
        if line == 'end_header':
            break
print(count)
PY
)"
      [[ -n "$FUSED_VERTEX_COUNT" ]] || FUSED_VERTEX_COUNT=0
    fi
  fi
fi

if [[ "$FUSED_VERTEX_COUNT" -le 0 ]]; then
  die "Dense fusion produced zero points in $run_mode mode. Check $LOG_PATH and consider lowering image size/quality, reducing source images per view, or rerunning sparse with different coverage."
fi

if [[ -f "$POISSON_PLY" ]]; then
  log "Step 4/4: poisson mesh already present, reusing $POISSON_PLY"
else
  log "Step 4/4: poisson meshing"
  run_with_progress "poisson mesher" \
    "$COLMAP_BIN" poisson_mesher \
    --input_path "$FUSED_PLY" \
    --output_path "$POISSON_PLY" \
    --PoissonMeshing.depth "$POISSON_DEPTH" \
    --PoissonMeshing.trim "$POISSON_TRIM" \
    --PoissonMeshing.color 1
fi

POISSON_FACE_COUNT=0
if [[ -f "$POISSON_PLY" ]]; then
  POISSON_FACE_COUNT="$(ply_face_count "$POISSON_PLY")"
fi

MESH_OUTPUT="$POISSON_PLY"
if [[ ! -f "$POISSON_PLY" || "${POISSON_FACE_COUNT:-0}" -le 0 ]]; then
  log "Poisson mesh is empty; falling back to Delaunay meshing."
  run_with_progress "delaunay mesher" \
    "$COLMAP_BIN" delaunay_mesher \
    --input_path "$DENSE_DIR" \
    --input_type dense \
    --output_path "$DELAUNAY_PLY"
  [[ -f "$DELAUNAY_PLY" ]] || die "Delaunay meshing finished without producing $DELAUNAY_PLY"
  MESH_OUTPUT="$DELAUNAY_PLY"
fi

WEB_FACE_COUNT=0
if [[ -f "$MESH_OUTPUT" && -f "$SIMPLIFY_MESH_SCRIPT" ]]; then
  mesh_source_mtime="$(stat -c %Y "$MESH_OUTPUT" 2>/dev/null || printf '0')"
  web_mtime="$(stat -c %Y "$WEB_PLY" 2>/dev/null || printf '0')"
  if [[ ! -f "$WEB_PLY" || "$web_mtime" -lt "$mesh_source_mtime" || "$FORCE" -eq 1 ]]; then
    log "Step 5/5: web mesh simplification"
    python3 "$SIMPLIFY_MESH_SCRIPT" "$MESH_OUTPUT" "$WEB_PLY" --max-faces 40000
  else
    log "Step 5/5: web mesh already present, reusing $WEB_PLY"
  fi
  WEB_FACE_COUNT="$(ply_face_count "$WEB_PLY")"
  if [[ "${WEB_FACE_COUNT:-0}" -le 0 ]]; then
    log "Web mesh simplification produced no faces; removing $WEB_PLY"
    rm -f "$WEB_PLY"
  fi
fi

FUSED_SIZE="$(du -h "$FUSED_PLY" | awk '{print $1}')"
MESH_SIZE="$(du -h "$MESH_OUTPUT" | awk '{print $1}')"
WEB_SIZE=""
if [[ -f "$WEB_PLY" ]]; then
  WEB_SIZE="$(du -h "$WEB_PLY" | awk '{print $1}')"
fi

log "Dense output ready"
log "Dense mode: $run_mode"
log "Fused point cloud: $FUSED_PLY"
log "Fused vertices: $FUSED_VERTEX_COUNT"
log "Fused size: $FUSED_SIZE"
log "Mesh: $MESH_OUTPUT"
log "Mesh size: $MESH_SIZE"
if [[ -f "$WEB_PLY" ]]; then
  log "Web mesh: $WEB_PLY"
  log "Web mesh size: $WEB_SIZE"
fi
log "Viewer:"
printf '  %s/viewer/%s?geometry=dense\n' "${TRACK_BASE_URL:-http://127.0.0.1:5000}" "$RUN_NAME"
printf '  %s/viewer/%s?geometry=mesh\n' "${TRACK_BASE_URL:-http://127.0.0.1:5000}" "$RUN_NAME"
