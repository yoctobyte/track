# TRACK

`TRACK` is an umbrella project for technical documentation, inventory,
spatial mapping, and operational control across real-world environments.

The acronym currently in use is:

**Technical Resource And Control Knowledge Kit**

## Core Idea

`TRACK` is not one monolithic application.

It is a coordinated set of subprojects that should remain:

- independently runnable
- independently useful
- independently deployable

At the same time, they should gradually share:

- common locations
- common tags
- shared navigation
- shared environmental context
- eventually, selected authentication and metadata services

The umbrella should integrate subprojects, not dissolve them.

## Current Subprojects

### `map3d/`

Spatial capture and 3D reconstruction.

Current focus:

- browser-based photo capture
- location-aware archival image storage
- COLMAP-based sparse reconstruction
- early HTML viewer
- dense reconstruction pipeline experiments

### `museumcontrol/`

Museum kiosk and device control dashboard.

Current focus:

- Tailscale-aware host discovery
- kiosk status and metadata
- secure proxy access
- operator-facing control UI

### `netinventory/`

Network observation and field inventory tooling.

Current focus:

- local network probing
- observation persistence
- task runtime
- user context
- sync/export workflows

## Project Structure

This repository is now the canonical `track` repo.

Imported subprojects keep their own history inside this repo.

That means:

- `museumcontrol/` history was preserved
- `netinventory/` history was preserved
- `map3d/` remains an actively developed subproject in the root repo

## Current Integration Strategy

For now, each subproject remains self-contained.

Near-term umbrella work should focus on:

1. a root identity and documentation layer
2. a root landing interface
3. shared concepts such as environment, location, and tags
4. thin integration seams between subprojects

Not yet:

- one merged database
- one merged codebase
- one forced Flask application

## Important Root Documents

- [GOALS.md](./GOALS.md)
- [PROGRESS.md](./PROGRESS.md)
- [ARCHITECTURE.md](./ARCHITECTURE.md)
- [STATE.md](./STATE.md)
- [philosophy/TRACK_PHILOSOPHY.md](./philosophy/TRACK_PHILOSOPHY.md)
- [ARCHITECTURAL_FEEDBACK.md](./ARCHITECTURAL_FEEDBACK.md)

## Guiding Rule

`TRACK` integrates subprojects; it does not swallow them.
