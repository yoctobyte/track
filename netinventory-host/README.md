# NetInventory Host

`netinventory-host` is the host-side web application for the NetInventory
subsystem inside `TRACK`.

Its current role is intentionally narrow:

- expose a stable host-facing web entrypoint under `/netinventory/`
- prepare separate runtime storage for each TRACK environment
- publish bootstrap/download material for the attended client tool
- offer lightweight browser registration and tiny collector downloads for ordinary devices
- publish user-mode and admin-mode collectors for Linux and Windows
- **(Active)** ingest orchestrated fleet telemetry (`netinventory-minimal`) via `/api/simple-ingest` and dynamically synthesize active network hardware topologies on the `/hosts` dashboard.
- **(Active)** derive a guessed topology graph under `/topology` and `/api/topology`, stored as flat JSON files in `data/environments/<env>/topology/`.
- **(Active)** coordinate Central-to-Local hardware inspections via the Rack UX bridging dynamically to local `netinventory-client` daemons via CORS.

The laptop-side field tool remains in [../netinventory-client](../netinventory-client).

Topology is derived evidence, not the source of truth. Raw simple ingests remain
append-only in `simple-registrations.jsonl`; the host rebuilds `summary.json`,
`nodes.json`, and `edges.json` from those samples.

## Passwords

Configure role passwords before exposing a host publicly:

```bash
./netinventory-host/password-tool.sh
```

Store the generated `NETINVENTORY_ADMIN_PASSWORD`,
`NETINVENTORY_PRIVILEGED_PASSWORD`, and `NETINVENTORY_USER_PASSWORD` values in
the service environment. Do not commit them.

Roles:

- `user`: view collected data.
- `privileged`: upload/sync field data and edit operational records.
- `admin`: full host administration.

The public index hides upload tokens and laptop setup blocks until a
privileged/admin password is entered. Upload endpoints require the upload token.

## Laptop Setup Block

On the public NetInventory Host page, log in as privileged/admin and copy the
NetInventory Client setup block. Paste it into the standalone laptop client
under `Sync target` -> `Paste setup block from host`, then save and sync.
