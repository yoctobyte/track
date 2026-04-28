#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MAP3D_DIR="$ROOT_DIR/map3d"
DATA_DIR="${MAP3D_DATA_DIR:-$MAP3D_DIR/data}"
DEFAULT_ORIGINALS_DIR="$DATA_DIR/originals"
DEFAULT_OUTPUT_BASE="$DATA_DIR/derived/reconstructions"
COLLECTOR_SCRIPT="$ROOT_DIR/map3d-collect-reconstruction-set.sh"
PREPARE_SCRIPT="$ROOT_DIR/map3d-prepare-session.sh"
JOBS_SCRIPT="$ROOT_DIR/map3d-jobs.sh"

usage() {
  cat <<'EOF'
Usage:
  ./map3d-reconstruct.sh
  ./map3d-reconstruct.sh --environment museum
  ./map3d-reconstruct.sh --environment museum --building ij --location patch
  ./map3d-reconstruct.sh --session 0121
  ./map3d-reconstruct.sh --environment museum --session 0121
  ./map3d-reconstruct.sh --images /absolute/or/relative/image_dir --name pilot-room

Options:
  --environment NAME  Use map3d/data/environments/NAME as the data dir.
  --session ID         Reconstruct one specific session.
  --building TEXT      Filter by building name fragment.
  --location TEXT      Filter by location name fragment.
  --tag TEXT           Filter by tag fragment.
  --list               List matching reconstruction jobs and exit.
  --images DIR         Use a specific image directory.
  --name NAME          Output workspace name. Defaults to session_XXXX or the
                       image directory name.
  --output-dir DIR     Base output directory.
                       Default: map3d/data/derived/reconstructions
  --camera-model NAME  COLMAP camera model. Default: SIMPLE_RADIAL
  --single-camera      Tell COLMAP to assume one shared camera intrinsics model.
                       This is the default (one user, one phone per capture).
  --multi-camera       Let COLMAP solve a separate camera per image. Only
                       useful for mixed datasets from multiple devices.
  --cpu-only           Force CPU mode even if colmap-cuda exists.
  --force              Replace an existing output workspace instead of resuming it.
  --skip-prepare       Assume the session reconstruction set is already prepared.
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
  - With no session/images specified, reconstruct all matching unreconstructed jobs.
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
  local progress_text=""
  local current=0
  local total=0
  local percent=0
  set +e
  "$@" 2>&1 | while IFS= read -r line; do
    if [[ "$line" =~ Processed\ file\ \[([0-9]+)/([0-9]+)\] ]]; then
      current="${BASH_REMATCH[1]}"
      total="${BASH_REMATCH[2]}"
      percent=$(( current * 100 / total ))
      progress_text="[${label}] ${current}/${total} (${percent}%)"
      printf '\r%s' "$progress_text"
      progress_active=1
      continue
    fi
    if [[ "$line" =~ Matching\ block\ \[([0-9]+)/([0-9]+)\] ]]; then
      current="${BASH_REMATCH[1]}"
      total="${BASH_REMATCH[2]}"
      percent=$(( current * 100 / total ))
      progress_text="[${label}] matching ${current}/${total} (${percent}%)"
      printf '\r%s' "$progress_text"
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
  if [[ "$progress_active" -eq 1 ]]; then
    printf '\n'
  fi
  return "$cmd_status"
}

sqlite_scalar() {
  local db_path="$1"
  local sql="$2"
  [[ -f "$db_path" ]] || {
    printf '0\n'
    return
  }
  python3 - "$db_path" "$sql" <<'PY'
import sqlite3
import sys

db_path, sql = sys.argv[1], sys.argv[2]
conn = None
try:
    conn = sqlite3.connect(db_path)
    cur = conn.execute(sql)
    row = cur.fetchone()
    print((row[0] if row else 0) or 0)
except Exception:
    print(0)
finally:
    if conn is not None:
        conn.close()
PY
}

