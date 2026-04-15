#!/bin/bash
set -euo pipefail

usage() {
    cat <<'EOF'
Usage:
  Single host:
    tools/bootstrap-host.sh --host HOST --login-user USER [options]

  Inventory import:
    tools/bootstrap-host.sh --from-inventory PATH [options]

Options:
  --host HOST                    Target hostname or IP to bootstrap.
  --login-user USER              Existing user used for the first SSH login.
  --from-inventory PATH          Read hosts from an Ansible INI inventory.
  --limit HOST_OR_GROUP          Limit inventory import to one host or group. Can be repeated.
  --login-var NAME               Inventory var used as bootstrap login user. Default: ansible_user.
  --host-var NAME                Inventory var used as SSH target address. Default: ansible_host.
  --ansible-user USER            Management user to create. Default: ansible.
  --key PATH                     Public SSH key to install. Default: ~/.ssh/id_ed25519.pub then ~/.ssh/id_rsa.pub.
  --inventory PATH               Single-host mode: inventory file to append/update.
  --group NAME                   Single-host mode: inventory group to use. Default: managed.
  --activate-ansible-user        Inventory mode: after successful bootstrap, rewrite ansible_user to --ansible-user.
  --password-mode MODE           Account password mode: prompt, random, locked, keep. Default: prompt.
  --sudo-mode MODE               Sudo mode: nopasswd, password, none. Default: nopasswd.
  --no-passwordless-sudo         Compatibility alias for --sudo-mode password.
  --dry-run                      Print planned targets without connecting.
  --stop-on-error                Inventory mode: stop after the first failed host.

Inventory mode uses ansible_user as the existing login user by default. That is
intentional for first import: a human enters the known current user, this tool
creates the dedicated management user, and --activate-ansible-user can then flip
successful inventory lines to ansible_user=ansible.

This is intentionally manual. It may prompt for SSH and sudo passwords.
EOF
}

HOST=""
LOGIN_USER=""
FROM_INVENTORY=""
ANSIBLE_USER="ansible"
KEY_PATH=""
INVENTORY_PATH=""
GROUP="managed"
LOGIN_VAR="ansible_user"
HOST_VAR="ansible_host"
PASSWORD_MODE="prompt"
SUDO_MODE="nopasswd"
ACCOUNT_PASSWORD_B64=""
ACTIVATE_ANSIBLE_USER=0
DRY_RUN=0
STOP_ON_ERROR=0
LIMITS=()

while [ "$#" -gt 0 ]; do
    case "$1" in
        --host) HOST="${2:-}"; shift 2 ;;
        --login-user) LOGIN_USER="${2:-}"; shift 2 ;;
        --from-inventory) FROM_INVENTORY="${2:-}"; shift 2 ;;
        --limit) LIMITS+=("${2:-}"); shift 2 ;;
        --login-var) LOGIN_VAR="${2:-}"; shift 2 ;;
        --host-var) HOST_VAR="${2:-}"; shift 2 ;;
        --ansible-user) ANSIBLE_USER="${2:-}"; shift 2 ;;
        --key) KEY_PATH="${2:-}"; shift 2 ;;
        --inventory) INVENTORY_PATH="${2:-}"; shift 2 ;;
        --group) GROUP="${2:-}"; shift 2 ;;
        --activate-ansible-user) ACTIVATE_ANSIBLE_USER=1; shift ;;
        --password-mode) PASSWORD_MODE="${2:-}"; shift 2 ;;
        --sudo-mode) SUDO_MODE="${2:-}"; shift 2 ;;
        --no-passwordless-sudo) SUDO_MODE="password"; shift ;;
        --dry-run) DRY_RUN=1; shift ;;
        --stop-on-error) STOP_ON_ERROR=1; shift ;;
        -h|--help) usage; exit 0 ;;
        *) echo "Unknown option: $1" >&2; usage; exit 2 ;;
    esac
done

if [ -n "$FROM_INVENTORY" ] && { [ -n "$HOST" ] || [ -n "$LOGIN_USER" ]; }; then
    echo "Use either --from-inventory or --host/--login-user, not both." >&2
    exit 2
fi

if [ -z "$FROM_INVENTORY" ] && { [ -z "$HOST" ] || [ -z "$LOGIN_USER" ]; }; then
    usage
    exit 2
fi

