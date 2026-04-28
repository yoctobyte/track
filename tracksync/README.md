# TRACK Sync

`tracksync` is the umbrella sync coordinator for TRACK deployments that run on
multiple hosts.

It is intentionally standalone:

- it has its own Flask app
- it stores its own config under `tracksync/data`
- it does not import subproject internals by default
- subproject-specific adapters can be added later

The scope is global TRACK trust and data sync. NetInventory, Map3D,
DeviceControl, and other subprojects are adapters under this layer; they do not
own pairing. A laptop with approved TrackSync credentials is a trusted TRACK
node, even if it is offline most of the time.

## Peer Setup

For the first practical setup, a peer is:

- host URL
- optional location slug
- optional remote username/password for the admin's local use
- sync secret for signed API requests

The username/password fields stay in local `tracksync/data/config.json`. They
are not exported in manifests. The sync secret is used only for HMAC request
signing.

This is mutual node trust, not a central-server-only credential. An always-on
server can act as a relay or public surface, but append-only data may originate
from any trusted laptop, workstation, backup server, or site-local host.

## Run

```bash
./tracksync/run.sh
```

Environment variables:

- `TRACKSYNC_HOST_ID`: stable local host id
- `TRACKSYNC_PORT`: HTTP port, default `5099`
- `TRACKSYNC_DATA_DIR`: data directory, default `tracksync/data`
- `TRACKSYNC_SECRET`: local shared secret for inbound requests
- `TRACKSYNC_ADMIN_PASSWORD`: UI password, default `tracksync-admin`

## Current Scope

This first slice supports:

- local host identity
- adding peer URL and secret through the admin UI
- signed hello/manifest API endpoints
- local environment slugs in manifests
- configurable artifact root manifests
- manual peer sync handshake

Record and file adapters will be added per subproject.

## Trusted Nodes

The intended production flow is:

1. A clean laptop creates a local TrackSync host identity.
2. The operator either creates a local environment or requests pairing with an
   existing trusted host.
3. A remote admin approves that laptop as a trusted node.
4. The laptop syncs when online and keeps local records while offline.

Normal sync should be append-only. If data is no longer active, adapters should
publish tombstones or superseding records instead of physically deleting remote
history. Local retention cleanup can exist later, but it is outside the sync
protocol.

## Environments

Environment slugs are assumed unique for now:

```text
museum
testing
lab
```

A host may serve multiple slugs. Collision handling and slug migration are
deferred until real deployments prove the edge cases.

## Artifact Roots

`tracksync` can advertise arbitrary local files in `/api/v1/manifest` and serve
them through signed `/api/v1/files/<root>/<path>` requests.
Configure roots in `tracksync/data/config.json`:

```json
{
  "artifact_roots": [
    {
      "id": "map3d-derived-large",
      "path": "/absolute/path/to/map3d/data/derived/model_reconstructions",
      "tier": "derived-large",
      "record_type": "map3d.model_artifact",
      "include": ["**/*.ply", "**/*.glb", "**/*.mp4", "**/*.json"],
      "exclude": ["**/logs/**"],
      "enabled": true
    }
  ]
}
```

Small data should be pulled first. Large artifacts are advertised so a stable
server can selectively fetch outputs produced by a GPU workstation later.
