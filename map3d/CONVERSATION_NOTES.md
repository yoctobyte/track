# map3d — Conversation Notes

This file captures relevant conclusions from external design conversations so
they remain visible inside the repo for future work.

## 2026-04-15 — TRACK environment isolation

`map3d` is now expected to run with strict data separation per TRACK
environment.

Current intended instance layout:

- `testing`: `http://127.0.0.1:5001/`, data root `map3d/data`
- `museum`: `http://127.0.0.1:5011/`, data root `map3d/data/environments/museum`
- `lab`: `http://127.0.0.1:5012/`, data root `map3d/data/environments/lab`

The reason is operational security: home/testing captures, museum captures,
previews, reconstructions, and SQLite state must not leak across environments.

Implementation note:

- Prefer separate `map3d` processes with separate `MAP3D_DATA_DIR` values.
- Avoid a single shared database with only UI-level filters unless there is a
  strong reason and full query-level enforcement.
- Public routing can still use the same `/map3d/` path because TRACK Hub chooses
  the backend based on the authenticated environment.

## 2026-04-12 — Shared conversation: "Photo Stitching Tools"

Source:

- https://chatgpt.com/share/69dbc98d-e394-8396-8805-e6a5372245d5

### What seems relevant to map3d

- The project direction is not "panorama stitching" in the narrow sense.
  The stronger match is:
  - structure-from-motion
  - photogrammetry
  - camera pose estimation
  - 3D scene reconstruction
  - later possibly NeRF / Gaussian-splatting-style rendering

- The target outcome is:
  - 3D point cloud / sparse model
  - camera positions
  - photos placed in space
  - a view where you can click a photo and understand where it was taken

- Change-over-time is explicitly compatible with that direction.
  The shared conversation pointed toward:
  - keeping a baseline model
  - aligning new photo sets against it
  - looking for geometry differences / mismatches / missing regions
  - supporting renovation and movement tracking

- AprilTags / QR-like anchors were reinforced as useful, especially indoors.
  Not mandatory, but potentially powerful for:
  - alignment
  - anchor points
  - indoor reconstruction stability

- A practical first pilot for actual 3D work was suggested:
  - one room
  - roughly 80–150 photos
  - run through COLMAP first
  - goal: recover camera positions and a usable sparse reconstruction

- Scaling guidance from that conversation:
  - small house: 500–1500 photos
  - large house: 2000–5000 photos
  - museum floor: 5000–15000 photos
  - full museum: 20000+ photos
  This is not a hard requirement, just rough expectation-setting.

### Important distinction captured in that conversation

- Classic panorama stitching:
  - Hugin
  - enblend / enfuse
  - OpenCV homography-based stitching
  - mostly CPU-friendly
  - useful for panoramas, not the main target of map3d

- map3d-relevant direction:
  - COLMAP
  - Meshroom
  - Open3D / CloudCompare for inspection
  - later custom web viewer / three.js / Potree-like visualization
  - oriented around spatial recovery, not just image stitching

### UI / workflow ideas reinforced there

- Smartphone-first data collection still makes sense.
- Burst capture is important.
- Uploading existing photos should remain supported.
- Hierarchical manual locations remain useful even if later inference exists.
- Sticky location selection is a strong workflow idea:
  once a user selects a building/location chain, captures should continue using
  that assignment until changed.

### Current interpretation for planning

This conversation strengthens the idea that map3d should be planned as:

- an archival capture system
- feeding an approximate 3D virtual space
- with time as an additional axis for repeated documentation

So the next phases should not treat gallery/archive features as the end state.
They should progressively bridge:

1. archived observations
2. image-to-image relationships
3. camera pose / spatial placement
4. rough 3D model
5. temporal comparison inside the same spatial context

### Caution

The shared conversation included useful technical direction, but it was still a
high-level design discussion, not a validated implementation plan. Tool choice
and pipeline details should still be tested against the actual data you collect.
