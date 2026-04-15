# DeviceControl Nodes

This document describes the practical node workflow for `devicecontrol`.

## Mental Model

`devicecontrol` only acts on enrolled hosts.

A host becomes enrolled when:

1. it exists in the correct environment inventory
2. SSH works for the configured Ansible user
3. sudo behavior is known
4. the human operator accepts that web-triggered playbooks may run on it

Discovery is not the same as enrollment. Tailscale, NetInventory, or manual
notes may reveal devices, but they should stay as candidates until access is
confirmed.

## Environment Inventories

Each TRACK environment has its own inventory:

```text
devicecontrol/data/environments/testing/inventory.ini
devicecontrol/data/environments/museum/inventory.ini
devicecontrol/data/environments/lab/inventory.ini
```

Keep these separate. Do not put testing/home hosts in the museum inventory.

## Add A Candidate Manually

Add commented candidates first:

```ini
# [tailscale_online_candidates]
# player-01 ansible_host=100.x.y.z ansible_user=TODO
```

This records the finding without making it active.

## Enroll A Host

After confirming the device belongs in this environment, move it into a real
group and fill in the SSH user:

```ini
[media_players]
player-01 ansible_host=100.x.y.z ansible_user=ansible
```

Recommended groups:

```ini
[media_players]
[kiosks]
[admin_boxes]
[network_tools]
[test_boxes]
```

Groups are useful because the web UI can target a group name instead of a
single hostname.

## Bootstrap A Host

Use the manual bootstrap helper from the repo root for one host:

```bash
./devicecontrol/bootstrap-host.sh \
  --host 100.x.y.z \
  --login-user pi \
  --inventory devicecontrol/data/environments/museum/inventory.ini \
  --group media_players
```

Defaults:

- creates user `ansible`
- installs your default public SSH key
- generates and stores a strong password for the remote `ansible` account
- grants passwordless sudo to `ansible` so Ansible can become root non-interactively
- keeps the account as a plain SSH automation user, not a desktop/runtime user

Ansible needs the management user to have a shell, so the bootstrap uses
`/bin/bash`. Do not use this user for autologin, kiosk sessions, browser
profiles, media playback, or day-to-day desktop work.

The generated management-account password is stored locally here:

```text
devicecontrol/data/bootstrap-passwords.json
```

That file is ignored by git. It is meant for the operator/server, not for the
public web interface.

If you want sudo to require a password instead:

```bash
./devicecontrol/bootstrap-host.sh \
  --host 100.x.y.z \
  --login-user pi \
  --sudo-mode password
```

That is stricter, but the current web UI cannot answer sudo prompts. Use this
only if you plan to run Ansible manually with a become password or add Vault
support later.

If you want key-only SSH with no usable account password:

```bash
./devicecontrol/bootstrap-host.sh \
  --host 100.x.y.z \
  --login-user pi \
  --password-mode locked
```

## Auto-Bootstrap An Inventory

For anything beyond a single new host, use `autobootstrap.sh`. It takes the
environment name as its only required argument and resolves to the matching
inventory under `devicecontrol/data/environments/<env>/inventory.ini`.

For first import, put the currently known login user in `ansible_user`.

Example before:

```ini
[video_players]
redacted-host ansible_host=100.x.x.x ansible_user=fons
```

Run a dry-run first:

```bash
./devicecontrol/autobootstrap.sh museum --dry-run
```

Then run the real import:

```bash
./devicecontrol/autobootstrap.sh museum
```

Limit to a group:

```bash
./devicecontrol/autobootstrap.sh museum --limit video_players
```

Autobootstrap checks every selected inventory host first:

- if `ansible@host` is already reachable by SSH key, it skips bootstrap
- if not reachable, it bootstraps through the known current login user
- after success, it unconditionally rewrites the inventory to
  `ansible_user=ansible` and preserves the old login as `bootstrap_user=...`

Expected result after a successful run:

```ini
redacted-host ansible_host=100.x.x.x ansible_user=ansible bootstrap_user=fons
```

On later runs, `autobootstrap.sh museum` will first try
`ansible@100.x.x.x`. If that works, it does nothing. If the server key
changes or the `ansible` account needs repair, it can still use
`bootstrap_user=fons` as the fallback enrollment login. The human account
is never touched again by devicecontrol in normal operation.

## Single-Host Bootstrap

For a one-off device that is not yet in any inventory, use
`bootstrap-host.sh` with an explicit host and login:

```bash
./devicecontrol/bootstrap-host.sh \
  --host 100.x.y.z \
  --login-user pi \
  --inventory devicecontrol/data/environments/testing/inventory.ini \
  --group media_players
```

This appends a new line already pinned to `ansible_user=ansible`, so the
human account is never reused for this host.

`bootstrap-host.sh --from-inventory` still exists for backwards
compatibility, but do not use it for bulk enrollment. It does not rewrite
the inventory by default, which leaves the inventory pointing at the
human login and defeats the whole point of the ansible user. Use
`autobootstrap.sh <env>` instead.

## Check A Host

```bash
./devicecontrol/tools/check-host.sh 100.x.y.z ansible
```

This checks SSH and whether passwordless sudo works.

## Passwords

Prefer SSH keys plus a dedicated `ansible` user.

Do not put real passwords into git-tracked inventories. If password-based
Ansible access becomes necessary, use a local ignored file or Ansible Vault.
The first web UI assumes key-based SSH and non-interactive sudo for actions
that need root.

## Run Actions From The Web UI

Open the active TRACK environment, then open `DeviceControl`.

The target field accepts:

- a hostname from the inventory
- a group name from the inventory
- empty value for all hosts in that environment

Start with `Ping`. Do not run upgrade/reboot actions until `Ping` is clean and
the host grouping is correct.

Web-triggered actions are deliberately non-interactive. They use SSH
`BatchMode` and strict known-host checking, so they will not ask to accept host
fingerprints or type passwords. If a web action fails with a host-key error,
run `autobootstrap.sh <env>` or `bootstrap-host.sh` from the console first.
Fingerprint acceptance belongs to enrollment, not to the web UI.

## Run Actions From The Shell

Equivalent manual form:

```bash
ansible-playbook \
  -i devicecontrol/data/environments/museum/inventory.ini \
  devicecontrol/ansible/playbooks/ping.yml \
  --limit player-01
```

For all enrolled museum hosts:

```bash
ansible-playbook \
  -i devicecontrol/data/environments/museum/inventory.ini \
  devicecontrol/ansible/playbooks/ping.yml
```

## Screenshots

The screenshot action is best-effort.

Linux desktop screenshots depend on:

- X11 vs Wayland
- active display number
- runtime desktop user
- `.Xauthority`
- installed screenshot tools

If screenshot fails, inspect the run log first. Some hosts will need host vars,
for example:

```ini
player-01 ansible_host=100.x.y.z ansible_user=ansible screenshot_runtime_user=museum screenshot_display=:0
```
