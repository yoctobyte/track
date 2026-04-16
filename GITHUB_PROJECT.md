# GitHub Project Seed

This repository is already structured like an umbrella project. The GitHub side
should reflect that instead of flattening everything into one feature bucket.

## Recommended Project Name

`TRACK Umbrella`

## Recommended Views

### 1. Board View: Delivery

Columns:

- `Inbox`
- `Ready`
- `In Progress`
- `Blocked`
- `Review`
- `Done`

Use this for active engineering work.

### 2. Table View: Subproject

Suggested fields:

- `Subproject`
- `Type`
- `Environment`
- `Priority`
- `Status`
- `Milestone`

Suggested `Subproject` options:

- `trackhub`
- `devicecontrol`
- `map3d`
- `museumcontrol`
- `netinventory`
- `umbrella`

Suggested `Type` options:

- `bug`
- `feature`
- `design`
- `docs`
- `ops`

### 3. Roadmap View: Milestones

Use GitHub milestones for the major tracks:

- `Umbrella Shell`
- `Device Operations`
- `3D Capture And Reconstruction`
- `Network Observation`
- `Museum Control`
- `Documentation And Philosophy`

## Suggested Labels

Core labels:

- `bug`
- `enhancement`
- `design`
- `docs`
- `ops`
- `security`

Subproject labels:

- `trackhub`
- `devicecontrol`
- `map3d`
- `museumcontrol`
- `netinventory`
- `umbrella`

State labels:

- `blocked`
- `needs-decision`
- `good-first-issue`

## Suggested First Issues

These are good seed items for the first public-facing project board.

### Umbrella

1. Document the canonical TRACK deployment topology
2. Define shared environment/location vocabulary across subprojects
3. Add a published contribution workflow for subprojects inside the umbrella

### DeviceControl

1. Stabilize screenshots across GNOME Wayland and Openbox/X11
2. Add scheduled polling jobs for stats and screenshots with retention
3. Build screenshot overview page with latest host captures
4. Add device timeline views for reboot, outage, and display-state events

### map3d

1. Formalize capture runs and burst grouping in the data model
2. Improve reconstruction set discovery across overlapping sessions
3. Add dense reconstruction viewer support and retention controls

### netinventory

1. Package downloadable field client workflows from the hub
2. Unify field observations with TRACK environment context
3. Define import path for locally collected privileged network data

### museumcontrol

1. Align styling and navigation with the umbrella shell
2. Clarify location-aware authentication and data separation

## Suggested Project Rhythm

- Use issues for concrete work items.
- Use design notes for architecture choices before implementation.
- Keep cross-project work under `umbrella` unless one subproject clearly owns it.
- Prefer milestones over giant meta-issues.

## Important Rule

The GitHub project should mirror the real structure of TRACK:

- umbrella at the top
- subprojects remain independently legible
- integration work stays explicit

Do not turn the board into a single undifferentiated backlog.
