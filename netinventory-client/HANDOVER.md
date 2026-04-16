# Handover

## Current State

The repository is in the middle of a Python rewrite centered on
`src/netinventory`.

The active rewrite now has three connected pieces in place:

1. persisted task definitions and task runs
2. persisted user context plus CLI/service exposure
3. material-change detection and duplicate suppression for the first
   scheduler-driven probe
4. richer local probe facts for gateway, resolver, and interface state
5. replication-style export/import bundles with merge support

The working tree is dirty. Existing user changes were preserved. Nothing was
reverted.

## What Was Already In Progress

Before this continuation, the workspace already contained functional but
unfinished work for the task/context runtime:

- CLI wiring for `recent`, `annotate`, and `context` in
  `src/netinventory/cli.py`
- command handlers in `src/netinventory/commands.py`
- HTTP endpoints `/api/v1/tasks` and `/api/v1/context` in
  `src/netinventory/service.py`
- task models in `src/netinventory/core/tasks.py`
- user-context model in `src/netinventory/core/context.py`
- task runtime scaffolding in `src/netinventory/tasks.py`
- user-context task flow in `src/netinventory/context.py`
- SQLite schema growth in `src/netinventory/storage/db.py`
- structured collector facts in `src/netinventory/collect/collector.py`

That earlier work was kept and validated rather than replaced.

## What Changed In This Turn

This continuation implemented the next backend target listed in the rewrite
notes: material-change detection and duplicate suppression.

### Main behavior change

`src/netinventory/storage/db.py` now treats observation ingestion as a policy
decision instead of an unconditional insert:

- `record_observation()` reads the most recent stored observation
- it compares:
  - `network_id`
  - `kind`
  - `facts_json`
- it also compares the current `active_network_id` from `app_state`
- if the new observation matches the latest stored observation and the active
  network did not change, the write is suppressed
- if the observation is different, or the active network changed, the
  observation is treated as material and stored
- on a material write, `app_state.last_material_change_at` is updated

This gives the first instant task bounded persistence and avoids repeated
identical writes for low-end devices.

### Richer sensing added

`src/netinventory/collect/collector.py` now captures more local network state:

- default gateway from `/proc/net/route`
- default route interface from `/proc/net/route`
- DNS servers from `/etc/resolv.conf`
- DNS search domains from `/etc/resolv.conf`
- interface inventory from `/sys/class/net`
  - name
  - MAC address
  - operstate
  - MTU
  - carrier
  - wireless flag

To avoid making every new fact automatically count as material, the collector
now computes a separate `material_fingerprint`. Duplicate suppression uses that
fingerprint rather than raw `facts_json`.

### Replication transport added

`src/netinventory/export.py` and `src/netinventory/storage/db.py` now support a
replication-style bundle format.

The export bundle now contains:

- `format = netinventory-sync-export`
- `source_device_id`
- `records`

The records currently cover:

- observations
- task runs
- user context

The import path now:

- reads `export.json` from the tarball
- merges records into local SQLite
- deduplicates via existing primary keys
- rebuilds network summaries from imported observations
- preserves source-device attribution on task runs and user context

### New model

`src/netinventory/core/models.py` now includes `ObservationIngestResult` with:

- `observation_id`
- `network_id`
- `stored`
- `material_change`
- `active_network_changed`
- `reason`

This allows task execution to know whether the collector result was actually
persisted.

### Task runtime integration

`src/netinventory/tasks.py` now uses the observation ingest result when
finalizing task runs for `current_network_probe`.

Task-run detail now reports one of:

- `stored material network observation: <network_id>`
- `suppressed duplicate observation: <network_id>`

Task runs are still recorded even when the observation write is suppressed.
That is intentional. Task activity and observation persistence are now separate
concepts.

### Planning docs updated

The following docs were updated to reflect that duplicate suppression is now
done:

- `PYTHON_REWRITE.md`
- `WORKING_ON.md`

## Important File-Level Notes

### `src/netinventory/storage/db.py`

- schema already includes:
  - `observations.facts_json`
  - `task_definitions`
  - `task_runs`
  - `user_context`
- `record_observation()` now returns `ObservationIngestResult`
- observations now store `material_fingerprint`
- task runs and user context now store `source_device_id`
- duplicate suppression only compares against the immediately previous stored
  observation
- `export_bundle_data()` now emits replication records rather than table dumps
- `import_bundle_data()` can merge replication bundles and legacy observation /
  context bundles
- `get_status()` still reports actual stored observation rows only

### `src/netinventory/tasks.py`

Registered task definitions:

- `current_network_probe`
- `arp_snapshot`
- `gps_watch`
- `user_context`

Only `current_network_probe` is implemented.

The others currently return a `SKIPPED` task run with detail
`task registered but not implemented yet`.

### `src/netinventory/commands.py`

- `handle_collect_once()` now runs through the task runtime
- `handle_recent()` prints recent task runs from SQLite
- `handle_annotate()` records user context through the task path
- `handle_context()` reads stored user context
- `handle_status()` upserts task definitions and prints `task_definitions`

