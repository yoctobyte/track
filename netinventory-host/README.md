# NetInventory Host

`netinventory-host` is the host-side web application for the NetInventory
subsystem inside `TRACK`.

Its current role is intentionally narrow:

- expose a stable host-facing web entrypoint under `/netinventory/`
- prepare separate runtime storage for each TRACK environment
- publish bootstrap/download material for the attended client tool
- offer lightweight browser registration and tiny collector downloads for ordinary devices
- publish user-mode and admin-mode collectors for Linux and Windows
- become the later home for uploads, unattended reports, and aggregation

The laptop-side field tool remains in [../netinventory-client](../netinventory-client).
