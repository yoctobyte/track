# Track — Progress Log

## 2026-04-12 — map3d Phase 3 first light: COLMAP reconstruction working

First real 3D reconstruction produced from captured phone data.

### What runs now

Two shell scripts at the repo root drive the pipeline:

- `map3d-collect-reconstruction-set.sh`
    - Queries `map3d/data/database.sqlite` to pull a contiguous run of
      recent captures (by building + time-gap walk) into
      `map3d/data/derived/reconstruction_sets/<name>/images/` as symlinks.
    - Skips zero-byte images (one empty file in session_0005 used to
      segfault COLMAP's feature extractor).
    - Writes a `manifest.tsv` + `selection.json` next to the images.
    - Default `--max-gap-sec` bumped from 15 to 180 — realistic human
      pauses between captures exceed 15s.

- `map3d-reconstruct.sh`
    - Prefers the locally built CUDA COLMAP:
        1. `colmap-cuda` on PATH (when the local .deb is installed),
        2. the in-tree binary at
           `tmp-colmap-build/pkgroot/opt/colmap-cuda/bin/colmap`,
        3. system `colmap` (CPU fallback).
    - Runs feature extraction → exhaustive matching → sparse mapping.
    - Uses a tuned parameter set that actually finishes on phone captures
      (see "Parameter notes" below).

### Known-good run on current data

Input: 69-image symlinked set `full-walk` built from sessions 53..121 at
"Home", captured as a ~5-minute walking pass.

Pipeline time on GTX 1660 (6 GB):

- feature extraction: 0.5 min
- exhaustive matching: 0.4 min
- sparse mapping: 0.4 min

Output: two sparse models

| Model | Cameras | Images | Points | Reproj error |
|-------|---------|--------|--------|--------------|
| 0     | 1       | 35     | 15866  | 0.73 px      |
| 1     | 1       | 17     | 2754   | 0.77 px      |

52 of 69 images registered. Both models have a single shared camera
intrinsic (single-camera mode is the default — one user, one phone per
capture set).

### Parameter notes (why the tuned values matter)

The out-of-box COLMAP defaults produce **zero sparse models** on this
dataset. Three settings had to change:

1. `Mapper.init_min_tri_angle` 16 → **4** degrees.
   This is the biggest fix. The default rejects any initial image pair
   with less than 16° of parallax. A phone walking outdoors has small
   baselines relative to subject distance, so every candidate pair gets
   rejected and the mapper gives up. 4° is enough to bootstrap.

2. `FeatureMatching.max_num_matches` 32768 → **16384** + `num_threads 1`.
   The GTX 1660 has 6 GB VRAM; our busiest images produce ~26k features.
   The default max_num_matches and parallel matchers OOM the GPU. Halving
   the matches and serializing workers fits within VRAM.

3. `ImageReader.single_camera` 0 → **1**.
   Every frame in a capture set comes from the same phone, so solving one
   shared intrinsic is both more accurate and faster than per-image
   intrinsics.

Secondary relaxations (init_min_num_inliers 100→50,
abs_pose_min_num_inliers 30→20, min_model_size 10→5, multiple_models 1)
help surface small but usable sub-reconstructions when parts of a walk
don't overlap cleanly with the main model.

Also: `estimate_affine_shape` and `domain_size_pooling` were tried and
removed — both force COLMAP onto the CPU SIFT path and negate the point
of using colmap-cuda.

### CUDA COLMAP build

`tmp-colmap-build/` holds a locally rebuilt CUDA-enabled COLMAP 4.1:

- deb: `colmap-cuda-local_4.1.0~cuda12.8-1_amd64.deb` (22 MB, installable
  with `sudo dpkg -i`)
- pkgroot: the extracted tree; the reconstruct script runs the binary
  directly from here when `colmap-cuda` is not on PATH, so installation
  is optional.

The directory is gitignored — it's a build artifact, not repo content.

### Next for Phase 3

1. Install the colmap-cuda deb globally (`sudo dpkg -i ...`) so
   `colmap-cuda` is on PATH and the fallback can go away.
2. **Capture a deliberate reconstruction set.** 52/69 registered from a
   casual walk is fine for a first light, but room-scale reconstruction
   wants denser, more deliberate capture — overlap per pair, slow pan,
   cover each subject from multiple angles. Use the capture page.
3. Dense reconstruction: `image_undistorter` → `patch_match_stereo` →
   `stereo_fusion`. Currently the script stops at sparse.
4. Model import into the Flask app: surface camera poses and sparse
   points alongside the gallery frames so clicking a frame shows where
   it sits in space.
5. AprilTag anchors: the DB has `apriltag_detections` already but the
   detector isn't wired. Once wired, detected tags give absolute anchor
   points that can stitch disjoint sparse models together.

## 2026-04-12 — map3d initial build and UI polish

### Session summary

Built the map3d subproject from scratch in a single session. Started with
a Flask vs FastAPI comparison (demos kept in demo/ for reference), chose
Flask for its cleaner fit with server-rendered UI. Implemented the full
Phase 1 data model, ingest pipeline, and web interface.

### What exists now

**Backend (Flask + SQLAlchemy + SQLite):**

- Data model: Building, Location (hierarchical, with indoor/outdoor
  environment), Session, Asset, Frame (with sensor_json), Observation,
  AprilTag, AprilTagDetection
- File storage: originals preserved immutably per session, SHA256 hashed,
  previews generated as JPEG thumbnails
- Ingest pipeline: receive file > hash > store > extract EXIF > generate
  preview > create records, single-pass
- Metadata extraction: EXIF via Pillow, timestamp recovery from multiple
  date fields

**API endpoints:**

- GET  /api/buildings — list all
- GET  /api/buildings/nearest?lat=&lon= — geo-match to find which building
- POST /api/buildings/resolve — find or create by name (case-insensitive)
- GET  /api/buildings/<id>/locations — list with effective_environment
- POST /api/buildings/<id>/locations/resolve — find or create by name
- GET  /api/locations/<id>/children
- POST /api/capture — accept image + sensor data from browser capture

**Web UI (dark theme — purple/pink/neon/70s-brown palette):**

- Buildings page: create with name, GPS coords ("use my location" button),
  geo-radius. Table shows coordinates.
- Building detail: location tree showing name, type, effective environment
  (indoor/outdoor). Add location with type, environment (auto/indoor/outdoor),
  parent selection. Delete empty leaf locations.
- Capture page:
  - Browser camera via getUserMedia (rear camera default, switchable)
  - Permission banner: single button requests camera + geolocation + motion
    sensors. Shows per-permission status (granted/denied/n/a). Handles iOS 13+
    DeviceOrientation/DeviceMotion permission API.
  - Sensor readout: orientation, accelerometer, gyroscope, geolocation,
    magnetometer, barometer — all displayed live, snapshot stored with each capture
  - GPS auto-detects building on page load
  - Combo-box inputs: type existing name (case-insensitive match) or type new
    name (created automatically on capture)
- Upload page: multi-file upload with same combo-box building/location inputs.
  New buildings/locations created inline on submit.
- Gallery: thumbnail grid, filter by building and session
- Frame detail: preview image, link to original, file info table, sensor data
  table, EXIF metadata table, location assignment/correction dropdown

**Infrastructure:**

- run.sh launcher: auto-creates venv, installs deps, kills existing instance,
  starts Flask on configurable host/port
- map3d.sh convenience wrapper in project root
- .gitignore: covers venvs, pycache, data dirs, IDE files, secrets
- GOALS.md: project vision, phases, design decisions
- Git repo initialized at track/ root level

### Architecture notes for next developer

- App factory pattern in app/__init__.py — blueprints for locations, upload,
  gallery, capture, api
- Models in app/models.py — Location.effective_environment is a property that
  walks the parent chain to resolve "auto"
- Ingest in app/ingest.py — single function ingest_image() does the full pipeline
- Storage paths are relative to data/ dir, served via /data/<path> route
- Sensor data stored as JSON on Frame.sensor_json — schema is whatever the
  browser provides, no strict validation
- Building/location resolve endpoints do case-insensitive lookup, create if
  not found — used by capture and upload JS to allow free-text entry

### Known gaps / next priorities

1. **HTTPS** — phone camera and sensor APIs require secure context over
   network. Localhost works for desktop testing. Need self-signed cert or
   reverse proxy for phone testing on LAN.
2. **AprilTag detection** — schema and model ready, detector not wired.
   Needs pupil-apriltags or similar library.
3. **Burst capture** — timed repeated capture from browser camera. UI and
   backend ready for it (just loop the capture call with a timer).
4. **Video import** — frame extraction pipeline not built yet.
5. **Clipboard paste** — upload from paste not wired yet.
6. **Phase 2** — visual similarity, duplicate detection, location suggestions.
7. **Phase 3** — 3D reconstruction, camera pose estimation.
8. **Phase 4** — time variation tracking.

### How to run

```bash
cd /home/rene/track
./map3d.sh
# or
cd /home/rene/track/map3d
./run.sh
```

Server starts on http://0.0.0.0:5000 by default. Set MAP3D_PORT or
MAP3D_HOST env vars to change.
