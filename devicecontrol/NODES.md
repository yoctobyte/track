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
./devicecontrol/tools/bootstrap-host.sh \
  --host 100.x.y.z \
  --login-user pi \
  --inventory devicecontrol/data/environments/museum/inventory.ini \
  --group media_players
```

Defaults:

- creates user `ansible`
- installs your default public SSH key
- prompts for a strong password for the remote `ansible` account
- grants passwordless sudo to `ansible` so Ansible can become root non-interactively
- keeps the account as a plain SSH automation user, not a desktop/runtime user

Ansible needs the management user to have a shell, so the bootstrap uses
`/bin/bash`. Do not use this user for autologin, kiosk sessions, browser
profiles, media playback, or day-to-day desktop work.

If you want sudo to require a password instead:

```bash
./devicecontrol/tools/bootstrap-host.sh \
  --host 100.x.y.z \
  --login-user pi \
  --sudo-mode password
```

That is stricter, but the current web UI cannot answer sudo prompts. Use this
only if you plan to run Ansible manually with a become password or add Vault
support later.

If you want key-only SSH with no usable account password:

```bash
./devicecontrol/tools/bootstrap-host.sh \
  --host 100.x.y.z \
  --login-user pi \
  --password-mode locked
```

## Bootstrap Hosts From An Inventory

For first import, put the currently known login user in `ansible_user`.

Example before bootstrap:

```ini
[video_players]
redacted-host ansible_host=100.x.x.x ansible_user=fons
```

Then dry-run the import:

```bash
./devicecontrol/tools/bootstrap-host.sh \
  --from-inventory devicecontrol/data/environments/museum/inventory.ini \
  --dry-run
```

Bootstrap all hosts in that inventory:

```bash
./devicecontrol/tools/bootstrap-host.sh \
  --from-inventory devicecontrol/data/environments/museum/inventory.ini
```

Bootstrap only one group:

```bash
./devicecontrol/tools/bootstrap-host.sh \
  --from-inventory devicecontrol/data/environments/museum/inventory.ini \
  --limit video_players
```

Bootstrap and rewrite successful hosts to the new management user:

```bash
./devicecontrol/tools/bootstrap-host.sh \
  --from-inventory devicecontrol/data/environments/museum/inventory.ini \
  --activate-ansible-user
```

After successful activation, the line becomes:

```ini
redacted-host ansible_host=100.x.x.x ansible_user=ansible
```

That rewritten form is what the web UI expects for normal ongoing actions.

## Auto-Bootstrap An Inventory

For bulk imports, prefer `autobootstrap.sh`.

It checks every selected inventory host first:

- if `ansible@host` is already reachable by SSH key, it skips bootstrap
- if not reachable, it bootstraps through the known current login user
- after success, it rewrites the inventory to `ansible_user=ansible`
- it preserves the old login as `bootstrap_user=...`

Example before:

```ini
[video_players]
redacted-host ansible_host=100.x.x.x ansible_user=fons
```

Run a dry-run first:

```bash
./devicecontrol/tools/autobootstrap.sh \
  --inventory devicecontrol/data/environments/museum/inventory.ini \
  --dry-run
```

Then run the real import:

```bash
./devicecontrol/tools/autobootstrap.sh \
  --inventory devicecontrol/data/environments/museum/inventory.ini
```

Limit to a group:

```bash
./devicecontrol/tools/autobootstrap.sh \
  --inventory devicecontrol/data/environments/museum/inventory.ini \
  --limit video_players
```

Expected result after a successful run:

```ini
redacted-host ansible_host=100.x.x.x ansible_user=ansible bootstrap_user=fons
```

On later runs, `autobootstrap.sh` will first try `ansible@100.x.x.x`. If
that works, it does nothing. If the server key changes or the `ansible` account
needs repair, it can still use `bootstrap_user=fons` as the fallback enrollment
login.

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
