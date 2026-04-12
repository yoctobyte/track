# Track — Project Goals

## Vision

A unified system for inventory, notes, technical documentation, and spatial
mapping across multiple physical locations. Each location (home, museum,
locatiewageningen, etc.) is its own project/context, but they share tooling
and eventually glue together.

## Subprojects

Subprojects live as subdirectories under `track/`. Some may have originated
as independent repos and will be integrated over time.

### map3d — Building Photo Archive and Spatial Mapping

Document buildings using smartphone photos, store them with structured
location metadata, and gradually evolve from manual tagging to automatic
spatial mapping and change-over-time comparison.

**Core principle:** Every media item is first a durable archival observation,
and only later material for inference, mapping, and change detection. The
system must be useful from day one with just manual location labels.

### Future subprojects (planned)

- **Network inventory** — making sense of seemingly randomly wired switches
- **Device management** — Ansible-controlled devices, some with web interfaces
- **Notes/documentation** — technical documentation tied to locations and devices

## Integration Strategy

- Each subproject is self-contained and independently useful
- Shared concept: top-level **location** (home, museum, locatiewageningen)
- Glue layer comes later — API-based integration between subprojects
- No premature coupling; build solid building blocks first

## User Context

- Multiple physical sites to document and manage
- Mix of IT infrastructure, physical spaces, and equipment
- Existing partial solutions (web interfaces, ansible playbooks, network maps)
- Goal is to unify without breaking what already works

---

## map3d — Detailed Goals

### Phase 1: Structured Capture and Archive (current)

- Hierarchical location model (building > floor > room > cabinet etc.)
- Photo upload (single, multi-file) and browser-based capture
- Capture phone sensor data at photo time (accelerometer, gyroscope,
  orientation, GPS, magnetometer, barometer)
- GPS-based auto-detection of which building you're at
- Indoor/outdoor environment classification (auto-inferred from location
  type, manually overridable)
- Original file preservation with SHA256 identity
- EXIF metadata extraction and storage
- Preview/thumbnail generation
- Manual and correctable location assignment
- Web interface for browsing, filtering, and correcting
- Session-based organization of capture batches
- AprilTag detection support (stubbed, ready to wire up)

### Phase 2: Assisted Spatial Grouping

- Visual similarity matching between images
- Related-image suggestions
- Room-level clustering
- Duplicate detection
- Probable location suggestions for unlabeled images

### Phase 3: 3D Mapping

- Feature extraction and image matching
- Camera pose estimation (using sensor data as hints)
- Sparse reconstruction (indoor strategy vs outdoor strategy)
- Optional dense reconstruction
- Spatial viewer
- Use GPS seeds for outdoor, AprilTags + features for indoor

### Phase 4: Time Variation Tracking

- Repeated sessions at same location
- Before/after comparison
- Viewpoint matching across visits
- Likely changed-region detection
- Per-location timeline

## Design Decisions

- **Flask** over FastAPI — cleaner for server-rendered web app, trivial to
  refactor later if needed. Both were prototyped and compared side-by-side.
- **SQLite** for database — sufficient for thousands of images, migration
  path to PostgreSQL via SQLAlchemy
- **Raw file storage** on disk — originals immutable, previews regenerable
- **No custom mobile app** — browser-based capture with getUserMedia and
  sensor APIs, requires HTTPS for phone access
- **Sensor data captured at photo time** — orientation, accelerometer, gyro,
  GPS, magnetometer, barometer. Stored as JSON on each frame. Valuable for
  Phase 3 reconstruction.
- **Indoor/outdoor auto-detection** — inferred from location type hierarchy,
  overridable. Affects reconstruction strategy in Phase 3.
