#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DB_PATH="$ROOT_DIR/map3d/data/database.sqlite"
OUTPUT_BASE="$ROOT_DIR/map3d/data/derived/reconstruction_sets"
MODE="latest-run"
NAME=""
BUILDING_ID=""
FROM_SESSION=""
TO_SESSION=""
MAX_GAP_SEC="180"
LINK_MODE="symlink"
FORCE=0

usage() {
  cat <<'EOF'
Usage:
  ./map3d-collect-reconstruction-set.sh
  ./map3d-collect-reconstruction-set.sh --name home-burst-a
  ./map3d-collect-reconstruction-set.sh --from-session 0092 --to-session 0121 --name home-pass

Options:
  --name NAME          Output set name.
  --building-id ID     Limit selection to one building id.
  --from-session ID    Start at this session id.
  --to-session ID      End at this session id.
  --max-gap-sec N      For latest-run mode, keep walking backward while the
                       time gap between captures stays within N seconds.
                       Default: 180
                       Note: the earlier default of 15 was too tight for
                       real-world capture — people pause to reframe, check
                       the viewfinder, or reposition for longer than that.
                       180 still excludes a true session break and captures
                       a realistic "one walk" slice.
  --copy               Copy files instead of symlinking them.
  --force              Replace an existing set directory.
  --help               Show this help.

Default behavior:
  Build a reconstruction set from the latest contiguous capture run, based on
  recent session timestamps and building continuity.
EOF
}

log() {
  printf '\n[%s] %s\n' "$(date '+%H:%M:%S')" "$*"
}

die() {
  printf '\nERROR: %s\n' "$*" >&2
  exit 1
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --name)
      NAME="${2:-}"
      shift 2
      ;;
    --building-id)
      BUILDING_ID="${2:-}"
      shift 2
      ;;
    --from-session)
      FROM_SESSION="${2:-}"
      shift 2
      ;;
    --to-session)
      TO_SESSION="${2:-}"
      shift 2
      ;;
    --max-gap-sec)
      MAX_GAP_SEC="${2:-}"
      shift 2
      ;;
    --copy)
      LINK_MODE="copy"
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

[[ -f "$DB_PATH" ]] || die "Database not found: $DB_PATH"
mkdir -p "$OUTPUT_BASE"

if [[ -n "$FROM_SESSION" || -n "$TO_SESSION" ]]; then
  MODE="session-range"
  [[ -n "$FROM_SESSION" && -n "$TO_SESSION" ]] || die "Use --from-session and --to-session together."
fi

RESULT="$(
ROOT_DIR="$ROOT_DIR" DB_PATH="$DB_PATH" BUILDING_ID="$BUILDING_ID" FROM_SESSION="$FROM_SESSION" TO_SESSION="$TO_SESSION" MAX_GAP_SEC="$MAX_GAP_SEC" MODE="$MODE" python3 <<'PY'
import json
import os
import sqlite3
from collections import Counter
from datetime import datetime

root = os.environ["ROOT_DIR"]
db_path = os.environ["DB_PATH"]
mode = os.environ["MODE"]
building_id = os.environ["BUILDING_ID"].strip()
from_session = os.environ["FROM_SESSION"].strip()
to_session = os.environ["TO_SESSION"].strip()
max_gap_sec = float(os.environ["MAX_GAP_SEC"])

conn = sqlite3.connect(db_path)
conn.row_factory = sqlite3.Row

rows = conn.execute(
    """
    select
      a.id as asset_id,
      s.id as session_id,
      s.building_id,
      b.name as building_name,
      s.start_time,
      a.storage_path
    from session s
    join asset a on a.session_id = s.id
    left join building b on b.id = s.building_id
    where a.storage_path is not null
    order by s.id desc
    """
).fetchall()

def parse_ts(value: str):
    return datetime.fromisoformat(value.replace(" ", "T"))

selected = []

if mode == "session-range":
    lo = int(from_session)
    hi = int(to_session)
    if lo > hi:
        lo, hi = hi, lo
    for row in rows:
        sid = int(row["session_id"])
        if lo <= sid <= hi:
            if building_id and int(row["building_id"]) != int(building_id):
                continue
            selected.append(row)
    selected.sort(key=lambda r: int(r["session_id"]))
else:
    eligible_rows = []
    for row in rows:
        if building_id and int(row["building_id"]) != int(building_id):
            continue
        eligible_rows.append(row)
    anchor = eligible_rows[0] if eligible_rows else None
    if anchor is None:
        print(json.dumps({"error": "No eligible sessions found"}))
        raise SystemExit
    anchor_building = int(anchor["building_id"])
    anchor_sid = int(anchor["session_id"])
    session_counts = Counter(int(r["session_id"]) for r in eligible_rows)

    if session_counts[anchor_sid] > 1:
        selected = [r for r in eligible_rows if int(r["session_id"]) == anchor_sid]
        selected.sort(key=lambda r: int(r["asset_id"]))
    else:
        selected.append(anchor)
        prev_ts = parse_ts(anchor["start_time"])
        prev_sid = anchor_sid
        for row in eligible_rows[1:]:
            sid = int(row["session_id"])
            if int(row["building_id"]) != anchor_building:
                break
            ts = parse_ts(row["start_time"])
            gap = abs((prev_ts - ts).total_seconds())
            if gap > max_gap_sec:
                break
            if sid != prev_sid - 1:
                break
            selected.append(row)
            prev_ts = ts
            prev_sid = sid
        selected.sort(key=lambda r: int(r["session_id"]))