database_has_features() {
  [[ -f "$DATABASE_PATH" ]] || return 1
  local image_rows keypoint_rows descriptor_rows
  image_rows="$(sqlite_scalar "$DATABASE_PATH" 'SELECT COUNT(*) FROM images;')"
  keypoint_rows="$(sqlite_scalar "$DATABASE_PATH" 'SELECT COUNT(*) FROM keypoints;')"
  descriptor_rows="$(sqlite_scalar "$DATABASE_PATH" 'SELECT COUNT(*) FROM descriptors;')"
  [[ "${image_rows:-0}" -gt 0 && "${keypoint_rows:-0}" -gt 0 && "${descriptor_rows:-0}" -gt 0 ]]
}

database_has_matches() {
  [[ -f "$DATABASE_PATH" ]] || return 1
  local match_rows geometry_rows
  match_rows="$(sqlite_scalar "$DATABASE_PATH" 'SELECT COUNT(*) FROM matches;')"
  geometry_rows="$(sqlite_scalar "$DATABASE_PATH" 'SELECT COUNT(*) FROM two_view_geometries;')"
  [[ "${match_rows:-0}" -gt 0 || "${geometry_rows:-0}" -gt 0 ]]
}

database_uses_resolved_image_paths() {
  [[ -f "$DATABASE_PATH" ]] || return 1
  local escaped
  escaped="$(sqlite_scalar "$DATABASE_PATH" "SELECT COUNT(*) FROM images WHERE name LIKE '%/%';")"
  [[ "${escaped:-0}" -gt 0 ]]
}

sparse_models_exist() {
  [[ -d "$SPARSE_DIR" ]] || return 1
  find "$SPARSE_DIR" -mindepth 2 -maxdepth 2 \
    \( -name 'points3D.bin' -o -name 'points3D.txt' \) | grep -q .
}

SESSION_ID=""
ENV_NAME=""
BUILDING_FILTER=""
LOCATION_FILTER=""
TAG_FILTER=""
LIST_ONLY=0
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
SKIP_PREPARE=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --session)
      SESSION_ID="${2:-}"
      shift 2
      ;;
    --environment|--env)
      ENV_NAME="${2:-}"
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
    --force)
      FORCE=1
      shift
      ;;
    --skip-prepare)
      SKIP_PREPARE=1
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
  export MAP3D_DATA_DIR="$DATA_DIR"
  DEFAULT_ORIGINALS_DIR="$DATA_DIR/originals"
  DEFAULT_OUTPUT_BASE="$DATA_DIR/derived/reconstructions"
  if [[ "$OUTPUT_BASE" == "$MAP3D_DIR/data"* ]]; then
    OUTPUT_BASE="$DEFAULT_OUTPUT_BASE${OUTPUT_BASE#"$MAP3D_DIR/data/derived/reconstructions"}"
  elif [[ "$OUTPUT_BASE" == "$DEFAULT_OUTPUT_BASE"* ]]; then
    OUTPUT_BASE="$OUTPUT_BASE"
  fi
fi

if [[ "$LIST_ONLY" -eq 1 ]]; then
  JOB_ARGS=(--need reconstruct)
  [[ -n "$ENV_NAME" ]] && JOB_ARGS=(--environment "$ENV_NAME" "${JOB_ARGS[@]}")
  [[ -n "$BUILDING_FILTER" ]] && JOB_ARGS+=(--building "$BUILDING_FILTER")
  [[ -n "$LOCATION_FILTER" ]] && JOB_ARGS+=(--location "$LOCATION_FILTER")
  [[ -n "$TAG_FILTER" ]] && JOB_ARGS+=(--tag "$TAG_FILTER")
  "$JOBS_SCRIPT" "${JOB_ARGS[@]}"
  exit 0
fi

if [[ -n "$SESSION_ID" && -n "$IMAGES_DIR" ]]; then
  die "Use either --session or --images, not both."
fi

reconstruct_one_session() {
  local local_session_id="$1"
  local local_run_name="session_$(printf '%04d' "$local_session_id")"
  if [[ "$SKIP_PREPARE" -eq 0 ]]; then
    local prepare_args=(--session "$local_session_id")
    [[ "$FORCE" -eq 1 ]] && prepare_args+=(--force)
    [[ -n "$ENV_NAME" ]] && prepare_args=(--environment "$ENV_NAME" "${prepare_args[@]}")
    "$PREPARE_SCRIPT" "${prepare_args[@]}" >/dev/null
  fi
  IMAGES_DIR="$DATA_DIR/derived/reconstruction_sets/$local_run_name/images"
  RUN_NAME="$local_run_name"
}

