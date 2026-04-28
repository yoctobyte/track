#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MAP3D_DIR="$ROOT_DIR/map3d"
DEFAULT_DATA_DIR="$MAP3D_DIR/data"
DATA_DIR="${MAP3D_DATA_DIR:-$DEFAULT_DATA_DIR}"
HELPER="$MAP3D_DIR/texture_mesh.py"
BAKER="$MAP3D_DIR/texture_bake.py"

usage() {
  cat <<'EOF'
Usage:
  ./map3d-texture.sh
  ./map3d-texture.sh --environment museum
  ./map3d-texture.sh --environment museum --session 0001

Options:
  --environment NAME   Use map3d/data/environments/NAME as the data dir.
  --session ID         Texture one specific session workspace.
  --texture-size PX    Texture atlas size (default: 4096).
  --mesh-kind KIND     web, delaunay, poisson, auto (default: auto).
  --max-images N       Limit source images considered during baking (debug/tuning).
  --force              Rebuild existing texturing outputs.
  --help               Show this help.
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
  if command -v colmap-cuda >/dev/null 2>&1; then
    COLMAP_BIN="colmap-cuda"
  elif [[ -x "$local_cuda_bin" ]]; then
    COLMAP_BIN="$local_cuda_bin"
  elif command -v colmap >/dev/null 2>&1; then
    COLMAP_BIN="colmap"
  else
    die "COLMAP binary not found."
  fi
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
    local registered points
    registered="$(printf '%s\n' "$analyzer_output" | sed -n 's/.*Registered images: \([0-9][0-9]*\).*/\1/p' | head -n 1)"
    points="$(printf '%s\n' "$analyzer_output" | sed -n 's/.*Points: \([0-9][0-9]*\).*/\1/p' | head -n 1)"
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

pick_mesh_path() {
  local dense_dir="$1"
  local mesh_kind="$2"
  case "$mesh_kind" in
    web)
      [[ -f "$dense_dir/meshed-web.ply" ]] && printf '%s\n' "$dense_dir/meshed-web.ply"
      ;;
    delaunay)
      [[ -f "$dense_dir/meshed-delaunay.ply" ]] && printf '%s\n' "$dense_dir/meshed-delaunay.ply"
      ;;
    poisson)
      [[ -f "$dense_dir/meshed-poisson.ply" ]] && printf '%s\n' "$dense_dir/meshed-poisson.ply"
      ;;
    auto)
      for path in "$dense_dir/meshed-web.ply" "$dense_dir/meshed-delaunay.ply" "$dense_dir/meshed-poisson.ply"; do
        [[ -f "$path" ]] && { printf '%s\n' "$path"; return 0; }
      done
      ;;
    *)
      die "Unknown mesh kind: $mesh_kind"
      ;;
  esac
}

ENV_NAME=""
SESSION_ID=""
TEXTURE_SIZE=4096
MESH_KIND="auto"
FORCE=0
MAX_IMAGES=0

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
    --texture-size)
      TEXTURE_SIZE="${2:-}"
      shift 2
      ;;
    --mesh-kind)
      MESH_KIND="${2:-}"
      shift 2
      ;;
    --max-images)
      MAX_IMAGES="${2:-}"
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
if [[ -n "$ENV_NAME" ]]; then
  DATA_DIR="$MAP3D_DIR/data/environments/$ENV_NAME"
fi
export MAP3D_DATA_DIR="$(realpath -m "$DATA_DIR")"

RECON_ROOT="$MAP3D_DATA_DIR/derived/reconstructions"
SET_ROOT="$MAP3D_DATA_DIR/derived/reconstruction_sets"

pick_colmap_bin

if [[ -z "$SESSION_ID" ]]; then
  for workspace_dir in "$RECON_ROOT"/session_*; do
    [[ -d "$workspace_dir" ]] || continue
    if pick_mesh_path "$workspace_dir/dense" "$MESH_KIND" >/dev/null; then
      if [[ ! -f "$workspace_dir/texturing/textured.obj" ]]; then
        SESSION_ID="${workspace_dir##*_}"
        break
      fi
    fi
  done