if not selected:
    print(json.dumps({"error": "No sessions selected"}))
    raise SystemExit

result = {
    "mode": mode,
    "building_id": int(selected[0]["building_id"]),
    "building_name": selected[0]["building_name"] or f"building_{selected[0]['building_id']}",
    "session_ids": [int(r["session_id"]) for r in selected],
    "storage_paths": [r["storage_path"] for r in selected],
    "count": len(selected),
    "first_session": int(selected[0]["session_id"]),
    "last_session": int(selected[-1]["session_id"]),
    "first_time": selected[0]["start_time"],
    "last_time": selected[-1]["start_time"],
}
print(json.dumps(result))
PY
)"

python3 - <<'PY' "$RESULT" >/dev/null
import json, sys
data = json.loads(sys.argv[1])
if "error" in data:
    raise SystemExit(1)
PY
if [[ $? -ne 0 ]]; then
  die "$(python3 - <<'PY' "$RESULT"
import json, sys
data = json.loads(sys.argv[1])
print(data.get("error", "Unknown collector error"))
PY
)"
fi

if [[ -z "$NAME" ]]; then
  NAME="$(python3 - <<'PY' "$RESULT"
import json, sys
data = json.loads(sys.argv[1])
print(f"{data['building_name'].lower().replace(' ', '-')}_s{data['first_session']:04d}-s{data['last_session']:04d}")
PY
)"
fi

SET_DIR="$OUTPUT_BASE/$NAME"
IMAGES_DIR="$SET_DIR/images"
MANIFEST_PATH="$SET_DIR/manifest.tsv"

if [[ -e "$SET_DIR" ]]; then
  if [[ "$FORCE" -eq 1 ]]; then
    rm -rf "$SET_DIR"
  else
    die "Set directory already exists: $SET_DIR (use --force to replace it)"
  fi
fi

mkdir -p "$IMAGES_DIR"

log "Collecting reconstruction set"
log "Mode: $MODE"
log "Output set: $SET_DIR"
log "Image link mode: $LINK_MODE"

ROOT_DIR="$ROOT_DIR" SET_DIR="$SET_DIR" IMAGES_DIR="$IMAGES_DIR" MANIFEST_PATH="$MANIFEST_PATH" LINK_MODE="$LINK_MODE" RESULT="$RESULT" python3 <<'PY'
import json
import os
import pathlib
import shutil

root = pathlib.Path(os.environ["ROOT_DIR"])
set_dir = pathlib.Path(os.environ["SET_DIR"])
images_dir = pathlib.Path(os.environ["IMAGES_DIR"])
manifest_path = pathlib.Path(os.environ["MANIFEST_PATH"])
link_mode = os.environ["LINK_MODE"]
data = json.loads(os.environ["RESULT"])

# Skip zero-byte and missing images. Early in the project a handful of capture
# attempts wrote an empty file (the filename prefix of which is the SHA256 of
# the empty string, e3b0c44298fc...). COLMAP segfaults on empty inputs, so we
# just filter them here rather than cleaning up historical data.
skipped = []
with manifest_path.open("w", encoding="utf-8") as f:
    f.write("index\tsession_id\tstorage_path\tfilename\n")
    index = 0
    for sid, storage_path in zip(data["session_ids"], data["storage_paths"]):
        src = root / "map3d" / "data" / storage_path
        if not src.exists() or src.stat().st_size == 0:
            skipped.append((sid, storage_path))
            continue
        index += 1
        dest = images_dir / f"{index:04d}_s{sid:04d}_{src.name}"
        if link_mode == "copy":
            shutil.copy2(src, dest)
        else:
            dest.symlink_to(src)
        f.write(f"{index}\t{sid}\t{storage_path}\t{dest.name}\n")

if skipped:
    print(f"[collector] skipped {len(skipped)} empty/missing images:")
    for sid, sp in skipped:
        print(f"  s{sid:04d}  {sp}")
    data["skipped_count"] = len(skipped)
    data["count"] = index

meta = set_dir / "selection.json"
meta.write_text(json.dumps(data, indent=2), encoding="utf-8")
PY

COUNT="$(python3 - <<'PY' "$RESULT"
import json, sys
print(json.loads(sys.argv[1])["count"])
PY
)"
FIRST_LAST="$(python3 - <<'PY' "$RESULT"
import json, sys
d = json.loads(sys.argv[1])
print(f"sessions {d['first_session']:04d}..{d['last_session']:04d}")
PY
)"

log "Collected images: $COUNT"
log "Selection: $FIRST_LAST"
log "Images directory: $IMAGES_DIR"
log "Manifest: $MANIFEST_PATH"
log "Next command:"
printf '  ./map3d-reconstruct.sh --images %q --name %q\n' "$IMAGES_DIR" "$NAME"
