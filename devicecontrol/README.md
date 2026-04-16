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
   ./devicecontrol/autobootstrap.sh museum --dry-run
   ```

3. Run for real:

   ```bash
   ./devicecontrol/autobootstrap.sh museum
   ```

Autobootstrap will:

- check whether `ansible@host` already works (skip if yes),
- otherwise SSH in as the human login, create the `ansible` user, install
  your public key, set a generated strong password, grant passwordless sudo,
- re-verify, and **rewrite the inventory in place** to
  `ansible_user=ansible bootstrap_user=<previous human login>`.

After that, no devicecontrol tool touches the human account again. The
human account is left intact as a rescue path, but every subsequent
ansible-playbook run targets the dedicated `ansible` user.

The generated `ansible` account password is stored locally at:

```text
devicecontrol/data/bootstrap-passwords.json
```

That file is ignored by git and should stay server/operator-local.

For a single new device not yet in an inventory, there is also a manual
helper:

```bash
./devicecontrol/bootstrap-host.sh \
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
- `screenshot-setup`
- `collect-stats`

The screenshot playbook is best-effort. Linux desktop screenshot behavior varies
by display server, desktop user, Xauthority, Wayland/X11, and installed tools.

`screenshot` captures using already-installed tools. `screenshot-setup` also
installs missing screenshot helpers before capturing. Use `screenshot-setup`
on first run or after a fresh OS install.

Both screenshot actions are desktop-aware for the currently supported cases:

- `openbox-x11`
- `gnome-x11`
- `gnome-wayland`

DeviceControl keeps a small per-host operational memory under:

```text
devicecontrol/data/environments/<environment>/capture_profiles/<host>.json
```

That profile stores the last known-good capture method, such as preferred tool,
display, auth mode, and whether capture succeeded as the desktop user or root.
`screenshot` uses that profile to reduce probing. `screenshot-setup` can
rediscover and refresh it.

`collect-stats` is the lightweight status probe used by the web UI. It stores
cached per-host runtime information under:

```text
devicecontrol/data/environments/<environment>/stats/
```

The overview treats the latest successful stats collection as `last seen`.
That is not yet a permanent monitoring heartbeat; it is cached operational
state produced by an approved Ansible action.

After each `collect-stats` run, DeviceControl also appends central behavior
events under:

```text
devicecontrol/data/environments/<environment>/device_events/<host>.jsonl
```

Current event types:

- `host_seen`
- `host_recovered`
- `poll_failed`
- `boot_id_changed`

These are generated centrally by comparing the newly fetched stats snapshot
with the previous cached snapshot and the Ansible run log. No permanent agent
or service is installed on the managed device.

This is intentionally polling-based. It can detect reboots/power losses after
the host comes back by noticing a changed Linux boot ID. It can detect outages
when a `collect-stats` run targets a host and Ansible reports it failed or
unreachable. It cannot observe an outage in real time unless polling is running
on an interval.

## Scheduled Jobs And Retention

Some actions should eventually run on an interval instead of only by button:

- `collect-stats` every few minutes for last-seen, load, memory, IPs, desktop
  hints, and configured-user processes
- `screenshot` less often, or only for selected display devices
- `ping` or a cheaper reachability check if stats collection is too heavy

Keep two kinds of data separate:

- Current state: one latest JSON/screenshot per host for the UI.
- History: timestamped samples for trends, diagnostics, and audit trails.

History needs thinning. A practical retention policy is:

- keep all samples for the recent short window
- keep periodic samples for older windows
- keep a few oldest/landmark samples for long-term context
- keep the latest sample always

In other words: do not store thousands of near-identical screenshots forever,
but do preserve enough old evidence to understand what changed over time.

## Display State Timeline

Some hosts intentionally show black screenshots. That does not always mean the
screenshot failed. On kiosk/media devices it may mean the system actively put
the monitor into a low-power state, disabled HDMI output, blanked X, or dropped
the framebuffer as part of a screen-off hack.

Treat this as operational data, not merely as a bad preview.

Future display monitoring should store small timestamped events separately from
full screenshots:

- screen/display enabled
- screen/display disabled
- HDMI output disabled/enabled
- framebuffer unavailable
- wake button or software wake triggered
- screenshot black but capture succeeded
- screenshot failed because no display/session was reachable

These events should be cheap to keep for a long time: timestamp, host, event
type, source action, and a few bytes of metadata. Full screenshots can use the
retention policy above, while display-state events form the durable timeline.

This matters especially for Raspberry Pi style players where “black” may be
the expected power-saving state rather than an error.

Initial implementation:

```text
devicecontrol/data/environments/<environment>/display_events/<host>.jsonl
```

After a `screenshot` action, DeviceControl inspects newly fetched PNG files and
appends compact events:

- `screenshot_active`
- `screenshot_black`
- `screenshot_failed`

The black/active classifier samples PNG luminance when possible and falls back
to a conservative file-size signal. The event is evidence from the screenshot,
not a final authority on the electrical monitor state.

## Boundary

This subproject acts on known/enrolled devices.

It does not replace:

- `netinventory` for discovery
- `museumcontrol` for specialized kiosk/player controls
- TRACK documentation for long-term device context