if [ -n "$FROM_INVENTORY" ] && [ ! -f "$FROM_INVENTORY" ]; then
    echo "Inventory not found: $FROM_INVENTORY" >&2
    exit 1
fi

case "$PASSWORD_MODE" in
    prompt|random|locked|keep) ;;
    *) echo "Invalid --password-mode: $PASSWORD_MODE" >&2; exit 2 ;;
esac

case "$SUDO_MODE" in
    nopasswd|password|none) ;;
    *) echo "Invalid --sudo-mode: $SUDO_MODE" >&2; exit 2 ;;
esac

if [ "$SUDO_MODE" = "password" ] && [ "$PASSWORD_MODE" = "locked" ]; then
    echo "--sudo-mode password requires a usable account password; use --password-mode prompt/random/keep." >&2
    exit 2
fi

if [ -z "$KEY_PATH" ]; then
    if [ -f "$HOME/.ssh/id_ed25519.pub" ]; then
        KEY_PATH="$HOME/.ssh/id_ed25519.pub"
    elif [ -f "$HOME/.ssh/id_rsa.pub" ]; then
        KEY_PATH="$HOME/.ssh/id_rsa.pub"
    else
        echo "No default public key found. Generate one or pass --key." >&2
        exit 1
    fi
fi

if [ ! -f "$KEY_PATH" ]; then
    echo "Public key not found: $KEY_PATH" >&2
    exit 1
fi

PUBLIC_KEY_B64="$(base64 -w0 "$KEY_PATH")"

prepare_account_password() {
    if [ "$DRY_RUN" = "1" ]; then
        return 0
    fi
    case "$PASSWORD_MODE" in
        prompt)
            local first second
            read -rsp "Password for remote $ANSIBLE_USER account: " first
            echo
            read -rsp "Confirm password for remote $ANSIBLE_USER account: " second
            echo
            if [ "$first" != "$second" ]; then
                echo "Passwords do not match." >&2
                exit 1
            fi
            if [ "${#first}" -lt 16 ]; then
                echo "Password is too short; use at least 16 characters." >&2
                exit 1
            fi
            ACCOUNT_PASSWORD_B64="$(printf '%s' "$first" | base64 -w0)"
            ;;
        random)
            local generated
            generated="$(openssl rand -base64 30)"
            ACCOUNT_PASSWORD_B64="$(printf '%s' "$generated" | base64 -w0)"
            echo "Generated password for remote $ANSIBLE_USER account. Store it securely:"
            echo "$generated"
            ;;
        locked|keep)
            ACCOUNT_PASSWORD_B64=""
            ;;
    esac
}

shell_quote() {
    printf '%q' "$1"
}

bootstrap_one() {
    local target_host="$1"
    local login_user="$2"
    local inventory_name="${3:-$target_host}"

    if [ "$DRY_RUN" = "1" ]; then
        echo "DRY-RUN: would bootstrap $ANSIBLE_USER@$target_host through $login_user@$target_host (inventory host: $inventory_name)"
        return 0
    fi

    echo
    echo "==> Bootstrapping $inventory_name"
    echo "    SSH target: $target_host"
    echo "    Login user: $login_user"
    echo "    Management user: $ANSIBLE_USER"
    echo "    Password mode: $PASSWORD_MODE"
    echo "    Sudo mode: $SUDO_MODE"

    local remote_cmd
    remote_cmd="ANSIBLE_USER=$(shell_quote "$ANSIBLE_USER") PASSWORD_MODE=$(shell_quote "$PASSWORD_MODE") SUDO_MODE=$(shell_quote "$SUDO_MODE") PUBLIC_KEY_B64=$(shell_quote "$PUBLIC_KEY_B64") ACCOUNT_PASSWORD_B64=$(shell_quote "$ACCOUNT_PASSWORD_B64") bash -s"

    ssh "$login_user@$target_host" "$remote_cmd" <<'EOF' || return 1
set -euo pipefail

PUBLIC_KEY="$(printf '%s' "$PUBLIC_KEY_B64" | base64 -d)"

if ! id "$ANSIBLE_USER" >/dev/null 2>&1; then
  sudo useradd --create-home --shell /bin/bash "$ANSIBLE_USER"
else
  sudo usermod --shell /bin/bash "$ANSIBLE_USER"
fi

sudo install -d -m 700 -o "$ANSIBLE_USER" -g "$ANSIBLE_USER" "/home/$ANSIBLE_USER/.ssh"
sudo touch "/home/$ANSIBLE_USER/.ssh/authorized_keys"
if ! sudo grep -qxF "$PUBLIC_KEY" "/home/$ANSIBLE_USER/.ssh/authorized_keys"; then
  printf '%s\n' "$PUBLIC_KEY" | sudo tee -a "/home/$ANSIBLE_USER/.ssh/authorized_keys" >/dev/null
fi
sudo chown "$ANSIBLE_USER:$ANSIBLE_USER" "/home/$ANSIBLE_USER/.ssh/authorized_keys"
sudo chmod 600 "/home/$ANSIBLE_USER/.ssh/authorized_keys"

case "$PASSWORD_MODE" in
  prompt|random)
    ACCOUNT_PASSWORD="$(printf '%s' "$ACCOUNT_PASSWORD_B64" | base64 -d)"
    printf '%s:%s\n' "$ANSIBLE_USER" "$ACCOUNT_PASSWORD" | sudo chpasswd
    ;;
  locked)
    sudo passwd -l "$ANSIBLE_USER" >/dev/null
    ;;
  keep)
    :
    ;;
