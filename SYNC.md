# TRACK Multi-Host Sync

## Goal

TRACK should support multiple independently running hosts, for example:

- stable server
- development server
- backup server
- site-local server
- intermittent laptop or workstation

The operator should be able to add another node URL, provide or approve pairing
credentials, and run sync. SQLite databases may remain local to each host. Sync
must happen at the record/file level, not by copying SQLite files.

The model is not "all data lives on one central server". The model is:

- each approved laptop, workstation, server, or backup box is a trusted node
- trust is global to TRACK, not owned by a single subproject
- subprojects publish append-only records and immutable artifacts into the
  global sync layer
- nodes may be offline most of the time and sync when reachable
- stable servers are useful relays and public surfaces, but they are not the
  only source of truth

## Boundary Rule

Subprojects remain independently runnable. Sync is allowed to be a global
umbrella feature because it coordinates between subprojects, but it must not
force subprojects into one shared runtime or one shared database.

Recommended shape:

- `tracksync` is a standalone global sync app.
- Each subproject may expose an adapter later.
- A subproject that does not implement an adapter remains unaffected.
- Local IDs stay local implementation details.
- Sync IDs become the cross-host identity.
- Pairing, trust, peer credentials, and sync policy live in `tracksync`, not in
  `netinventory`, `map3d`, or another subproject.

## Identity Model

Every synced object needs a stable globally unique identifier in addition to
local database IDs.

Use a plain text sync ID:

```text
tr_<kind>_<hostid>_<ulid>
```

Examples:

```text
tr_session_stable01_01JZ3V7Y4RE8XQHY8R0A8VQXVK
tr_asset_devbox_01JZ3V86R0GNBT2Q9Y6S3HRF56
tr_location_museum_01JZ3V8N8SQRY33J9YR57VXJ3J
```

Rules:

- Local integer primary keys remain allowed.
- Sync IDs are immutable once assigned.
- Imported remote records keep their original sync ID.
- If a legacy row has no sync ID, the local adapter creates one once and stores
  it before export.
- Conflict handling uses sync IDs, not local integer IDs.

## Environment Naming

For the current implementation, environment slugs are assumed to be globally
unique across the hosts that sync with each other.

Examples:

```text
testing
museum
lab
stable-demo
```

Rules for now:

- Slugs are lowercase `a-z0-9-`.
- Slugs are stable and safe to use in local paths.
- Hosts may serve multiple distinct slugs.
- Collision handling is intentionally deferred.
- User-facing names may change; slugs should not casually change.

TrackSync stores local environment connection metadata as:

```json
{
  "slug": "museum",
  "name": "Museum",
  "username": "admin",
  "password": "local-only"
}
```

Only non-secret fields are exported in manifests:

```json
{
  "slug": "museum",
  "name": "Museum",
  "origin_host_id": "stable01",
  "enabled": true,
  "updated_at": "2026-04-28T12:00:00Z"
}
```

Passwords and usernames are local connection hints. They are not sync records
and are not exported to peers.

## Filename Model

Synced files need names that are unique, readable, and deterministic enough to
trace back to the record.

Preferred file path:

```text
<subproject>/objects/<kind>/<hostid>/<sync-id>/<sha256-prefix>_<safe-original-name>
```

Examples:

```text
map3d/objects/asset/stable01/tr_asset_stable01_01JZ.../9ac72a3f9121_frontdoor.jpg
```

Rules:

- Do not depend on local integer IDs in cross-host file paths.
- Include a content hash prefix.
- Keep the human filename suffix when safe.
- Treat file content as immutable once exported.
- If content changes, create a new object revision or a new derived file.

## Record Envelope

All subproject adapters should export records through the same envelope:

```json
{
  "sync_id": "tr_asset_stable01_01JZ3V86R0GNBT2Q9Y6S3HRF56",
  "record_type": "map3d.asset",
  "origin_host_id": "stable01",
  "updated_at": "2026-04-28T12:00:00Z",
  "deleted": false,
  "version": 1,
  "body": {}
}
```

Minimum fields:

- `sync_id`
- `record_type`
- `origin_host_id`
- `updated_at`
- `deleted`
- `version`
- `body`

Conflict policy for phase 1:

- Append-only facts never conflict.
- New facts and file revisions are preferred over in-place mutation.
- Mutable records use latest `updated_at` as the default winner.
- Manual conflict UI can be added later for high-value records.
- Derived data should usually not sync by default, but it may sync when marked
  as an exportable artifact.

Deletion policy:

- Physical deletion is not part of normal sync.
- If something must disappear from active views, export a tombstone or
  superseding record with `deleted: true`.
- Peers should preserve historical records and artifacts unless an operator
  explicitly runs a local retention cleanup outside the sync protocol.

This gives intermittent laptops a safe operating mode: they can append data
while offline, reconnect later, and merge without needing central locks.

## Trust Model

Pairing is global. A trusted node may contribute data for any subproject whose
adapter and policy allow it.

Initial trust levels:

- `pending`: node has requested pairing but cannot sync protected data yet.
- `trusted`: node may exchange manifests, records, and allowed artifacts.
- `disabled`: node remains known but all signed sync requests are rejected.

Phase 1 can still use mutual shared secrets for signed HTTP requests. The
important boundary is that the secret identifies a TRACK node, not a
NetInventory client or one-off upload token. Later, the same trust table can
grow into per-node keypairs or certificate-style approval without changing the
subproject record envelope.

Expected laptop flow:

1. Laptop installs TRACK and creates a local host identity.
2. Laptop either creates a local environment or requests pairing with an
   existing trusted host.
3. Remote admin approves the laptop as a trusted node.
4. Laptop syncs append-only records and allowed artifacts when online.
5. Other trusted nodes pull from it directly or through an always-on relay.

## Artifact Policy

Small durable documentation has priority over huge data, but the system should
be able to sync any file when the operator intentionally enables it.

Artifact tiers:

- `core`: small metadata needed for the application to understand records.
- `evidence`: original observations such as uploaded photos, videos, JSONL
  event logs, inventory files, rack photos, and screenshots.
- `derived-small`: previews, manifests, selections, summaries, and compact
  exports.
- `derived-large`: GPU or CPU generated outputs such as meshes, Gaussian
  splats, dense reconstructions, rendered videos, and texture atlases.
- `archive`: cold backup material that is useful to preserve but not needed
  during normal browsing.

Default sync behavior:

- Sync `core`, `evidence`, and `derived-small` first.
- Advertise `derived-large` and `archive` in manifests, but download them only
  when explicitly requested or when a peer policy says it wants them.
- Never include secrets, local tokens, PID files, virtualenvs, model checkouts,
  package caches, or full SQLite database files.

This supports asymmetric hosts. A GPU workstation can produce large `map3d`
artifacts and advertise them. A stable server can pull those artifacts later
and serve them without ever running the GPU pipeline.

Configured artifact roots are represented in `tracksync/data/config.json`:

```json
{
  "artifact_roots": [
    {
      "id": "map3d-model-results",
      "path": "/srv/track/map3d/data/derived/model_reconstructions",
      "tier": "derived-large",
      "record_type": "map3d.model_artifact",
      "include": ["**/*.ply", "**/*.glb", "**/*.mp4", "**/*.json"],
      "exclude": ["**/logs/**", "**/.cache/**"],
      "enabled": true
    }
  ]
}
```

The first implementation advertises artifact manifests with size, SHA-256,
relative path, record type, tier, and a signed download path. Automated pull
policy comes after this manifest and download endpoint are stable.

## Transport

Phase 1 uses HTTPS plus shared-secret request signing.

Each request includes:

- `X-Track-Sync-Host`
- `X-Track-Sync-Timestamp`
- `X-Track-Sync-Signature`

Signature:

```text
hmac_sha256(secret, METHOD + "\n" + PATH + "\n" + TIMESTAMP + "\n" + BODY_SHA256)
```

This is intentionally simple enough for local deployments. It can later evolve
to per-host keypairs without changing the adapter envelope.

## First Milestone

Implemented first:

- standalone `tracksync` app
- local host identity
- peer URL/secret configuration
- signed `/api/v1/hello`
- signed `/api/v1/manifest`
- signed `/api/v1/files/<root>/<path>`
- local environment slugs in manifests
- configurable artifact root manifests
- manual sync action that checks remote availability

Not yet implemented:

- per-subproject record adapters
- artifact pull policy
- imported file placement policy
- conflict UI
- automatic scheduled sync
- public/private key trust