fi

[[ -n "$SESSION_ID" ]] || die "No textured-eligible session found."
RUN_NAME="session_$(printf '%04d' "$SESSION_ID")"
WORKSPACE_DIR="$RECON_ROOT/$RUN_NAME"
SPARSE_ROOT="$WORKSPACE_DIR/sparse"
IMAGES_DIR="$SET_ROOT/$RUN_NAME/images"
DENSE_DIR="$WORKSPACE_DIR/dense"

[[ -d "$WORKSPACE_DIR" ]] || die "Workspace not found: $WORKSPACE_DIR"
[[ -d "$SPARSE_ROOT" ]] || die "Sparse output missing: $SPARSE_ROOT"
[[ -d "$IMAGES_DIR" ]] || die "Prepared images missing: $IMAGES_DIR"

MESH_PATH="$(pick_mesh_path "$DENSE_DIR" "$MESH_KIND")"
[[ -n "$MESH_PATH" ]] || die "No usable mesh found in $DENSE_DIR"

case "$(basename "$MESH_PATH")" in
  meshed-delaunay.ply)
    TEXTURE_DIR="$WORKSPACE_DIR/texturing_delaunay"
    ;;
  meshed-poisson.ply)
    TEXTURE_DIR="$WORKSPACE_DIR/texturing_poisson"
    ;;
  meshed-web.ply)
    if [[ "$MESH_KIND" == "web" ]]; then
      TEXTURE_DIR="$WORKSPACE_DIR/texturing_web"
    else
      TEXTURE_DIR="$WORKSPACE_DIR/texturing"
    fi
    ;;
  *)
    TEXTURE_DIR="$WORKSPACE_DIR/texturing"
    ;;
esac

BUNDLER_DIR="$TEXTURE_DIR/bundler"
RASTER_DIR="$BUNDLER_DIR/images"
PREFIX="$BUNDLER_DIR/export"
BUNDLE_FILE="$PREFIX.bundle.out"
LIST_FILE="$PREFIX.list.txt"
LIST_RASTER_FILE="$PREFIX.rasters.list.txt"
TXT_DIR="$TEXTURE_DIR/colmap_txt"
CAMERAS_TXT="$TXT_DIR/cameras.txt"
IMAGES_TXT="$TXT_DIR/images.txt"
OUTPUT_OBJ="$TEXTURE_DIR/textured.obj"
OUTPUT_PNG="$TEXTURE_DIR/texture.png"
OUTPUT_META="$TEXTURE_DIR/texture_meta.json"

mkdir -p "$TEXTURE_DIR" "$BUNDLER_DIR" "$RASTER_DIR" "$TXT_DIR"

if [[ -f "$OUTPUT_OBJ" && -f "$OUTPUT_META" && "$FORCE" -eq 0 ]]; then
  if python3 - <<'PY' "$OUTPUT_META" "$TEXTURE_SIZE" "$MAX_IMAGES"
import json, sys
meta_path, texture_size, max_images = sys.argv[1:]
try:
    meta = json.load(open(meta_path, encoding="utf-8"))
except Exception:
    raise SystemExit(1)
ok = (
    int(meta.get("texture_size", -1)) == int(texture_size)
    and int(meta.get("max_images", -1)) == int(max_images)
)
raise SystemExit(0 if ok else 1)
PY
  then
    log "Textured mesh already present: $OUTPUT_OBJ"
    exit 0
  fi
fi

if [[ "$FORCE" -eq 1 ]]; then
  rm -f "$OUTPUT_OBJ" "$TEXTURE_DIR"/textured.mtl "$OUTPUT_PNG" "$OUTPUT_META"
fi

SPARSE_MODEL_DIR="$(best_sparse_model "$SPARSE_ROOT")" || die "No sparse model found in $SPARSE_ROOT"

