#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MAP3D_DIR="$ROOT_DIR/map3d"
DEFAULT_ORIGINALS_DIR="$MAP3D_DIR/data/originals"
DEFAULT_OUTPUT_BASE="$MAP3D_DIR/data/derived/reconstructions"
COLLECTOR_SCRIPT="$ROOT_DIR/map3d-collect-reconstruction-set.sh"

usage() {
  cat <<'EOF'
Usage:
  ./map3d-reconstruct.sh
  ./map3d-reconstruct.sh --session 0121
  ./map3d-reconstruct.sh --images /absolute/or/relative/image_dir --name pilot-room

Options:
  --session ID         Use map3d/data/originals/session_XXXX as the image set.
                       If omitted, the latest contiguous capture run is used.
  --images DIR         Use a specific image directory.
  --name NAME          Output workspace name. Defaults to session_XXXX or the
                       image directory name.
  --output-dir DIR     Base output directory.
                       Default: map3d/data/derived/reconstructions
  --max-gap-sec N      Max gap in seconds for collecting latest run. Default: 15
  --camera-model NAME  COLMAP camera model. Default: SIMPLE_RADIAL
  --single-camera      Tell COLMAP to assume one shared camera intrinsics model.
                       This is the default (one user, one phone per capture).
  --multi-camera       Let COLMAP solve a separate camera per image. Only
                       useful for mixed datasets from multiple devices.
  --cpu-only           Force CPU mode even if colmap-cuda exists.
  --force              Delete an existing output workspace before running.
  --help               Show this help.

What this does:
  1. feature extraction
  2. image matching
  3. sparse reconstruction via mapper

It does not yet run dense reconstruction or mesh generation.

Reality check:
  - 1 image cannot produce a 3D reconstruction.
  - A useful pilot usually wants at least 20-30 overlapping images.
  - A solid room/cabinet pass is more like 80-150 images.
EOF
}

log() {
  printf '\n[%s] %s\n' "$(date '+%H:%M:%S')" "$*"
}

die() {
  printf '\nERROR: %s\n' "$*" >&2
  exit 1
}

SESSION_ID=""
IMAGES_DIR=""
RUN_NAME=""
OUTPUT_BASE="$DEFAULT_OUTPUT_BASE"
CAMERA_MODEL="SIMPLE_RADIAL"
# Default to single-camera on. A map3d capture session is one user walking
# with one phone, so every frame in an image set shares the same intrinsics.
# Letting COLMAP estimate one shared camera is both more accurate and faster
# than solving per-image intrinsics.
SINGLE_CAMERA=1
MULTI_CAMERA=0
FORCE=0
CPU_ONLY=0
MAX_GAP_SEC=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --session)
      SESSION_ID="${2:-}"
      shift 2
      ;;
    --images)
      IMAGES_DIR="${2:-}"
      shift 2
      ;;
    --name)
      RUN_NAME="${2:-}"
      shift 2
      ;;
    --output-dir)
      OUTPUT_BASE="${2:-}"
      shift 2
      ;;
    --camera-model)
      CAMERA_MODEL="${2:-}"
      shift 2
      ;;
    --single-camera)
      SINGLE_CAMERA=1
      shift
      ;;
    --multi-camera)
      SINGLE_CAMERA=0
      shift
      ;;
    --cpu-only)
      CPU_ONLY=1
      shift
      ;;
    --max-gap-sec)
      MAX_GAP_SEC="${2:-}"
      shift 2
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

if [[ -n "$SESSION_ID" && -n "$IMAGES_DIR" ]]; then
  die "Use either --session or --images, not both."
fi

if [[ -z "$SESSION_ID" && -z "$IMAGES_DIR" ]]; then
  [[ -x "$COLLECTOR_SCRIPT" ]] || die "Collector script not found or not executable: $COLLECTOR_SCRIPT"
  AUTO_SET_NAME="latest-auto"
  log "No session or image directory given. Collecting the latest contiguous capture run first."
  GAP_ARGS=()
  if [[ -n "$MAX_GAP_SEC" ]]; then
    GAP_ARGS=("--max-gap-sec" "$MAX_GAP_SEC")
  fi
  "$COLLECTOR_SCRIPT" --name "$AUTO_SET_NAME" --force "${GAP_ARGS[@]}"
  IMAGES_DIR="$MAP3D_DIR/data/derived/reconstruction_sets/$AUTO_SET_NAME/images"
  [[ -n "$RUN_NAME" ]] || RUN_NAME="$AUTO_SET_NAME"
fi

if [[ -n "$SESSION_ID" ]]; then
  SESSION_NUM="$(printf '%04d' "$SESSION_ID" 2>/dev/null || true)"
  [[ -n "$SESSION_NUM" ]] || die "Invalid session id: $SESSION_ID"
  IMAGES_DIR="$DEFAULT_ORIGINALS_DIR/session_${SESSION_NUM}"
  [[ -n "$RUN_NAME" ]] || RUN_NAME="session_${SESSION_NUM}"
