#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MAP3D_DIR="$ROOT_DIR/map3d"
DEFAULT_RECON_BASE="$MAP3D_DIR/data/derived/reconstructions"

usage() {
  cat <<'EOF'
Usage:
  ./map3d-dense.sh
  ./map3d-dense.sh --name full-walk
  ./map3d-dense.sh --workspace map3d/data/derived/reconstructions/full-walk

Options:
  --name NAME        Reconstruction workspace name under
                     map3d/data/derived/reconstructions
  --workspace DIR    Explicit reconstruction workspace directory
  --images DIR       Explicit image directory. If omitted, the script tries
                     map3d/data/derived/reconstruction_sets/<name>/images
  --model ID         Sparse model directory name under sparse/ (default: best model)
  --quality LEVEL    Dense quality preset: low, medium, high
                     Default: low
  --cpu-only         Force CPU mode even if colmap-cuda exists
  --force            Delete existing dense outputs before running
  --help             Show this help

What this does:
  1. picks a sparse model from an existing reconstruction workspace
  2. runs image_undistorter
  3. runs patch_match_stereo
  4. runs stereo_fusion

Outputs:
  <workspace>/dense/
    images/
    sparse/
    stereo/
    fused.ply

This produces a dense point cloud. It does not yet build or texture a mesh.
EOF
}

log() {
  printf '\n[%s] %s\n' "$(date '+%H:%M:%S')" "$*"
}

die() {
  printf '\nERROR: %s\n' "$*" >&2
  exit 1
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

WORKSPACE_NAME=""
WORKSPACE_DIR=""
IMAGES_DIR=""
MODEL_ID=""
QUALITY="low"
CPU_ONLY=0
FORCE=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --name)
      WORKSPACE_NAME="${2:-}"
      shift 2
      ;;
    --workspace)
      WORKSPACE_DIR="${2:-}"
      shift 2
      ;;
    --images)
      IMAGES_DIR="${2:-}"
      shift 2
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
[[ -n "$WORKSPACE_NAME" || -n "$WORKSPACE_DIR" ]] || WORKSPACE_NAME="latest-auto"

case "$QUALITY" in
  low)
    MAX_IMAGE_SIZE=1200
    PATCHMATCH_WINDOW_RADIUS=4
    PATCHMATCH_NUM_SAMPLES=8
    PATCHMATCH_NUM_ITERATIONS=3
    PATCHMATCH_GEOM_CONSISTENCY=1
    STEREO_FUSION_MIN_PIXELS=5
    ;;
  medium)
    MAX_IMAGE_SIZE=1600
    PATCHMATCH_WINDOW_RADIUS=5
    PATCHMATCH_NUM_SAMPLES=12
    PATCHMATCH_NUM_ITERATIONS=4
    PATCHMATCH_GEOM_CONSISTENCY=1
    STEREO_FUSION_MIN_PIXELS=5
    ;;
  high)
    MAX_IMAGE_SIZE=2400
    PATCHMATCH_WINDOW_RADIUS=5
    PATCHMATCH_NUM_SAMPLES=15
    PATCHMATCH_NUM_ITERATIONS=5
    PATCHMATCH_GEOM_CONSISTENCY=1
    STEREO_FUSION_MIN_PIXELS=4
    ;;
  *)
    die "Unknown quality preset: $QUALITY (use low, medium, or high)"
    ;;
esac

if [[ -n "$WORKSPACE_NAME" && -n "$WORKSPACE_DIR" ]]; then
  die "Use either --name or --workspace, not both."
fi

if [[ -n "$WORKSPACE_NAME" ]]; then
  WORKSPACE_DIR="$DEFAULT_RECON_BASE/$WORKSPACE_NAME"
fi

WORKSPACE_DIR="$(realpath -m "$WORKSPACE_DIR")"
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