if [[ -n "$SESSION_ID" ]]; then
  SESSION_NUM="$(printf '%04d' "$SESSION_ID" 2>/dev/null || true)"
  [[ -n "$SESSION_NUM" ]] || die "Invalid session id: $SESSION_ID"
  reconstruct_one_session "$SESSION_ID"
elif [[ -z "$IMAGES_DIR" ]]; then
  JOB_ARGS=(--need reconstruct --ids-only)
  [[ -n "$ENV_NAME" ]] && JOB_ARGS=(--environment "$ENV_NAME" "${JOB_ARGS[@]}")
  [[ -n "$BUILDING_FILTER" ]] && JOB_ARGS+=(--building "$BUILDING_FILTER")
  [[ -n "$LOCATION_FILTER" ]] && JOB_ARGS+=(--location "$LOCATION_FILTER")
  [[ -n "$TAG_FILTER" ]] && JOB_ARGS+=(--tag "$TAG_FILTER")
  mapfile -t SESSION_IDS < <("$JOBS_SCRIPT" "${JOB_ARGS[@]}")
  if [[ "${#SESSION_IDS[@]}" -eq 0 ]]; then
    log "No matching unreconstructed jobs."
    exit 0
  fi
  for sid in "${SESSION_IDS[@]}"; do
    log "Reconstructing job session $sid"
    child_args=()
    [[ -n "$ENV_NAME" ]] && child_args+=(--environment "$ENV_NAME")
    child_args+=(--session "$sid")
    [[ "$FORCE" -eq 1 ]] && child_args+=(--force)
    [[ "$CPU_ONLY" -eq 1 ]] && child_args+=(--cpu-only)
    [[ "$SINGLE_CAMERA" -eq 0 ]] && child_args+=(--multi-camera)
    [[ -n "$CAMERA_MODEL" ]] && child_args+=(--camera-model "$CAMERA_MODEL")
    "$0" "${child_args[@]}"
  done
  exit 0
fi

IMAGES_DIR="$(realpath -m "$IMAGES_DIR")"
[[ -d "$IMAGES_DIR" ]] || die "Image directory does not exist: $IMAGES_DIR"

if [[ -z "$RUN_NAME" ]]; then
  RUN_NAME="$(basename "$IMAGES_DIR")"
fi
RUN_NAME="$(basename "$RUN_NAME")"

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

FEATURE_HELP="$("$COLMAP_BIN" feature_extractor -h 2>&1 || true)"
MATCHER_HELP="$("$COLMAP_BIN" exhaustive_matcher -h 2>&1 || true)"
if printf '%s' "$FEATURE_HELP" | grep -q -- '--FeatureExtraction.use_gpu'; then
  FEATURE_USE_GPU_OPT="--FeatureExtraction.use_gpu"
else
  FEATURE_USE_GPU_OPT="--SiftExtraction.use_gpu"
fi
if printf '%s' "$MATCHER_HELP" | grep -q -- '--FeatureMatching.use_gpu'; then
  MATCH_USE_GPU_OPT="--FeatureMatching.use_gpu"
  MATCH_MAX_OPT="--FeatureMatching.max_num_matches"
  MATCH_GUIDED_OPT="--FeatureMatching.guided_matching"
  MATCH_THREADS_OPT="--FeatureMatching.num_threads"
else
  MATCH_USE_GPU_OPT="--SiftMatching.use_gpu"
  MATCH_MAX_OPT="--SiftMatching.max_num_matches"
  MATCH_GUIDED_OPT="--SiftMatching.guided_matching"
  MATCH_THREADS_OPT="--SiftMatching.num_threads"
fi

IMAGE_COUNT="$(find -L "$IMAGES_DIR" -maxdepth 1 \( -type f -o -type l \) \( -iname '*.jpg' -o -iname '*.jpeg' -o -iname '*.png' \) | wc -l | tr -d ' ')"
[[ "$IMAGE_COUNT" -gt 0 ]] || die "No JPG/JPEG/PNG files found in $IMAGES_DIR"

if [[ "$IMAGE_COUNT" -lt 2 ]]; then
  die "Only $IMAGE_COUNT image found in $IMAGES_DIR. COLMAP needs multiple overlapping images for any 3D reconstruction."
