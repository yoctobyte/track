# Track — Progress Log

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