if [[ -z "$IMAGES_DIR" ]]; then
  if [[ -n "$WORKSPACE_NAME" ]] && [[ -d "$MAP3D_DIR/data/derived/reconstruction_sets/$WORKSPACE_NAME/images" ]]; then
    IMAGES_DIR="$MAP3D_DIR/data/derived/reconstruction_sets/$WORKSPACE_NAME/images"
  else
    BASENAME_WORKSPACE="$(basename "$WORKSPACE_DIR")"
    if [[ -d "$MAP3D_DIR/data/derived/reconstruction_sets/$BASENAME_WORKSPACE/images" ]]; then
      IMAGES_DIR="$MAP3D_DIR/data/derived/reconstruction_sets/$BASENAME_WORKSPACE/images"
    fi
  fi
fi

[[ -n "$IMAGES_DIR" ]] || die "Could not infer image directory. Use --images DIR."
IMAGES_DIR="$(realpath -m "$IMAGES_DIR")"
[[ -d "$IMAGES_DIR" ]] || die "Image directory does not exist: $IMAGES_DIR"

DENSE_DIR="$WORKSPACE_DIR/dense"
FUSED_PLY="$DENSE_DIR/fused.ply"
LOG_PATH="$WORKSPACE_DIR/dense.log"

if [[ -e "$DENSE_DIR" ]]; then
  if [[ "$FORCE" -eq 1 ]]; then
    log "Removing existing dense output: $DENSE_DIR"
    rm -rf "$DENSE_DIR"
  else
    die "Dense output already exists: $DENSE_DIR (use --force to replace it)"
  fi
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
log "Quality preset: $QUALITY"
log "Max image size: $MAX_IMAGE_SIZE"
log "PatchMatch window radius: $PATCHMATCH_WINDOW_RADIUS"
log "PatchMatch samples: $PATCHMATCH_NUM_SAMPLES"
log "PatchMatch iterations: $PATCHMATCH_NUM_ITERATIONS"

if [[ "$USE_GPU" -eq 0 ]]; then
  log "GPU note: using CPU COLMAP. Dense stereo will be much slower."
fi

log "Step 1/3: image undistortion"
"$COLMAP_BIN" image_undistorter \
  --image_path "$IMAGES_DIR" \
  --input_path "$SPARSE_MODEL_DIR" \
  --output_path "$DENSE_DIR" \
  --output_type COLMAP \
  --max_image_size "$MAX_IMAGE_SIZE"

log "Step 2/3: dense stereo"
"$COLMAP_BIN" patch_match_stereo \
  --workspace_path "$DENSE_DIR" \
  --workspace_format COLMAP \
  --PatchMatchStereo.gpu_index "$([[ "$USE_GPU" -eq 1 ]] && printf '0' || printf '-1')" \
  --PatchMatchStereo.window_radius "$PATCHMATCH_WINDOW_RADIUS" \
  --PatchMatchStereo.num_samples "$PATCHMATCH_NUM_SAMPLES" \
  --PatchMatchStereo.num_iterations "$PATCHMATCH_NUM_ITERATIONS" \
  --PatchMatchStereo.geom_consistency "$PATCHMATCH_GEOM_CONSISTENCY"

log "Step 3/3: stereo fusion"
"$COLMAP_BIN" stereo_fusion \
  --workspace_path "$DENSE_DIR" \
  --workspace_format COLMAP \
  --input_type geometric \
  --StereoFusion.min_num_pixels "$STEREO_FUSION_MIN_PIXELS" \
  --output_path "$FUSED_PLY"

[[ -f "$FUSED_PLY" ]] || die "Dense fusion finished without producing $FUSED_PLY"

POINT_LINES="$(grep -vc '^#' "$DENSE_DIR/stereo/fusion.cfg" 2>/dev/null || true)"
PLY_SIZE="$(du -h "$FUSED_PLY" | awk '{print $1}')"

log "Dense output ready"
log "Fused point cloud: $FUSED_PLY"
log "PLY size: $PLY_SIZE"

log "Next useful commands:"
printf '  %s poisson_mesher --input_path %q --output_path %q\n' \
  "$COLMAP_BIN" "$FUSED_PLY" "$DENSE_DIR/meshed-poisson.ply"
printf '  %s delaunay_mesher --input_path %q --output_path %q\n' \
  "$COLMAP_BIN" "$DENSE_DIR" "$DENSE_DIR/meshed-delaunay.ply"
printf '  %s model_analyzer --path %q\n' "$COLMAP_BIN" "$SPARSE_MODEL_DIR"
