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

Bootstrap is manual for now because it may need SSH passwords and sudo.

The blessed workflow is:

1. Edit the environment inventory by hand with the current human login
   per host, e.g. `redacted-host ansible_host=100.x.y.z ansible_user=fons`.
2. Dry-run autobootstrap against that environment:

   ```bash
   ./devicecontrol/tools/autobootstrap.sh museum --dry-run
   ```

3. Run for real:

   ```bash
   ./devicecontrol/tools/autobootstrap.sh museum
   ```

Autobootstrap will:

- check whether `ansible@host` already works (skip if yes),
- otherwise SSH in as the human login, create the `ansible` user, install
  your public key, set a strong password, grant passwordless sudo,
- re-verify, and **rewrite the inventory in place** to
  `ansible_user=ansible bootstrap_user=<previous human login>`.

After that, no devicecontrol tool touches the human account again. The
human account is left intact as a rescue path, but every subsequent
ansible-playbook run targets the dedicated `ansible` user.

For a single new device not yet in an inventory, there is also a manual
helper:

```bash
./devicecontrol/tools/bootstrap-host.sh \
  --host 192.168.1.50 \
  --login-user pi \
  --inventory devicecontrol/data/environments/testing/inventory.ini \
  --group media_players
```

Do **not** use `bootstrap-host.sh --from-inventory` for bulk imports —
autobootstrap is the intended bulk path and is the only one that
guarantees the one-way flip to `ansible_user=ansible`.

The `ansible` account is not an empty-password desktop user. It is a
plain SSH automation account with a real shell, because Ansible needs a
shell to execute modules. It should not be used as a kiosk/runtime/desktop
login.

See [NODES.md](./NODES.md) for the full candidate -> enrolled host
workflow, inventory editing rules, and examples.

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
