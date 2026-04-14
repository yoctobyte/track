# NetInventory

`netinventory` is the network-observation subsystem inside `TRACK`.

It is intentionally not just a web app. Its current direction is:

- `Agent`
  - local execution on a laptop or controlled device
  - privileged inspection where needed
  - field context such as rack, wall port, or cable path
- `Hub`
  - central SQLite-backed storage
  - task runs, observations, and user context
  - import/export and service API
- `Web`
  - TRACK-facing operator surface
  - status, recent activity, known networks
  - downloadable agent bootstrap

## Why

The system needs to support a very physical workflow:

- connect a laptop to random Ethernet sockets or Wi-Fi networks
- observe the environment locally
- record what cable or port was actually used
- preserve that evidence centrally later

That makes `netinventory` a hybrid by design.

## Current TRACK Launcher

For umbrella use, TRACK starts:

- [run-track.sh](./run-track.sh)

This runs the hub web surface on `127.0.0.1:8888` by default.

It does **not** try to run privileged capture automatically.

## Main Docs

- [PROJECT_GOALS.md](./PROJECT_GOALS.md)
- [PYTHON_REWRITE.md](./PYTHON_REWRITE.md)
- [ARCHITECTURE.md](./ARCHITECTURE.md)
- [HANDOVER.md](./HANDOVER.md)
