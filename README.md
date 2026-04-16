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

### `netinventory-client/`

Laptop-side network observation and field inventory tooling.

Current focus:

- local network probing
- observation persistence
- task runtime
- user context
- sync/export workflows

### `netinventory-host/`

Host-side intake and publishing surface for NetInventory.

Current focus:

- receive and later aggregate client/host reports
- publish client downloads and bootstrap entrypoints
- centralize web-facing network inventory workflows

### `devicecontrol/`

Ansible-backed operational control kit.

Current focus:

- environment-separated Ansible inventories
- manual host bootstrap helpers
- approved maintenance playbooks
- web-triggered runs with logs and fetched screenshots

## Project Structure

This repository is now the canonical `track` repo.

Imported subprojects keep their own history inside this repo.

That means:

- `museumcontrol/` history was preserved
- `netinventory-client/` history was preserved
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

## Central Runtime Configuration

TRACK now keeps per-environment subservice launch parameters in
`trackhub/config.json`.

That central config decides:

- which environments exist
- which subprojects are exposed in each environment
- which app instances autostart on the current workstation
- which environment variables are injected into generic subservice launchers

Useful root tools:

- `./track.sh`
  - start the umbrella plus configured autostart subservices
- `./track-configure.py list`
  - inspect current environments, apps, and launch plan
- `./track-configure.py validate`
  - validate configured launch script targets

## Important Root Documents

- [GOALS.md](./GOALS.md)
- [PROGRESS.md](./PROGRESS.md)
- [ARCHITECTURE.md](./ARCHITECTURE.md)
- [STATE.md](./STATE.md)
- [GITHUB_PROJECT.md](./GITHUB_PROJECT.md)
- [philosophy/TRACK_PHILOSOPHY.md](./philosophy/TRACK_PHILOSOPHY.md)
- [ARCHITECTURAL_FEEDBACK.md](./ARCHITECTURAL_FEEDBACK.md)

## Guiding Rule

`TRACK` integrates subprojects; it does not swallow them.
