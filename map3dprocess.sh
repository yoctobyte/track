#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MAP3D_DIR="$ROOT_DIR/map3d"
PREPARE_SCRIPT="$ROOT_DIR/map3d-prepare-session.sh"
RECONSTRUCT_SCRIPT="$ROOT_DIR/map3d-reconstruct.sh"
DENSE_SCRIPT="$ROOT_DIR/map3d-dense.sh"
TEXTURE_SCRIPT="$ROOT_DIR/map3d-texture.sh"

usage() {
  cat <<'EOF'
Usage:
  ./map3dprocess.sh
  ./map3dprocess.sh --environment museum
  ./map3dprocess.sh --session 0001
  ./map3dprocess.sh --building waterlinie --location patch

Default behavior:
  Find the first incomplete video-backed map3d session and continue:
    1. refresh the prepared reconstruction set
    2. reconstruct sparse COLMAP output
    3. run dense/mesh generation
    4. bake a textured mesh

Options:
  --environment NAME  Limit processing to one environment.
  --session ID        Process one specific session id.
  --building TEXT     Filter by building name fragment.
  --location TEXT     Filter by location name fragment.
  --all               Process all matching incomplete video sessions.
  --list              List matching video sessions and exit.
  --dry-run           Print what would be run, but do not run it.
  --force             Force replacement of existing outputs at each stage.
  --help              Show this help.
EOF
}

log() {
  printf '[%s] %s\n' "$(date '+%H:%M:%S')" "$*"
}

die() {
  printf 'ERROR: %s\n' "$*" >&2
  exit 1
}

ENV_FILTER=""
SESSION_FILTER=""
BUILDING_FILTER=""
LOCATION_FILTER=""
PROCESS_ALL=0
LIST_ONLY=0
DRY_RUN=0
FORCE=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --environment|--env)
      ENV_FILTER="${2:-}"
      shift 2
      ;;
    --session)
      SESSION_FILTER="${2:-}"
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
    --all)
      PROCESS_ALL=1
      shift
      ;;
    --list)
      LIST_ONLY=1
      shift
      ;;
    --dry-run)
      DRY_RUN=1
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

SELECTED_JSON="$(
  ENV_FILTER="$ENV_FILTER" \
  SESSION_FILTER="$SESSION_FILTER" \
  BUILDING_FILTER="$BUILDING_FILTER" \
  LOCATION_FILTER="$LOCATION_FILTER" \
  PROCESS_ALL="$PROCESS_ALL" \
  LIST_ONLY="$LIST_ONLY" \
  python3 - "$ROOT_DIR" <<'PY'
import json
import os
import sqlite3
import sys
from pathlib import Path

root = Path(sys.argv[1])
map3d_dir = root / "map3d"
default_data = map3d_dir / "data"
env_root = default_data / "environments"

env_filter = (os.environ.get("ENV_FILTER") or "").strip()
session_filter = (os.environ.get("SESSION_FILTER") or "").strip()
building_filter = (os.environ.get("BUILDING_FILTER") or "").strip().lower()
location_filter = (os.environ.get("LOCATION_FILTER") or "").strip().lower()
process_all = os.environ.get("PROCESS_ALL") == "1"
list_only = os.environ.get("LIST_ONLY") == "1"


def env_dirs():
    if env_filter:
        if env_filter == "default":
            yield ("default", default_data)
            return
        yield (env_filter, env_root / env_filter)
        return
    if (default_data / "database.sqlite").exists():
        yield ("default", default_data)
    if env_root.exists():
        for child in sorted(env_root.iterdir(), key=lambda p: p.name):
            if child.is_dir() and (child / "database.sqlite").exists():
                yield (child.name, child)


def location_names(conn, session_id: int):
    rows = conn.execute(
        """
        SELECT DISTINCT l.name
        FROM observation o
        JOIN frame f ON f.id = o.frame_id
        JOIN asset a ON a.id = f.asset_id
        JOIN location l ON l.id = o.assigned_location_id
        WHERE a.session_id = ?
        ORDER BY l.name
        """,
        (session_id,),
    ).fetchall()
    return [row[0] for row in rows if row[0]]


def texture_ready(recon_dir: Path) -> bool:
    obj_path = recon_dir / "texturing" / "textured.obj"
    meta_path = recon_dir / "texturing" / "texture_meta.json"
    if not obj_path.exists() or not meta_path.exists():
        return False
    try:
        meta = json.loads(meta_path.read_text())
    except Exception:
        return False
    return int(meta.get("max_images", 0)) == 0


