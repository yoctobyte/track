# TRACK State

Last refreshed: 2026-04-15

## Current Reality

The repository now contains six real subprojects:

- `map3d`
- `museumcontrol`
- `netinventory-client`
- `netinventory-host`
- `netinventory-simple`
- `devicecontrol`

They are not yet unified under a root web shell.

They should remain independently runnable while the umbrella grows above them.

## Current Priorities

### 1. Establish the umbrella cleanly

We need:

- a root project identity
- a root landing entry
- a clear architecture for subproject coexistence

We do **not** yet need:

- a giant merged application
- a shared all-purpose database
- deep runtime coupling

### 2. Keep subprojects healthy on their own

Each subproject should continue to make sense by itself:

- `map3d` should keep working as a standalone mapping/capture app
- `museumcontrol` should keep working as a standalone control dashboard
- `netinventory-client` should keep working as a standalone inventory/observation tool
- `netinventory-host` should keep working as a standalone intake/publishing surface
- `netinventory-simple` should keep working as an isolated non-server client asset pack
- `devicecontrol` should keep working as a standalone Ansible control surface

### 3. Define shared concepts before shared code

The likely shared concepts are:

- environment / site
- location hierarchy
- tags
- access scope

These should be defined before we attempt broad integration.

## map3d Current State

`map3d` is the most actively integrated subproject in this repo right now.

Current known capabilities:

- capture runs grouped more realistically
- reconstruction-set collection
- sparse reconstruction helper
- dense reconstruction helper
- HTML sparse viewer
- experimental dense-viewer support in progress

Current known architectural issue:

- `map3d` still occupies the web role as if it were the main app
- this must be reduced over time so it becomes one sub-application under `TRACK`

Current environment/data isolation rule:

- `map3d` data must not be shared across TRACK environments.
- `testing`, `museum`, and `lab` should run as separate `map3d` instances with
  separate SQLite databases and file roots.
- `testing` currently keeps the legacy `map3d/data` root so existing capture
  work remains available.
- `museum` and `lab` use isolated roots under `map3d/data/environments/`.
- Do not solve this by exposing one global `map3d` database and filtering only
  in the UI; that risks accidental cross-environment leakage.

## museumcontrol Current State

`museumcontrol` has now been imported with history intact.

It is already a meaningful standalone project with:

- its own authentication and admin model
- its own UI
- its own device metadata concerns

Near-term work should avoid breaking this independence.

## netinventory-client Current State

`netinventory-client` has now been imported with history intact.

It is clearly its own project with:

- its own runtime model
- task execution
- probe and observation logic
- sync/export behavior

It should currently be understood as a hybrid subsystem:

- central data collection and aggregation
- locally run inspection scripts
- some probe paths that may require elevated privileges
- potential permanent monitoring on controlled devices

It should remain operationally separate while shared location/tag concepts are
defined at the umbrella level.

More broadly, `TRACK` should expect subprojects to solve different parts of the
documentation / organization / administration problem in different and sometimes
inventive ways. Uniformity is less important than keeping the seams clear.

## netinventory-host Current State

`netinventory-host` is the new umbrella-facing host application for network
inventory.

Its current role is intentionally thin:

- serve a stable `/netinventory/` entrypoint under TRACK
- describe the attended client / unattended host split clearly
- publish client bootstrap/download information
- prepare a place for future collection and aggregation flows

Near-term work should keep it lightweight while `netinventory-client` continues
to evolve independently.

## netinventory-simple Current State

`netinventory-simple` is not a separate runtime. It is the isolated home for
lightweight downloadable client assets.

It currently exists to hold:

- shell and Windows batch collector templates
- future PowerShell or binary collectors
- the minimal client-side pieces that `netinventory-host` serves for download

## devicecontrol Current State

`devicecontrol` is the Ansible-backed TRACK control kit.

Its first version should be understood as:

- a standalone Flask web interface around approved Ansible playbooks
- a per-environment inventory runner
- a manual bootstrap helper for creating the `ansible` management user
- a place for operational logs and fetched screenshots

Bootstrap remains intentionally console-side for now because it may require SSH
passwords, sudo prompts, and trust decisions. The web interface should only act
on already enrolled hosts.

Current environment/data isolation rule:

- each TRACK environment uses its own `devicecontrol` inventory
- run logs and screenshots are written under that environment
- do not expose one shared inventory through UI filtering only

## Main Near-Term Deliverables

1. root documentation
2. root landing shell
3. canonical path-based routing plan under one public hostname
4. shared environment/location/tag design
5. per-environment access model

Current intended routing support:

- `reverse-proxy` for real deployment
- `app-proxy` as a testing/development fallback

Current intended launcher behavior:

- the umbrella starts subservices from central launch metadata in `trackhub/config.json`
- autostart is explicit per environment/app instance
- generic subservice launchers receive environment variables from the umbrella config
- it should not auto-restart crashed subservices by default
- temporary subservice downtime is acceptable during development
- production should still aim for stable long-running subservices

## Explicit Non-Goals Right Now

- full database unification
- full auth unification across all subprojects
- moving all subprojects into one Flask app
- solving all server/GPU-node deployment architecture at once

## Notes

Temporary notes and raw drafts are intentionally still present in the repo.
They should be archived later, not aggressively cleaned right now.
