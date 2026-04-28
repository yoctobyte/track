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
- manual peer sync handshake

Record and file adapters will be added per subproject.

