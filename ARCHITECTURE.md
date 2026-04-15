# TRACK Architecture

## Summary

`TRACK` should be built as an umbrella system over multiple subprojects.

Those subprojects may share concepts and later share services, but they should
not be prematurely fused into a single codebase or runtime.

## Architectural Rule

Each subproject should remain:

- standalone
- runnable on its own
- deployable on its own
- useful on its own

The umbrella should provide:

- common identity
- common navigation
- shared conceptual model
- selective integration

Subprojects are allowed to be technically unusual if their domain requires it.
`TRACK` is expected to contain odd, inventive, and specialized subsystems
rather than forcing everything into one uniform runtime pattern.

## Current Subproject Roles

### `map3d`

Role:

- capture spatial evidence
- reconstruct approximate 3D space
- connect time-based documentation to place

### `museumcontrol`

Role:

- operate and inspect controllable devices
- expose approved actions safely
- support museum staff workflows

### `netinventory`

Role:

- observe network environments
- build technical inventory from field evidence
- summarize repeated network encounters
- support hybrid collection patterns:
  - central aggregation
  - local probes
  - privileged inspection where needed
  - persistent monitoring on controlled devices

### `devicecontrol`

Role:

- run approved Ansible maintenance actions
- keep per-environment inventories separate
- provide manual bootstrap helpers for enrolling hosts
- store action logs and fetched operational artifacts such as screenshots

It should not become a general arbitrary-command web shell. Bootstrap and trust
setup remain console-side until the security model is more mature.

## Recommended Integration Shape

## 1. Root Shell

Create a small root-level web shell for `TRACK`.

Its responsibilities should be:

- pick an environment
- route to a subproject
- provide shared navigation
- eventually enforce access scope

This root shell should initially be thin.

It does not need to absorb subproject code.

Preferred outward shape:

- one public hostname
- one Cloudflare tunnel
- stable subpaths such as:
  - `/map3d/`
  - `/museumcontrol/`
  - `/netinventory/`
  - `/devicecontrol/`

Two acceptable routing modes should be supported:

1. `reverse-proxy`
   - preferred for deployment
   - Nginx/Caddy/other front-end proxy handles path routing
2. `app-proxy`
   - acceptable for development and testing
   - the umbrella app proxies subprojects itself
   - slower and less clean, but convenient when no front-end proxy exists

## 2. Shared Concepts

The first shared layer should be conceptual, not operational.

Recommended shared concepts:

- `environment`
  - examples: `home`, `museum`, `lab`
- `location`
  - hierarchical physical structure inside an environment
- `tag`
  - lightweight shared label vocabulary
- `access_scope`
  - who may see or operate which environment

## 3. Shared Data Approach

Do not merge all databases.

Instead:

- each subproject keeps its own database
- shared concepts are synchronized or referenced through thin seams
- APIs or import/export bridges come before deep storage coupling

This keeps the subprojects portable.

## 4. Runtime / Deployment Approach

Prefer this mental model:

- one umbrella identity
- multiple independently runnable services
- no default umbrella supervision of crashed subservices

That can later become:

- reverse-proxied sub-apps
- a root landing app linking or proxying into subprojects
- specialized deployment by node type

Examples:

- CPU head-end for root UI and control tasks
- GPU node for heavy `map3d` processing

Preferred external/public topology:

- public user hits one hostname
- reverse proxy or shell routes to subprojects internally
- local ports remain implementation details

This is preferable to exposing one public subdomain or public port per subproject.

### Supervision Policy

By default, the umbrella should start subservices once and not automatically
restart them if they crash.

Reason:

- subprojects are under active development
- a failed subservice should be visible as failed
- the umbrella should tolerate temporary subservice outages
- automatic relaunch can hide crashes and interfere with debugging

Later, optional supervision may be added as an explicit per-service or
per-environment deployment choice.

In production, the desired end state is still that subservices are stable
enough to remain up under normal operation.

## 5. Authentication Direction

Authentication should move toward environment-aware access.

Likely flow:

1. user lands at root
2. user chooses environment
3. user authenticates for that environment
4. user sees only the permitted subprojects/data for that environment

This is preferable to one global login followed by broad visibility.

## Integration Order

The recommended order is:

1. root docs and project identity
2. root landing shell
3. shared environment/location/tag design
4. per-environment access model
5. thin subproject integration
6. deeper service sharing only where justified

## Anti-Pattern To Avoid

Do not turn `TRACK` into:

- one giant Flask project
- one giant schema
- one giant auth system
- one giant deployment unit

That would reduce flexibility and make the umbrella brittle.

## Working Principle

`TRACK` is the umbrella.

`map3d`, `museumcontrol`, `netinventory`, and `devicecontrol` are not
“features” of a single app. They are subprojects under a common direction.
