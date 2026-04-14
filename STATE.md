# TRACK State

Last refreshed: 2026-04-14

## Current Reality

The repository now contains three real subprojects:

- `map3d`
- `museumcontrol`
- `netinventory`

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
- `netinventory` should keep working as a standalone inventory/observation tool

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

## museumcontrol Current State

`museumcontrol` has now been imported with history intact.

It is already a meaningful standalone project with:

- its own authentication and admin model
- its own UI
- its own device metadata concerns

Near-term work should avoid breaking this independence.

## netinventory Current State

`netinventory` has now been imported with history intact.

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

- the umbrella may start selected local subservices once
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
