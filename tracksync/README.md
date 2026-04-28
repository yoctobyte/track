# TRACK Sync

`tracksync` is the umbrella sync coordinator for TRACK deployments that run on
multiple hosts.

It is intentionally standalone:

- it has its own Flask app
- it stores its own config under `tracksync/data`
- it does not import subproject internals by default
- subproject-specific adapters can be added later

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
- configurable artifact root manifests
- manual peer sync handshake

Record and file adapters will be added per subproject.

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
