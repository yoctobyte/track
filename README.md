# TRACK

TRACK is a collection of small tools for documenting and operating real-world
locations: photos, network inventory, device control, 3D mapping, and host sync.

The project is intentionally not one big app. Each subproject should remain
runnable on its own. The root TRACK app only provides shared environment
navigation and starts the configured host-side services.

## Quick Start On A Test Laptop

Requirements:

- Linux laptop or workstation
- `git`
- `python3`
- `python3-venv`
- `pip`
- optional: `sudo` for privileged NetInventory probes

Clone and check the config:

```bash
git clone <repo-url> track
cd track
./track-configure.py validate
./track-configure.py list
```

Start the TRACK umbrella app and configured host-side services:

```bash
./track.sh
```

Open:

```text
http://127.0.0.1:5000/
```

The launch scripts create local virtual environments and install their Python
requirements on first run.

## NetInventory Client

NetInventory Client is the laptop field tool for local network observation. It
is not launched by `./track.sh` and is not shown in the TRACK umbrella UI.

Run it from the repository root:

```bash
./netinventory-client.sh
```

It starts a local UI on `http://127.0.0.1:8889/`, keeps running in the
foreground, and may ask for sudo so it can perform better Wi-Fi, ARP, and link
inspection. The launcher opens a browser automatically when possible.

Useful options:

```bash
NETINVENTORY_UI_PORT=8890 ./netinventory-client.sh
NETINVENTORY_OPEN_BROWSER=0 ./netinventory-client.sh
NETINVENTORY_SKIP_SUDO=1 ./netinventory-client.sh
TRACK_BASE_URL=https://track.praktijkpioniers.com ./netinventory-client.sh
```

See [netinventory-client/README.md](./netinventory-client/README.md) if this is
the only tool an admin needs to run.

## Installation Profiles

Use [INSTALL.md](./INSTALL.md) for the current install model. The short version:

- `standalone`: start fresh, keep all data local until paired later.
- `server`: mostly-on host that serves TrackHub, host-side apps, and TrackSync.
- `client` or field laptop: local tools and opportunistic sync with a remote
  trusted TRACK host.

Known deployments usually point laptops at:

```text
https://track.praktijkpioniers.com
```

The remote host can list available environments/realms. The local environment
slug does not have to match the remote slug; admins are expected to choose
responsible names.

## Main Commands

```bash
./track.sh                  # start TrackHub plus configured autostart services
./track-configure.py list   # inspect environments, apps, ports, launch plan
./track-configure.py validate
./netinventory-client.sh    # standalone laptop network inventory client
```

Local tests:

```bash
./trackhub/test-local.sh
./tracksync/test-local.sh
./netinventory-host/test-local.sh
./quicktrack/test-local.sh
```

## Subprojects

- `trackhub/`: root web interface and environment navigation.
- `tracksync/`: host identity, peer credentials, manifests, and file sync APIs.
- `netinventory-host/`: public intake, storage, and topology views for network
  inventory data.
- `netinventory-client/`: standalone laptop/client network observation tool.
- `quicktrack/`: timestamped photo observations with optional notes and GPS.
- `map3d/`: photo capture and 3D reconstruction workflow.
- `devicecontrol/`: Ansible-backed maintenance actions for enrolled devices.
- `museumcontrol/`: kiosk and device control dashboard.

## Data And Sync Rules

- SQLite databases may remain local to each app.
- Synced records and filenames should be globally unique enough to move between
  hosts safely.
- Normal sync is append-only: new facts and file revisions are added rather than
  deleted in place.
- TrackSync trust is global. Subprojects expose data; TrackSync decides which
  peer is trusted to exchange it.
- Host-local environment names are allowed. A remote `museum` can be local
  `devspacemuseum` if the admin configured that mapping deliberately.

## More Docs

- [INSTALL.md](./INSTALL.md)
- [ARCHITECTURE.md](./ARCHITECTURE.md)
- [STATE.md](./STATE.md)
- [PROGRESS.md](./PROGRESS.md)
- [GOALS.md](./GOALS.md)