esac

case "$SUDO_MODE" in
  nopasswd)
    printf '%s\n' "$ANSIBLE_USER ALL=(ALL) NOPASSWD:ALL" | sudo tee "/etc/sudoers.d/90-track-$ANSIBLE_USER" >/dev/null
    sudo chmod 440 "/etc/sudoers.d/90-track-$ANSIBLE_USER"
    ;;
  password)
    printf '%s\n' "$ANSIBLE_USER ALL=(ALL) ALL" | sudo tee "/etc/sudoers.d/90-track-$ANSIBLE_USER" >/dev/null
    sudo chmod 440 "/etc/sudoers.d/90-track-$ANSIBLE_USER"
    ;;
  none)
    sudo rm -f "/etc/sudoers.d/90-track-$ANSIBLE_USER"
    ;;
esac
EOF

    echo "    Verifying $ANSIBLE_USER@$target_host..."
    ssh -o BatchMode=yes "$ANSIBLE_USER@$target_host" "whoami && hostname" || return 1
    if [ "$SUDO_MODE" = "nopasswd" ]; then
        ssh -o BatchMode=yes "$ANSIBLE_USER@$target_host" "sudo -n true && echo sudo-nopasswd-ok" || return 1
    fi
}

append_single_inventory() {
    local target_host="$1"
    if [ -z "$INVENTORY_PATH" ]; then
        return 0
    fi
    mkdir -p "$(dirname "$INVENTORY_PATH")"
    touch "$INVENTORY_PATH"
    if ! grep -qx "\\[$GROUP\\]" "$INVENTORY_PATH"; then
        printf '\n[%s]\n' "$GROUP" >> "$INVENTORY_PATH"
    fi
    if ! grep -qE "^${target_host}([[:space:]]|$)" "$INVENTORY_PATH"; then
        printf '%s ansible_host=%s ansible_user=%s\n' "$target_host" "$target_host" "$ANSIBLE_USER" >> "$INVENTORY_PATH"
        echo "Added $target_host to $INVENTORY_PATH under [$GROUP]."
    else
        echo "$target_host already exists in $INVENTORY_PATH; not appending duplicate."
    fi
}

inventory_hosts_tsv() {
    python3 - "$FROM_INVENTORY" "$HOST_VAR" "$LOGIN_VAR" "${LIMITS[@]}" <<'PY'
from __future__ import annotations

import shlex
import sys
from pathlib import Path

path = Path(sys.argv[1])
host_var = sys.argv[2]
login_var = sys.argv[3]
limits = set(sys.argv[4:])

current_group = "ungrouped"
hosts: dict[str, dict[str, object]] = {}

for raw in path.read_text(encoding="utf-8").splitlines():
    line = raw.strip()
    if not line or line.startswith(("#", ";")):
        continue
    if line.startswith("[") and line.endswith("]"):
        name = line[1:-1].strip()
        if name and ":" not in name:
            current_group = name
        continue
    if line.startswith("["):
        continue

    try:
        parts = shlex.split(line, comments=True)
    except ValueError as exc:
        print(f"Skipping unparsable inventory line: {raw} ({exc})", file=sys.stderr)
        continue
    if not parts:
        continue

    name = parts[0]
    item = hosts.setdefault(name, {"groups": set(), "vars": {}})
    item["groups"].add(current_group)
    for part in parts[1:]:
        if "=" in part:
            key, value = part.split("=", 1)
            item["vars"][key] = value

for name in sorted(hosts):
    groups = sorted(hosts[name]["groups"])
    values = hosts[name]["vars"]
    if limits and name not in limits and not limits.intersection(groups):
        continue
    target = values.get(host_var, name)
    login = values.get(login_var, "")
    if not login:
        print(f"Skipping {name}: missing {login_var}=...", file=sys.stderr)
        continue
    print("\t".join([name, str(target), str(login), ",".join(groups)]))
PY
}

