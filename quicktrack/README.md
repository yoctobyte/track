# QuickTrack

QuickTrack is a small TRACK subproject for fast photo observations.

It captures:

- one uploaded photo
- server-side UTC timestamp
- optional description
- optional GPS coordinates, requested only after pressing the GPS button
- optional sender ID, persisted in a browser cookie after first submit

Runtime data is local to the instance:

- `quicktrack/data/records/*.json`
- `quicktrack/data/photos/*`

Record IDs are timestamp-prefixed and sender-labelled, so they are sortable,
globally unlikely to collide, and suitable for later TrackSync artifact syncing.

## Run

```bash
./quicktrack/run.sh
```

Useful environment variables:

- `QUICKTRACK_PORT`, default `5107`
- `QUICKTRACK_BIND`, default `0.0.0.0`
- `QUICKTRACK_DATA_DIR`, default `quicktrack/data`
- `QUICKTRACK_MAX_UPLOAD_MB`, default `32`