jobs = []
session_value = int(session_filter) if session_filter else None
for env_name, data_dir in env_dirs():
    db_path = data_dir / "database.sqlite"
    if not db_path.exists():
        continue
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        """
        SELECT
          s.id AS session_id,
          s.label AS label,
          s.source_type AS source_type,
          b.name AS building_name,
          SUM(CASE WHEN a.type = 'video' THEN 1 ELSE 0 END) AS video_count,
          SUM(CASE WHEN a.type = 'image' THEN 1 ELSE 0 END) AS image_count
        FROM session s
        JOIN building b ON b.id = s.building_id
        LEFT JOIN asset a ON a.session_id = s.id
        GROUP BY s.id, s.label, s.source_type, b.name
        HAVING video_count > 0
        ORDER BY s.id ASC
        """
    ).fetchall()
    for row in rows:
        session_id = int(row["session_id"])
        if session_value is not None and session_id != session_value:
            continue
        building_name = row["building_name"] or ""
        if building_filter and building_filter not in building_name.lower():
            continue
        locations = location_names(conn, session_id)
        if location_filter and not any(location_filter in name.lower() for name in locations):
            continue
        set_name = f"session_{session_id:04d}"
        set_dir = data_dir / "derived" / "reconstruction_sets" / set_name
        recon_dir = data_dir / "derived" / "reconstructions" / set_name
        prepared = (set_dir / "selection.json").exists() or (set_dir / "images").exists()
        reconstructed = any(
            child.is_dir() and ((child / "points3D.bin").exists() or (child / "points3D.txt").exists())
            for child in (recon_dir / "sparse").glob("*")
        ) if (recon_dir / "sparse").exists() else False
        dense_dir = recon_dir / "dense"
        dense_ready = any(
            path.exists()
            for path in (
                dense_dir / "meshed-web.ply",
                dense_dir / "meshed-delaunay.ply",
                dense_dir / "meshed-poisson.ply",
            )
        )
        textured_ready = texture_ready(recon_dir)
        if not prepared:
            next_stage = "prepare"
        elif not reconstructed:
            next_stage = "reconstruct"
        elif not dense_ready:
            next_stage = "dense"
        elif not textured_ready:
            next_stage = "texture"
        else:
            next_stage = "done"
        jobs.append({
            "environment": env_name,
            "data_dir": str(data_dir),
            "session_id": session_id,
            "label": row["label"] or set_name,
            "building": building_name,
            "locations": locations,
            "source_type": row["source_type"] or "",
            "video_count": int(row["video_count"] or 0),
            "image_count": int(row["image_count"] or 0),
            "prepared": prepared,
            "reconstructed": reconstructed,
            "dense_ready": dense_ready,
            "textured_ready": textured_ready,
            "next_stage": next_stage,
        })
    conn.close()

if list_only:
    print(json.dumps(jobs, indent=2))
    raise SystemExit(0)

jobs = [job for job in jobs if job["next_stage"] != "done"]
jobs.sort(key=lambda job: (job["environment"], job["session_id"]))
if not process_all and jobs:
    jobs = [jobs[0]]
print(json.dumps(jobs, indent=2))
PY
)"

if [[ "$LIST_ONLY" -eq 1 ]]; then
  printf '%s\n' "$SELECTED_JSON"
  exit 0
fi

JOB_COUNT="$(python3 - <<'PY' "$SELECTED_JSON"
import json, sys
data = json.loads(sys.argv[1])
print(len(data))
PY
)"

if [[ "$JOB_COUNT" -eq 0 ]]; then
  log "No incomplete video-backed sessions found."
  exit 0
fi

run_stage() {
  local -a cmd=("$@")
  if [[ "$DRY_RUN" -eq 1 ]]; then
    printf 'DRY-RUN:'
    printf ' %q' "${cmd[@]}"
    printf '\n'
    return 0
  fi
  "${cmd[@]}"
}

while IFS=$'\t' read -r env_name session_id building next_stage; do
  [[ -n "$session_id" ]] || continue
  log "Processing session ${session_id} in ${env_name} (${building})"
  log "Current next stage: ${next_stage}"

  ENV_ARGS=()
  if [[ "$env_name" != "default" ]]; then
    ENV_ARGS+=(--environment "$env_name")
  fi
  FORCE_ARGS=()
  [[ "$FORCE" -eq 1 ]] && FORCE_ARGS+=(--force)

  run_stage "$PREPARE_SCRIPT" "${ENV_ARGS[@]}" --session "$session_id" "${FORCE_ARGS[@]}"
  run_stage "$RECONSTRUCT_SCRIPT" "${ENV_ARGS[@]}" --session "$session_id" --skip-prepare "${FORCE_ARGS[@]}"
  run_stage "$DENSE_SCRIPT" "${ENV_ARGS[@]}" --session "$session_id" "${FORCE_ARGS[@]}"
  run_stage "$TEXTURE_SCRIPT" "${ENV_ARGS[@]}" --session "$session_id" "${FORCE_ARGS[@]}"
done < <(
  python3 - <<'PY' "$SELECTED_JSON"
import json, sys
for job in json.loads(sys.argv[1]):
    print(f"{job['environment']}\t{job['session_id']:04d}\t{job['building']}\t{job['next_stage']}")
PY
)
