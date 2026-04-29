# TrackSync — pull side and per-subproject backup policy

The signed channel and manifest discovery are in place. This iteration adds the
client-side pull loop and a per-peer policy that controls *which subprojects*
get backed up locally.

Hosts are responsible for their own data. Cross-host copies are opportunistic:
when a peer reaches another peer it can pull the artifacts it cares about.

## Pull loop

`/sync/<peer_id>` currently fetches `/api/v1/hello` and `/api/v1/manifest` and
stops. Extend it to walk the manifest and download missing files via signed
`/api/v1/files/<root_id>/<rel_path>`.

Rules:

- Land pulled files at `tracksync/data/peers/<peer_id>/<root_id>/<rel_path>`.
- Skip files that already exist locally with matching size + sha256.
- Re-download on size or sha256 mismatch; do not overwrite a verified file
  in place. Quarantine bad downloads under `_bad/` for inspection.
- Verify sha256 after download.
- Report per-peer counts: pulled, skipped, failed. Persist last counts on the
  peer record.

## Per-subproject backup policy

Every artifact root carries a `record_type` like `map3d.model_artifact`. The
prefix before the first dot is the subproject. The pull loop consults a
per-peer policy keyed by subproject:

```json
"pull_policy": {
  "default": true,
  "subprojects": {
    "map3d": false
  }
}
```

Defaults: every subproject enabled, `map3d` disabled. The map3d roots hold
videos and dense reconstructions; pulling them by default would dominate any
laptop's disk.

The operator can flip `map3d` on for a specific peer (a backup server) without
affecting laptops or other peers.

The policy is per-peer, not global, so a single TrackSync instance can play
"thin laptop" toward one peer and "full backup" toward another.

## Out of scope this iteration

- Tier-aware pull (skip `derived-large` and `archive` unless asked). The spec
  already mentions it; layer on top of the subproject toggle later.
- Record (envelope) sync — adapters do not emit records yet.
- Push direction — pull-only is enough for "another peer holds a copy."
- Conflict UI — append-only files do not conflict.
- sha256 caching on the producer side — flagged separately, not part of this
  change.
