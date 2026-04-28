# TRACK Multi-Host Sync

## Goal

TRACK should support multiple independently running hosts, for example:

- stable server
- development server
- backup server
- site-local server

The operator should be able to add another server URL, provide a shared secret,
and run sync. SQLite databases may remain local to each host. Sync must happen
at the record/file level, not by copying SQLite files.

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
- Mutable records use latest `updated_at` as the default winner.
- Manual conflict UI can be added later for high-value records.
- Derived data should usually not sync unless explicitly marked exportable.

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
- manual sync action that checks remote availability

Not yet implemented:

- per-subproject record adapters
- file transfer
- conflict UI
- automatic scheduled sync
- public/private key trust

