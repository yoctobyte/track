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

Run it standalone from the repository root:

```bash
./netinventory-client.sh
```

It is intentionally not part of the TRACK umbrella UI or autostart plan. An
admin can run it on any laptop, keep it in the foreground for privileged
operations, then configure sync/upload toward the public NetInventory host for
the chosen environment. The launcher opens the local web UI in a browser when
possible; set `NETINVENTORY_OPEN_BROWSER=0` to disable that.

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
- provide a lightweight browser-and-script registration path for ordinary devices
- publish user-mode and admin-mode lightweight collectors for Linux and Windows
- centralize web-facing network inventory workflows

### `netinventory-simple/`

Client-side lightweight registration assets for NetInventory.

Current focus:

- isolated user-mode and admin-mode `.sh` / `.bat` collector templates
- room for future binary or packaged collectors
- no standalone server runtime

### `devicecontrol/`

Ansible-backed operational control kit.

Current focus:

- environment-separated Ansible inventories
- manual host bootstrap helpers
- approved maintenance playbooks
- web-triggered runs with logs and fetched screenshots

### `quicktrack/`

Fast photo observation capture.

Current focus:

- timestamped photo submissions
- optional description and sender ID
- explicit GPS capture only after pressing the location button
- local JSON/photo storage ready for later TrackSync artifact handling

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

- [INSTALL.md](./INSTALL.md)
- [GOALS.md](./GOALS.md)
- [PROGRESS.md](./PROGRESS.md)
- [ARCHITECTURE.md](./ARCHITECTURE.md)
- [STATE.md](./STATE.md)
- [GITHUB_PROJECT.md](./GITHUB_PROJECT.md)
- [philosophy/TRACK_PHILOSOPHY.md](./philosophy/TRACK_PHILOSOPHY.md)
- [ARCHITECTURAL_FEEDBACK.md](./ARCHITECTURAL_FEEDBACK.md)

## Guiding Rule

`TRACK` integrates subprojects; it does not swallow them.
