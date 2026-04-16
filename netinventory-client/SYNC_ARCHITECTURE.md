# Sync Architecture

## Goal

NetInventory needs multi-device data sharing that feels cloud-like without
forcing a full cloud dependency into the core product.

The system should support:

- single-device local operation with zero required remote setup
- multi-device synchronization across homes, labs, and sites
- intermittent connectivity
- devices behind NAT
- bounded local storage and write volume
- later expansion to direct peer sync

The design center is not "share SQLite files". The design center is
record-level replication with local-first agents.

## Core Model

Each device runs a local agent.

Each agent:

- collects observations locally
- stores raw and normalized state locally
- remains useful when offline
- can export or sync records to other peers
- has its own stable identity

A "cloud-like" experience means:

- devices appear in one shared inventory
- device data converges incrementally
- the user does not manually shuffle files
- sync works through outbound connectivity when possible
- temporary disconnects do not corrupt the model

## Recommended Architecture

### Phase 1 default: relay-mediated sync

The recommended first production architecture is relay-mediated sync.

Each agent establishes an outbound connection to a sync relay or coordinator.
That relay is responsible for:

- peer presence
- authenticated session establishment
- batch exchange
- optional fan-out of encrypted payloads

The relay does not need to be the permanent source of truth for the product
model. It can be:

- a self-hosted service
- a site-local service
- a lightweight internet-facing broker

Why this is the right first step:

- works behind NAT without inbound ports
- easier than direct mesh
- simpler operationally than TURN/STUN-heavy peer connectivity
- gives a cloud-like user experience quickly

### Later option: direct peer sync

Direct peer sync can be added later as an optimization or advanced deployment
mode.

That requires:

- rendezvous
- peer discovery
- NAT traversal help
- relay fallback

Direct peer sync should not be the first milestone unless decentralization is a
hard requirement from day one.

### Optional mode: hub-and-spoke

An even earlier rollout can use a trusted aggregator.

Agents push and pull from one or more aggregators:

- local workstation
- site gateway
- self-hosted VPS

This is simpler than full relay-mediated federation and can evolve into it.

## Identity And Trust

Shared secrets are acceptable for the current local inspection API, but they
are not sufficient for long-term multi-device federation.

Each agent should have:

- `device_id`
- public/private keypair
- device metadata
  - hostname
  - device class
  - human label
  - site membership if known
- trust policy
  - allowed peers
  - allowed organizations
  - allowed relay/coordinator

Recommended identity properties:

- `device_id` is stable and locally generated
- public key is the real cryptographic identity
- device metadata is signed by that identity
- sync messages are signed
- transport is encrypted

Trust establishment can start with:

- manual pairing
- import of trusted peer keys
- site-level trust bundles

Later it can grow into:

- org-scoped certificate authority
- delegated device enrollment
- revocation lists

## Data Model For Sync

Do not sync database files. Sync records.

There are several classes of data in the system, and they should not all be
treated the same way.

### 1. Facts

Facts are observed evidence emitted by a device.

Examples:

- current IP
- default gateway
- DNS resolver
- local interface state
- ARP observation
- Wi-Fi scan result
- traceroute hop

Properties:

- attributed to a source device
- timestamped
- append-only
- immutable after creation

### 2. Task runs

Task runs describe operational freshness and execution outcomes.

Examples:

- probe succeeded
- scan skipped
- monitor failed
- task started/finished

Properties:

- attributed to a source device
- append-only
- useful for freshness, confidence, and diagnostics

### 3. Context

Context is human-entered or externally supplied metadata.

Examples:

- room
- cabinet
- wall port
- switch port
- device role
- note

Properties:

- mutable
- versioned
- history should be preserved

### 4. Summaries

Summaries are derived state.

Examples:

- current active network
- likely site
- inferred uplink
- normalized device profile

Properties:

- recomputable
- not the primary replication unit
- often local caches derived from facts plus context

### 5. Topology edges

Topology edges represent inferred or confirmed relationships.

Examples:

- device connected to switch
- AP serves network
- host seen on subnet
- wall port maps to switch port

Properties:

- can be inferred
- may also be explicitly confirmed by humans
- should carry confidence and provenance

## Record Envelope

Every replicated record should be wrapped in a consistent envelope.

Suggested envelope fields:

- `record_id`
- `record_type`
- `source_device_id`
- `observed_at`
- `created_at`
- `sequence`
- `entity_scope`
- `payload`
- `confidence`
- `schema_version`
- `signature`

Field guidance:

- `record_id`
  - globally unique
  - never reused
- `record_type`
  - fact, task_run, context, topology_edge, tombstone, etc.
- `source_device_id`
  - the device that produced the record
- `observed_at`
  - when the event actually happened
- `created_at`
  - when the record was materialized
- `sequence`
  - monotonically increasing per source device
- `entity_scope`
  - optional stable entity reference when known