fi

if [[ -f "$DATABASE_PATH" ]]; then
  DATABASE_IMAGE_COUNT="$(sqlite_scalar "$DATABASE_PATH" 'SELECT COUNT(*) FROM images;')"
  if [[ "${DATABASE_IMAGE_COUNT:-0}" -gt 0 && "${DATABASE_IMAGE_COUNT:-0}" -ne "$IMAGE_COUNT" ]]; then
    log "Prepared set changed (${DATABASE_IMAGE_COUNT} -> ${IMAGE_COUNT} images); resetting sparse workspace to include new session media."
    rm -f "$DATABASE_PATH"
    rm -rf "$SPARSE_DIR"
    rm -rf "$WORKSPACE_DIR/dense"
  elif database_uses_resolved_image_paths; then
    log "Sparse workspace uses resolved source paths; resetting to rebuild against stable session frame names."
    rm -f "$DATABASE_PATH"
    rm -rf "$SPARSE_DIR"
    rm -rf "$WORKSPACE_DIR/dense"
  fi
fi

if [[ -e "$WORKSPACE_DIR" && "$FORCE" -eq 1 ]]; then
  log "Removing existing workspace: $WORKSPACE_DIR"
  rm -rf "$WORKSPACE_DIR"
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
if [[ -f "$DATABASE_PATH" || -d "$SPARSE_DIR" ]]; then
  log "Resume mode: reusing any existing database, matches, and sparse models in this workspace."
fi

if [[ "$USE_GPU" -eq 0 ]]; then
  log "GPU note: using CPU COLMAP. Install the local colmap-cuda package if you want GPU SIFT/matching."
fi

if [[ "$IMAGE_COUNT" -lt 8 ]]; then
  log "Dataset note: this is a very small image set. Expect failure or a weak model unless the images overlap extremely well."
elif [[ "$IMAGE_COUNT" -lt 20 ]]; then
  log "Dataset note: this may work for a tiny object/spot, but it is still sparse for room-scale reconstruction."
fi

if database_has_features; then
  log "Step 1/3: feature extraction already present, reusing $DATABASE_PATH"
else
  log "Step 1/3: feature extraction"
  # Notes on extraction tuning:
  #   - max_num_features 16384 gives more to work with on busy outdoor scenes; the
  #     matcher may clamp per pair but that's fine.
  #   - We deliberately do NOT enable estimate_affine_shape or domain_size_pooling:
  #     both force COLMAP onto the CPU SIFT path, which negates the whole point of
  #     using colmap-cuda. The GPU SIFT path is fast enough that we can afford
  #     plain DoG SIFT and make up for it with exhaustive matching + guided
  #     matching at the pair stage.
  run_with_progress "feature extraction" \
    "$COLMAP_BIN" feature_extractor \
    --database_path "$DATABASE_PATH" \
    --image_path "$IMAGES_DIR" \
    --ImageReader.camera_model "$CAMERA_MODEL" \
    --ImageReader.single_camera "$SINGLE_CAMERA" \
    "$FEATURE_USE_GPU_OPT" "$USE_GPU" \
    --SiftExtraction.max_num_features 16384
fi

if database_has_matches; then
  log "Step 2/3: exhaustive matching already present, reusing $DATABASE_PATH"
else
  log "Step 2/3: exhaustive matching"
  # Notes on matching tuning:
  #   - max_num_matches 16384 keeps us under the GTX 1660's 6 GB limit for images
  #     that produced >20k features; otherwise the GPU matcher OOMs.
  #   - num_threads 1 serializes GPU workers so they don't both fight for VRAM.
  #   - guided_matching recovers more inliers on textured outdoor scenes.
  run_with_progress "matching" \
    "$COLMAP_BIN" exhaustive_matcher \
    --database_path "$DATABASE_PATH" \
    "$MATCH_USE_GPU_OPT" "$USE_GPU" \
    "$MATCH_MAX_OPT" 16384 \
    "$MATCH_THREADS_OPT" 1 \
    "$MATCH_GUIDED_OPT" 1
fi

if sparse_models_exist; then
  log "Step 3/3: sparse mapping already present, reusing $SPARSE_DIR"
else
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
  run_with_progress "sparse mapper" \
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
fi

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