fi

IMAGES_DIR="$(realpath -m "$IMAGES_DIR")"
[[ -d "$IMAGES_DIR" ]] || die "Image directory does not exist: $IMAGES_DIR"

if [[ -z "$RUN_NAME" ]]; then
  RUN_NAME="$(basename "$IMAGES_DIR")"
fi

OUTPUT_BASE="$(realpath -m "$OUTPUT_BASE")"
WORKSPACE_DIR="$OUTPUT_BASE/$RUN_NAME"
DATABASE_PATH="$WORKSPACE_DIR/database.db"
SPARSE_DIR="$WORKSPACE_DIR/sparse"
LOG_PATH="$WORKSPACE_DIR/reconstruct.log"

# Prefer the locally built CUDA COLMAP. Order of preference:
#   1. colmap-cuda on PATH (installed via the local .deb)
#   2. the in-tree build under tmp-colmap-build/pkgroot/opt/colmap-cuda/bin/colmap
#   3. system colmap (CPU)
LOCAL_CUDA_BIN="$ROOT_DIR/tmp-colmap-build/pkgroot/opt/colmap-cuda/bin/colmap"
if [[ "$CPU_ONLY" -eq 0 ]] && command -v colmap-cuda >/dev/null 2>&1; then
  COLMAP_BIN="colmap-cuda"
  USE_GPU=1
elif [[ "$CPU_ONLY" -eq 0 ]] && [[ -x "$LOCAL_CUDA_BIN" ]]; then
  COLMAP_BIN="$LOCAL_CUDA_BIN"
  USE_GPU=1
else
  COLMAP_BIN="colmap"
  USE_GPU=0
fi

IMAGE_COUNT="$(find -L "$IMAGES_DIR" -maxdepth 1 \( -type f -o -type l \) \( -iname '*.jpg' -o -iname '*.jpeg' -o -iname '*.png' \) | wc -l | tr -d ' ')"
[[ "$IMAGE_COUNT" -gt 0 ]] || die "No JPG/JPEG/PNG files found in $IMAGES_DIR"

if [[ "$IMAGE_COUNT" -lt 2 ]]; then
  die "Only $IMAGE_COUNT image found in $IMAGES_DIR. COLMAP needs multiple overlapping images for any 3D reconstruction."
fi

if [[ -e "$WORKSPACE_DIR" ]]; then
  if [[ "$FORCE" -eq 1 ]]; then
    log "Removing existing workspace: $WORKSPACE_DIR"
    rm -rf "$WORKSPACE_DIR"
  else
    die "Workspace already exists: $WORKSPACE_DIR (use --force to replace it)"
  fi
fi

mkdir -p "$WORKSPACE_DIR" "$SPARSE_DIR"

exec > >(tee -a "$LOG_PATH") 2>&1

log "map3d manual reconstruction helper"
log "Repo root: $ROOT_DIR"
log "COLMAP binary: $COLMAP_BIN"
log "GPU mode: $USE_GPU"
log "Images directory: $IMAGES_DIR"
log "Image count: $IMAGE_COUNT"
log "Workspace: $WORKSPACE_DIR"
log "Database: $DATABASE_PATH"
log "Camera model: $CAMERA_MODEL"
log "Single camera: $SINGLE_CAMERA"

if [[ "$USE_GPU" -eq 0 ]]; then
  log "GPU note: using CPU COLMAP. Install the local colmap-cuda package if you want GPU SIFT/matching."
fi

if [[ "$IMAGE_COUNT" -lt 8 ]]; then
  log "Dataset note: this is a very small image set. Expect failure or a weak model unless the images overlap extremely well."
elif [[ "$IMAGE_COUNT" -lt 20 ]]; then
  log "Dataset note: this may work for a tiny object/spot, but it is still sparse for room-scale reconstruction."
fi

log "Step 1/3: feature extraction"
# Notes on extraction tuning:
#   - FeatureExtraction.use_gpu is the v4.x option name (was SiftExtraction.use_gpu).
#   - max_num_features 16384 gives more to work with on busy outdoor scenes; the
#     matcher may clamp per pair but that's fine.
#   - We deliberately do NOT enable estimate_affine_shape or domain_size_pooling:
#     both force COLMAP onto the CPU SIFT path, which negates the whole point of
#     using colmap-cuda. The GPU SIFT path is fast enough that we can afford
#     plain DoG SIFT and make up for it with exhaustive matching + guided
#     matching at the pair stage.
"$COLMAP_BIN" feature_extractor \
  --database_path "$DATABASE_PATH" \
  --image_path "$IMAGES_DIR" \
  --ImageReader.camera_model "$CAMERA_MODEL" \
  --ImageReader.single_camera "$SINGLE_CAMERA" \
  --FeatureExtraction.use_gpu "$USE_GPU" \
  --SiftExtraction.max_num_features 16384