activate_inventory_user() {
    local path="$1"
    local inventory_name="$2"
    python3 - "$path" "$inventory_name" "$LOGIN_VAR" "$ANSIBLE_USER" <<'PY'
from __future__ import annotations

import re
import sys
from pathlib import Path

path = Path(sys.argv[1])
host_name = sys.argv[2]
login_var = sys.argv[3]
new_user = sys.argv[4]

lines = path.read_text(encoding="utf-8").splitlines()
changed = False
out = []

for line in lines:
    stripped = line.lstrip()
    if not stripped or stripped.startswith(("#", ";", "[")):
        out.append(line)
        continue
    parts = stripped.split(maxsplit=1)
    if parts[0] != host_name:
        out.append(line)
        continue
    if re.search(rf"(^|\\s){re.escape(login_var)}=", line):
        line = re.sub(rf"(^|\\s){re.escape(login_var)}=\\S+", rf"\\1{login_var}={new_user}", line)
    else:
        line = f"{line} {login_var}={new_user}"
    changed = True
    out.append(line)

if changed:
    path.write_text("\\n".join(out) + "\\n", encoding="utf-8")
else:
    raise SystemExit(f"Host not found for inventory rewrite: {host_name}")
PY
}

if [ -z "$FROM_INVENTORY" ]; then
    prepare_account_password
    bootstrap_one "$HOST" "$LOGIN_USER" "$HOST"
    append_single_inventory "$HOST"
    echo
    echo "Bootstrap complete."
    exit 0
fi

echo "Inventory bootstrap mode"
echo "Inventory: $FROM_INVENTORY"
echo "Login var: $LOGIN_VAR"
echo "Host var: $HOST_VAR"
echo "Management user: $ANSIBLE_USER"
echo "Password mode: $PASSWORD_MODE"
echo "Sudo mode: $SUDO_MODE"
if [ "${#LIMITS[@]}" -gt 0 ]; then
    echo "Limits: ${LIMITS[*]}"
fi
if [ "$ACTIVATE_ANSIBLE_USER" = "1" ]; then
    echo "Successful hosts will be rewritten to $LOGIN_VAR=$ANSIBLE_USER."
else
    echo "Inventory will not be rewritten. Pass --activate-ansible-user to flip successful hosts."
fi

mapfile -t HOST_ROWS < <(inventory_hosts_tsv)
if [ "${#HOST_ROWS[@]}" -eq 0 ]; then
    echo "No bootstrap targets found in inventory." >&2
    exit 1
fi

prepare_account_password

FAILURES=0
for row in "${HOST_ROWS[@]}"; do
    IFS=$'\t' read -r inventory_name target_host login_user groups <<< "$row"
    if bootstrap_one "$target_host" "$login_user" "$inventory_name"; then
        if [ "$ACTIVATE_ANSIBLE_USER" = "1" ] && [ "$DRY_RUN" != "1" ]; then
            activate_inventory_user "$FROM_INVENTORY" "$inventory_name"
            echo "    Updated $inventory_name to $LOGIN_VAR=$ANSIBLE_USER in $FROM_INVENTORY."
        elif [ "$ACTIVATE_ANSIBLE_USER" = "1" ]; then
            echo "    DRY-RUN: would update $inventory_name to $LOGIN_VAR=$ANSIBLE_USER in $FROM_INVENTORY."
        fi
    else
        FAILURES=$((FAILURES + 1))
        echo "ERROR: bootstrap failed for $inventory_name ($target_host)." >&2
        if [ "$STOP_ON_ERROR" = "1" ]; then
            exit 1
        fi
    fi
done

echo
if [ "$FAILURES" -gt 0 ]; then
    echo "Bootstrap finished with $FAILURES failure(s)." >&2
    exit 1
fi
echo "Bootstrap complete for ${#HOST_ROWS[@]} host(s)."