- `payload`
  - typed content for the record
- `confidence`
  - numeric confidence where inference is involved
- `schema_version`
  - for migration compatibility
- `signature`
  - authenticity and tamper detection

## Local Storage Direction

The current rewrite stores useful local state in SQLite. That should continue,
but the schema should gradually shift toward explicit replication records.

Recommended storage direction:

- append-only event tables for observed facts and task runs
- versioned records for user context
- derived summary tables rebuilt from replicated records
- per-peer sync cursor tables
- import journal tables for replay safety

Important consequence:

- synced data should be mergeable at the record level
- summaries should be downstream caches, not authoritative origins

## Conflict Model

There is no safe distributed system here without an explicit conflict policy.

Use different conflict rules per class of data.

### Facts

Facts should be immutable and append-only.

If two devices report different facts, keep both. Do not overwrite one with the
other.

### Task runs

Task runs should also be append-only.

They describe execution history, not a singleton state.

### Context

Context can start with a simple conflict rule:

- preserve history
- expose current value as last-writer-wins

That is acceptable as a first implementation if history is retained.

Later improvements:

- source priority
- actor identity
- explicit approval or merge workflows

### Summaries

Summaries should be recomputed from underlying records.

Do not replicate summaries as the authoritative truth if they can be rebuilt.

### Topology edges

Topology edges should carry:

- provenance
- confidence
- confirmation state

Conflicting edges should coexist until inference or human action resolves them.

## Sync Semantics

Sync should be incremental and idempotent.

Use a cursor-based model:

- peer A asks peer/relay B for records since cursor X
- B returns a batch plus next cursor
- A applies only new records
- A acknowledges applied cursor

Core properties:

- replays are safe
- duplicate delivery is safe
- offline gaps can be repaired
- peers do not need full snapshots every time

Basic operations:

- `hello`
- `authenticate`
- `capabilities`
- `push_batch`
- `pull_batch`
- `ack_cursor`
- `request_snapshot`
- `transfer_bundle`

## Connectivity Model

To feel cloud-like under normal conditions:

- each agent maintains outbound connectivity when possible
- a relay or coordinator tracks reachable sessions
- peers sync in small batches
- sync resumes from cursors after disconnects

Offline fallback still matters:

- export bundle generation remains useful
- import must become a first-class path
- manual transfer should be treated as an alternate transport, not a different
  data model

## Security Model

Minimum viable secure design:

- per-device keypairs
- signed sync envelopes
- encrypted transport
- peer allowlist or org trust list
- scoped authorization by device/site/org

Requirements:

- devices are not universally trusted by default
- relay compromise should not automatically imply payload trust
- import path must validate signatures and record shape
- revoked devices must stop being accepted

Recommended trust levels:

- local-only device
- paired peer
- site member
- org member
- admin device

## Import And Export Direction

Import/export should become the first sync-compatible transport.

That means export bundles should evolve from "database dump" toward
"replication batch".

A sync-compatible export should contain:

- source device identity
- export timestamp
- signed records
- schema version
- optional cursor/checkpoint info

Import should:

- validate bundle format
- validate signatures and source identity
- deduplicate by `record_id`
- append accepted records
- rebuild summaries as needed
- record import provenance

This import path is the natural next milestone because it creates the merge
logic needed for later network sync.

## Rollout Plan

### Phase 1: local-first plus import/export merge

Build:

- stable per-record IDs
- append-only fact/task/context records
- import pipeline that merges records
- export bundles built from those records

Do not build mesh networking yet.

### Phase 2: coordinator or relay sync

Build:

- device keypairs
- authenticated sync sessions
- push/pull batch API
- per-peer cursors
- replay-safe ingestion

This gives the first cloud-like experience.

### Phase 3: richer federation

Build:

- multi-site trust policies
- relay fan-out or mailbox queues
- peer presence
- site-scoped authorization
- optional end-to-end encrypted payload relaying

### Phase 4: optional direct peer optimization

Build:

- peer rendezvous
- NAT traversal
- relay fallback
- opportunistic direct replication

This should remain optional.

## Implications For The Current Rewrite

The current Python rewrite should move toward these concrete changes:

1. add stable record IDs for synced entities and events
2. add per-record source attribution everywhere
3. separate append-only fact records from derived summary tables
4. build import as a merge pipeline, not a file restore path
5. add peer cursor/checkpoint storage
6. add device key management
7. keep sync logic out of collector-specific code

The current shared-secret HTTP service is useful for local inspection, but it
should not become the long-term federation security model.

## Near-Term Recommendation

The next concrete implementation step should be:

1. define replication-ready record schemas
2. update export to emit those records
3. build import to merge them into local state

Only after that should networked sync be added.

That sequence keeps the architecture honest:

- one replication model
- multiple transports
- local-first operation
- clean path from manual bundle transfer to cloud-like sync
