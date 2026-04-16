# Python Rewrite Decision

## Decision

NetInventory will be rewritten in Python from scratch.

This is a clean-room rewrite, not a line-by-line port of the current Go
implementation.

## Why

The dominant problem is no longer low-level concurrency. The project now depends
more on:

- rapid iteration on data models and heuristics
- broad library availability
- sensor and protocol integration flexibility
- easier experimentation with normalization, inference, and topology mapping
- one language across collector, summarizer, and CLI

Go gave us some useful early structure, but it is no longer the right design
center for the project.

## What This Means

- Python becomes the primary implementation language
- CLI becomes the primary interface
- backend/business logic must remain separate from any UI
- the existing Go and Flask code is considered legacy/reference code
- new backend work should happen in the new Python package, not in the old stack

## Rewrite Rules

- Do not port behavior blindly just because it exists today
- Rebuild around the current product goals, not the current file layout
- Keep raw evidence capture, but make normalized summaries the real product
- Prefer simple, explicit local storage and service boundaries
- Prefer zero-config local behavior by default
- Design for future multi-device ingest from the start

Configuration policy:

- local single-device use should work without any required environment variables
- paths and runtime defaults should be autodetected sensibly
- explicit configuration should be minimal and file-based when needed
- secrets/config become relevant mainly for sync and multi-device sharing later

## Immediate Rewrite Priorities

1. Establish the new Python package and CLI entrypoint
2. Define the new domain model and storage boundaries
3. Build collector runtime and change detection in Python
4. Add normalized summary storage
5. Reintroduce UI only after backend shape stabilizes

## Progress Notes

- Python package scaffold created
- `pyproject.toml` added with a `netinv` CLI entrypoint
- CLI command structure created for `collect`, `serve`, `status`, `current`,
  `recent`, `networks`, and `sync`
- Initial local SQLite storage foundation added for normalized state
- `status`, `current`, and `networks` now read from the new Python storage layer
- Bare `netinv` now reports rewrite/runtime status instead of being an empty stub
- Lightweight local HTTP service added for remote inspection and extraction
- Export bundle generation added for workstation import workflows
- Shared-secret API protection added with auto-generated local secret storage
- `collect --once` now writes a first real observation and updates local summary state

Current remote-agent surface:

- `GET /api/v1/status`
- `GET /api/v1/current`
- `GET /api/v1/networks`
- `GET /api/v1/tasks`
- `GET /api/v1/export`

CLI additions:

- `netinv serve`
- `netinv export`
- `netinv import`

Current auth model:

- service API requires a shared secret
- secret is auto-generated locally on first use
- secret is stored in the local state directory
- clients can present it via `X-NetInv-Token` or `Authorization: Bearer ...`

Current collector progress:

- one-shot local collection implemented in Python
- writes one observation into SQLite
- updates active network and minimal network summary state
- uses a simple initial local fingerprint based on host identity and detected IP
- observations now store structured fact payloads, not just summary text
- consecutive duplicate probe results are now suppressed to reduce needless writes
- the local probe now captures gateway, resolver, and interface state from the host

Current task-runtime progress:

- task definition model added
- task runs stored in SQLite
- `current_network_probe` is the first scheduler-driven task
- `recent` now reports recent task activity
- remote agent can expose task definitions and recent task runs

Current user-context progress:

- user annotations are now stored as structured records
- CLI can attach context to arbitrary entity kinds
- remote agent can expose stored user context
- user context and task runs now keep source-device attribution for replication

Current sync-transport progress:

- export bundles now emit replication-style records rather than only local tables
- import can merge observations, task runs, and user context from a bundle
- imported records are deduplicated by stable record IDs already stored in SQLite

## Port Status Checkpoint

Current status of the rewrite:

- new Python path is now the active development path
- legacy Go/Flask code remains only as reference material
- storage has moved from raw-file-only ideas to a real local SQLite model
- remote-agent extraction now exists in Python via HTTP + export bundles
- the collector is only at first-probe stage and still needs real sensing logic

What is not ported and should be rebuilt rather than translated:

- legacy plugin execution model
- legacy Flask aggregation path
- legacy snapshot file flow as the primary storage model

Immediate next backend targets:

1. network/site/port relationship inference
2. long-running task execution and summarization
3. richer per-task reporting and freshness summaries
4. device identity and signed replication envelopes

## Legacy Status

The current Go collector and Flask UI remain in the repository only as temporary
reference material during the rewrite. They should not drive new architecture.