log "Step 2/3: exhaustive matching"
# Notes on matching tuning:
#   - FeatureMatching.use_gpu is the v4.x option name (was SiftMatching.use_gpu).
#   - max_num_matches 16384 keeps us under the GTX 1660's 6 GB limit for images
#     that produced >20k features; otherwise the GPU matcher OOMs.
#   - num_threads 1 serializes GPU workers so they don't both fight for VRAM.
#   - guided_matching recovers more inliers on textured outdoor scenes.
"$COLMAP_BIN" exhaustive_matcher \
  --database_path "$DATABASE_PATH" \
  --FeatureMatching.use_gpu "$USE_GPU" \
  --FeatureMatching.max_num_matches 16384 \
  --FeatureMatching.num_threads 1 \
  --FeatureMatching.guided_matching 1

log "Step 3/3: sparse mapping"
# Notes on mapper tuning:
#   - init_min_tri_angle default is 16 degrees. That is too strict for phones
#     walking outdoors: our baselines are small compared to subject distance, so
#     the default rejects every candidate initial pair. 4 degrees bootstraps.
#   - init_min_num_inliers relaxed from 100 to 50 so we can seed from slightly
#     weaker pairs when the scene has busy but repetitive texture.
#   - abs_pose_min_num_inliers relaxed from 30 to 20 for the same reason.
#   - min_model_size 5 lets useful but small sub-models survive (the default 10
#     discarded a 6-image fragment we wanted to keep).
#   - multiple_models 1 so disconnected parts of the capture each get a model.
"$COLMAP_BIN" mapper \
  --database_path "$DATABASE_PATH" \
  --image_path "$IMAGES_DIR" \
  --output_path "$SPARSE_DIR" \
  --Mapper.init_min_tri_angle 4 \
  --Mapper.init_min_num_inliers 50 \
  --Mapper.init_max_forward_motion 0.98 \
  --Mapper.init_num_trials 400 \
  --Mapper.abs_pose_min_num_inliers 20 \
  --Mapper.filter_min_tri_angle 1.0 \
  --Mapper.ba_local_min_tri_angle 3 \
  --Mapper.min_num_matches 10 \
  --Mapper.min_model_size 5 \
  --Mapper.multiple_models 1

MODEL_COUNT="$(find "$SPARSE_DIR" -mindepth 1 -maxdepth 1 -type d | wc -l | tr -d ' ')"
log "Sparse models produced: $MODEL_COUNT"

if [[ "$MODEL_COUNT" -eq 0 ]]; then
  die "No sparse model was produced. Check $LOG_PATH for COLMAP output."
fi

BEST_MODEL="$(find "$SPARSE_DIR" -mindepth 1 -maxdepth 1 -type d | sort | head -n 1)"
ANALYZER_OUTPUT="$("$COLMAP_BIN" model_analyzer --path "$BEST_MODEL" 2>&1 || true)"
REGISTERED_IMAGES="$(printf '%s\n' "$ANALYZER_OUTPUT" | sed -n 's/.*Registered images: \([0-9][0-9]*\).*/\1/p' | head -n 1)"
POINT_COUNT="$(printf '%s\n' "$ANALYZER_OUTPUT" | sed -n 's/.*Points: \([0-9][0-9]*\).*/\1/p' | head -n 1)"
MEAN_ERROR="$(printf '%s\n' "$ANALYZER_OUTPUT" | sed -n 's/.*Mean reprojection error: \([^ ]*\).*/\1/p' | head -n 1)"

[[ -n "$REGISTERED_IMAGES" ]] || REGISTERED_IMAGES="0"
[[ -n "$POINT_COUNT" ]] || POINT_COUNT="0"
[[ -n "$MEAN_ERROR" ]] || MEAN_ERROR="unknown"

log "Best model candidate: $BEST_MODEL"
log "Registered images: $REGISTERED_IMAGES"
log "Sparse points: $POINT_COUNT"
log "Mean reprojection error: $MEAN_ERROR"

if [[ "$REGISTERED_IMAGES" -lt 3 ]]; then
  log "Model quality note: reconstruction technically started, but this is still too small to trust as a useful room-scale result."
elif [[ "$REGISTERED_IMAGES" -lt 10 ]]; then
  log "Model quality note: reconstruction is valid but still thin. Expect a partial or fragile model."
fi

log "Next useful commands:"
printf '  %s gui\n' "$COLMAP_BIN"
printf '  %s model_analyzer --path %q\n' "$COLMAP_BIN" "$BEST_MODEL"
printf '  %s model_converter --input_path %q --output_path %q --output_type TXT\n' \
  "$COLMAP_BIN" "$BEST_MODEL" "$BEST_MODEL"

log "Done."
