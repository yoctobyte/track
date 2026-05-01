# NetInventory Client

NetInventory Client is the standalone laptop tool for collecting local network
observations. It is meant for an admin walking around with a laptop, connecting
to Wi-Fi or Ethernet, recording what was observed, and later uploading or
syncing that evidence to a public NetInventory Host.

It does not require the TRACK umbrella app to run.

## Install

Requirements:

- Linux laptop or workstation
- `git`
- `python3`
- `python3-venv`
- `pip`
- optional: `sudo` for privileged probes

Clone the TRACK repository:

```bash
git clone git@github.com:yoctobyte/track.git
cd track
```

No separate install command is required. The launcher creates
`netinventory-client/venv` and installs the package into it on first run.

## Run

From the repository root:

```bash
./netinventory-client.sh
```

The default local UI is:

```text
http://127.0.0.1:8889/
```

The process stays in the foreground. Stop it with `Ctrl-C`.

The launcher asks for sudo when available because some probes need elevated
rights for full Wi-Fi scans, ARP discovery, link inspection, or raw network
operations. It does not run the whole web UI as root; it only caches sudo
credentials for probe commands.

## Common Options

Use a different local port:

```bash
NETINVENTORY_UI_PORT=8890 ./netinventory-client.sh
```

Do not open a browser automatically:

```bash
NETINVENTORY_OPEN_BROWSER=0 ./netinventory-client.sh
```

Run without sudo prompts:

```bash
NETINVENTORY_SKIP_SUDO=1 ./netinventory-client.sh
```

Point the client at the expected public TRACK host for future upload/sync:

```bash
TRACK_BASE_URL=https://track.example.org ./netinventory-client.sh
```

Override the repository URL embedded in generated bootstrap scripts:

```bash
TRACK_GITHUB_REPO=git@github.com:yoctobyte/track.git ./netinventory-client.sh
```

## What It Stores

The client stores observations locally first. Typical data includes:

- scan snapshots
- detected networks and addresses
- local context entered by the operator
- task/probe runs

The local database is allowed to be unique to this laptop. Exported records and
future upload payloads should use IDs and filenames that remain safe when moved
between hosts.

## Sync Direction

The intended operational model is:

- laptop runs NetInventory Client locally
- public server runs NetInventory Host inside TRACK
- admin copies the setup block from the public NetInventory Host page
- admin pastes that block into the client sync setup
- laptop uploads or syncs collected observations when online

NetInventory Client is intentionally not exposed through TrackHub and is not
started by `./track.sh`.

## Troubleshooting

If the browser cannot connect, check that the terminal is still running the
client and that no other process is using the selected port.

If dependency installation fails, verify `python3-venv` and `pip` are installed.
On Debian or Ubuntu:

```bash
sudo apt install python3 python3-venv python3-pip
```

If privileged scans are unavailable, run normally and allow the sudo prompt, or
set `NETINVENTORY_SKIP_SUDO=1` to continue with reduced probe coverage.

## Developer Notes

The subproject entrypoint used by the root launcher is:

```bash
netinventory-client/run-track.sh
```

That script can still run in background mode for development:

```bash
NETINVENTORY_BACKGROUND=1 ./netinventory-client/run-track.sh
```

Run the local regression test:

```bash
./netinventory-client/test-local.sh
```
