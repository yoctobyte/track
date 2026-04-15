# DeviceControl

`devicecontrol` is the TRACK control kit for Ansible-backed operational
actions.

It is intentionally narrower than the documentation/archive parts of TRACK:

- hosts must be enrolled first
- inventories are separated per TRACK environment
- the web UI only exposes approved playbooks
- bootstrap remains a manual console-side process

## Runtime

System dependency:

```bash
sudo apt install ansible
```

The Flask UI intentionally does not install Ansible with `pip`. It expects the
same `ansible-playbook` command a sysadmin would use from the shell.

Standalone:

```bash
./devicecontrol/run-testing.sh
```

By default, the web UI accepts requests only from TrackHub with authenticated
proxy headers. For deliberate local standalone testing, set:

```bash
DEVICECONTROL_ALLOW_STANDALONE=1 ./devicecontrol/run-testing.sh
```

Do not use standalone mode on a publicly reachable port.

Environment-specific wrappers:

```bash
./devicecontrol/run-testing.sh  # port 5021
./devicecontrol/run-museum.sh   # port 5031
./devicecontrol/run-lab.sh      # port 5032
```

When proxied through TrackHub, the active environment is supplied through
`X-Trackhub-Environment`. Direct standalone use falls back to the wrapper
environment.

## Data Layout

Each environment has its own inventory and output directories:

```text
devicecontrol/data/environments/<environment>/
  inventory.ini
  run_logs/
  screenshots/
```

Do not share one inventory across museum/lab/testing. That would risk operating
the wrong devices from the wrong location.

## Bootstrap

Bootstrap is manual for now because it may need SSH passwords and sudo:

```bash
./devicecontrol/tools/bootstrap-host.sh \
  --host 192.168.1.50 \
  --login-user pi \
  --inventory devicecontrol/data/environments/testing/inventory.ini \
  --group media_players
```

The script creates an `ansible` user by default, installs your public SSH key,
prompts for a strong account password, and grants passwordless sudo for
non-interactive Ansible automation.

That means the account is not an empty-password desktop user. It is a plain SSH
automation account with a real shell, because Ansible needs a shell to execute
modules. It should not be used as a kiosk/runtime/desktop login.

See [NODES.md](./NODES.md) for the full candidate -> enrolled host workflow,
inventory editing rules, and examples.

For bulk imports, use:

```bash
./devicecontrol/tools/autobootstrap.sh \
  --inventory devicecontrol/data/environments/museum/inventory.ini \
  --dry-run
```

## First Playbooks

Current approved actions:

- `ping`
- `apt-update`
- `apt-upgrade`
- `reboot`
- `update-and-reboot`
- `screenshot`

The screenshot playbook is best-effort. Linux desktop screenshot behavior varies
by display server, desktop user, Xauthority, Wayland/X11, and installed tools.

## Boundary

This subproject acts on known/enrolled devices.

It does not replace:

- `netinventory` for discovery
- `museumcontrol` for specialized kiosk/player controls
- TRACK documentation for long-term device context
