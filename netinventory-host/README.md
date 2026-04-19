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
- **(Active)** coordinate Central-to-Local hardware inspections via the Rack UX bridging dynamically to local `netinventory-client` daemons via CORS.

The laptop-side field tool remains in [../netinventory-client](../netinventory-client).
