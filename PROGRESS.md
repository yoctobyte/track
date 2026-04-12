# Track — Progress Log

## 2026-04-12 — map3d initial build

### Completed

- Project structure: Flask app with blueprints, SQLAlchemy + SQLite
- Full data model implemented:
  - Building (with GPS coordinates and geo-radius for auto-detection)
  - Location (hierarchical, with indoor/outdoor environment field)
  - Session (capture batches)
  - Asset (original files)
  - Frame (individual observations with metadata + sensor data)
  - Observation (location assignments, correctable)
  - AprilTag + AprilTagDetection (schema ready, detection not wired)
- File storage manager: originals preserved by session, SHA256 hashed
- Metadata extraction: EXIF parsing via Pillow, timestamp recovery
- Preview generation: JPEG thumbnails at 800px
- Ingest pipeline: hash > store > extract > preview > record, single pass
- Web UI:
  - Buildings page: create with GPS, "use my location" button
  - Building detail: location tree with types and environment display
  - Location CRUD: add/edit/delete with hierarchy, type, environment
  - Upload page: multi-file upload with building/location selection
  - Capture page: browser camera via getUserMedia, full sensor readout
    (orientation, accelerometer, gyroscope, geolocation, magnetometer,
    barometer), sensor snapshot stored with each capture
  - Gallery: thumbnail grid, filter by building/session
  - Frame detail: preview, original link, file info, sensor data,
    EXIF metadata, location assignment/correction
- API endpoints:
  - GET /api/buildings
  - GET /api/buildings/nearest?lat=&lon= (geo-matching)
  - GET /api/buildings/<id>/locations (includes effective_environment)
  - GET /api/locations/<id>/children
  - POST /api/capture (image + sensor data from browser)
- GPS auto-detection of building on capture page
- Indoor/outdoor environment: auto-inferred from location type, inherits
  from parent, manually overridable
- Flask vs FastAPI comparison demos (in demo/ for reference)

### Not yet implemented

- HTTPS (needed for phone camera/sensor access over network)
- AprilTag detection (schema ready, detector not wired)
- Video import and frame extraction
- Burst capture mode (timed repeated capture)
- Visual similarity matching
- 3D reconstruction pipeline
- Time comparison / change detection
- Clipboard paste upload