### `src/netinventory/service.py`

- request handling upserts task definitions before serving data
- new routes:
  - `/api/v1/tasks`
  - `/api/v1/context`
- the shared-secret auth model remains unchanged

### `src/netinventory/collect/collector.py`

`CollectedObservation` now carries structured `facts`.

Current probe facts are still minimal and local:

- hostname
- fqdn
- primary_ip
- mac_address
- default_gateway
- default_route_interface
- dns_servers
- search_domains
- active_interfaces
- interfaces
- platform
- python_version

`network_id` is still derived from `primary_ip|mac_address`, hashed and
truncated.

## Current Runtime Flow

For `collect --once`, the flow is now:

1. CLI enters `handle_collect_once()`
2. DB opens and task definitions are upserted
3. `run_task_once(db, "current_network_probe", TaskTrigger.MANUAL)` starts
4. a `RUNNING` task run is stored
5. the collector emits a `CollectedObservation`
6. DB checks whether the observation is materially different from the latest
   stored observation
7. if material:
   - the observation is inserted
   - the network summary is updated
   - `active_network_id` is updated
   - `last_material_change_at` is updated
8. if duplicate:
   - no observation row is inserted
   - no network summary counter is incremented
9. the task run is finalized as `SUCCEEDED` with a detail string describing the
   outcome

So repeated identical probes still appear as task activity, but do not keep
writing to the observation table.

## Verification Performed

Validation was done in temporary state directories using `NETINV_HOME` and
`PYTHONPATH=/home/rene/netinventory/src`.

Earlier in-progress functionality was smoke-tested:

- `python3 -m netinventory status`
- `python3 -m netinventory collect --once`
- `python3 -m netinventory recent`
- `python3 -m netinventory annotate network demo-net room "Rack Room A"`

The new duplicate-suppression behavior was verified with:

1. fresh temp state
2. `collect --once`
3. `collect --once` again
4. `status`
5. `recent`

Observed results:

- first run detail: `stored material network observation: <network_id>`
- second run detail: `suppressed duplicate observation: <network_id>`
- `status` showed `observations: 1` after two identical runs
- `recent` showed both task runs in descending order

This confirms that task attempts are tracked separately from observation
persistence.

The new import/export path was verified with a source and destination temp
state:

1. source device collected one observation
2. source device wrote one user-context annotation
3. source exported a bundle
4. destination imported the bundle
5. destination SQLite showed:
   - 1 observation
   - 1 network summary
   - 2 task runs
   - 1 user-context record

The first destination `status` check was run too early while import was still in
flight. A direct SQLite inspection confirmed the merge succeeded. Subsequent
reads should be done after the import command finishes.

## Current Working Tree

At the end of this turn, the working tree still included in-progress rewrite
changes across:

- `PYTHON_REWRITE.md`
- `WORKING_ON.md`
- `src/netinventory/cli.py`
- `src/netinventory/collect/collector.py`
- `src/netinventory/commands.py`
- `src/netinventory/context.py`
- `src/netinventory/core/context.py`
- `src/netinventory/core/models.py`
- `src/netinventory/core/tasks.py`
- `src/netinventory/service.py`
- `src/netinventory/storage/db.py`
- `src/netinventory/tasks.py`

## Known Limitations

- only one real task implementation exists: `current_network_probe`
- duplicate suppression compares only with the latest stored observation
- materiality is intentionally simple:
  - same latest facts + same network + same kind + no active-network change
    means suppress
  - anything else stores
- there is no suppression window or thresholding yet
- there is no structured suppressed-attempt counter
- `recent` reports task runs only, not a richer observation-ingest model
- export includes observations and user context, but not task history
- export/import is local-bundle based only; there is still no live peer sync
- long-running tasks exist only as definitions
- task definitions are upserted on request/command paths, which is acceptable
  for now but not a final design

## Best Next Step

The rewrite notes now point next to richer network sensing inputs.

The cleanest next sequence is now:

1. define stable device identity and signing material
2. add signatures or trust metadata to replication envelopes
3. begin network/site/port relationship inference on top of replicated records
4. only then add live sync transport beyond bundles

If storage wear remains a priority, a strong next increment would be:

- optionally track suppressed-attempt counts in app state or task metadata

The normalized material fingerprint is now in place, so noisy future collector
fields no longer have to force every probe into a stored observation.

## Suggested Restart Context

When rerunning with auto permissions, the next agent should assume:

- the task/context rewrite is functional
- duplicate suppression for the instant probe is done
- no revert is needed
- the next meaningful target is richer sensing or the import path
- verification should continue with isolated temp state directories

Useful first commands on restart:

```bash
git status --short
git diff --stat
sed -n '1,220p' WORKING_ON.md
sed -n '1,220p' PYTHON_REWRITE.md
```

If continuing implementation:

```bash
sed -n '1,220p' src/netinventory/collect/collector.py
sed -n '1,340p' src/netinventory/storage/db.py
sed -n '1,220p' src/netinventory/tasks.py
```