log "map3d texturing helper"
log "Workspace: $WORKSPACE_DIR"
log "Sparse model: $SPARSE_MODEL_DIR"
log "Images: $IMAGES_DIR"
log "Mesh input: $MESH_PATH"
log "Texture output: $OUTPUT_OBJ"

if [[ ! -f "$CAMERAS_TXT" || ! -f "$IMAGES_TXT" || "$FORCE" -eq 1 ]]; then
  log "Exporting COLMAP text cameras"
  rm -f "$TXT_DIR"/*.txt
  "$COLMAP_BIN" model_converter \
    --input_path "$SPARSE_MODEL_DIR" \
    --output_path "$TXT_DIR" \
    --output_type TXT
fi

log "Running automatic texture baker"
if map3d/venv/bin/python "$BAKER" \
  --mesh "$MESH_PATH" \
  --cameras "$CAMERAS_TXT" \
  --images "$IMAGES_TXT" \
  --images-dir "$IMAGES_DIR" \
  --output-dir "$TEXTURE_DIR" \
  --texture-size "$TEXTURE_SIZE" \
  --texture-name "$(basename "$OUTPUT_PNG")" \
  --mesh-name "$(basename "$OUTPUT_OBJ")" \
  --max-images "$MAX_IMAGES"; then
  python3 - <<'PY' "$OUTPUT_META" "$TEXTURE_SIZE" "$MAX_IMAGES" "$MESH_KIND" "$MESH_PATH"
import json, sys
meta_path, texture_size, max_images, mesh_kind, mesh_path = sys.argv[1:]
with open(meta_path, "w", encoding="utf-8") as fh:
    json.dump(
        {
            "texture_size": int(texture_size),
            "max_images": int(max_images),
            "mesh_kind": mesh_kind,
            "mesh_path": mesh_path,
        },
        fh,
        indent=2,
    )
PY
  log "Texturing complete"
  printf '  %s\n' "$OUTPUT_OBJ"
  printf '  %s\n' "$OUTPUT_PNG"
  exit 0
fi

log "Automatic baker failed; preparing MeshLab fallback assets"

if [[ ! -f "$BUNDLE_FILE" || ! -f "$LIST_FILE" || "$FORCE" -eq 1 ]]; then
  log "Exporting Bundler cameras"
  "$COLMAP_BIN" model_converter \
    --input_path "$SPARSE_MODEL_DIR" \
    --output_path "$PREFIX" \
    --output_type Bundler
fi

log "Preparing local raster list for MeshLab"
> "$LIST_RASTER_FILE"
while IFS= read -r image_name; do
  [[ -n "$image_name" ]] || continue
  image_path="$IMAGES_DIR/$image_name"
  [[ -f "$image_path" ]] || die "Missing prepared frame for Bundler image: $image_path"
  raster_path="$RASTER_DIR/$image_name"
  if [[ ! -f "$raster_path" || "$FORCE" -eq 1 ]]; then
    rm -f "$raster_path"
    ln "$image_path" "$raster_path" 2>/dev/null || cp -f "$image_path" "$raster_path"
  fi
  printf 'images/%s\n' "$image_name" >> "$LIST_RASTER_FILE"
done < "$LIST_FILE"

log "Running PyMeshLab texture baking"
if ! map3d/venv/bin/python "$HELPER" \
  --mesh "$MESH_PATH" \
  --bundle "$BUNDLE_FILE" \
  --list "$LIST_RASTER_FILE" \
  --output-dir "$TEXTURE_DIR" \
  --texture-size "$TEXTURE_SIZE" \
  --texture-name "$(basename "$OUTPUT_PNG")" \
  --mesh-name "$(basename "$OUTPUT_OBJ")" \
  --save-project; then
  die "PyMeshLab texturing crashed. The prepared MeshLab project is at $TEXTURE_DIR/texturing_setup.mlp and can be used with the standalone MeshLab/meshlabserver path."
fi

log "Texturing complete"
printf '  %s\n' "$OUTPUT_OBJ"
printf '  %s\n' "$OUTPUT_PNG"
