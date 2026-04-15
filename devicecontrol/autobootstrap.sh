#!/bin/bash
set -euo pipefail

DEVICECONTROL_DIR="$(cd "$(dirname "$0")" && pwd)"
ENV_ROOT="$DEVICECONTROL_DIR/data/environments"
BOOTSTRAP="$DEVICECONTROL_DIR/bootstrap-host.sh"

usage() {
    cat <<'EOF'
Usage:
  ./autobootstrap.sh ENVIRONMENT [options]
  ./autobootstrap.sh --inventory PATH [options]

Examples:
  ./autobootstrap.sh testing
  ./autobootstrap.sh museum --dry-run
  ./autobootstrap.sh lab --limit media_players

The positional ENVIRONMENT form resolves to:
  devicecontrol/data/environments/<ENVIRONMENT>/inventory.ini

Options:
  --inventory PATH              Override: use this inventory file directly.
  --limit HOST_OR_GROUP         Limit to one host or group. Can be repeated.
  --ansible-user USER           Management user to verify/create. Default: ansible.
  --login-var NAME              Current inventory SSH user var. Default: ansible_user.
  --bootstrap-var NAME          Optional original login var. Default: bootstrap_user.
  --host-var NAME               Inventory target address var. Default: ansible_host.
  --key PATH                    Public SSH key to install when bootstrapping.
  --password-mode MODE          Passed to bootstrap-host.sh. Default: stored.
  --sudo-mode MODE              Passed to bootstrap-host.sh. Default: nopasswd.
  --dry-run                     Show checks/planned bootstrap/update steps only.
  --stop-on-error               Stop if bootstrap-host.sh fails.

Workflow:
  1. Parse inventory.
  2. Check whether ansible@host works with SSH keys.
  3. Skip reachable hosts.
  4. Bootstrap unreachable hosts through bootstrap_user, or through ansible_user
     when ansible_user is still the known human/current login user.
  5. Recheck ansible@host.
  6. Rewrite successful original inventory lines to ansible_user=ansible and
     preserve the old login as bootstrap_user=...

For first import, inventory lines usually look like:
  redacted-host ansible_host=100.x.y.z ansible_user=fons

After successful autobootstrap:
  redacted-host ansible_host=100.x.y.z ansible_user=ansible bootstrap_user=fons
EOF
}

INVENTORY=""
ENVIRONMENT=""
ANSIBLE_USER="ansible"
LOGIN_VAR="ansible_user"
BOOTSTRAP_VAR="bootstrap_user"
HOST_VAR="ansible_host"
PASSWORD_MODE="stored"
SUDO_MODE="nopasswd"
KEY_PATH=""
DRY_RUN=0
STOP_ON_ERROR=0
LIMITS=()

while [ "$#" -gt 0 ]; do
    case "$1" in
        --inventory|--from-inventory) INVENTORY="${2:-}"; shift 2 ;;
        --limit) LIMITS+=("${2:-}"); shift 2 ;;
        --ansible-user) ANSIBLE_USER="${2:-}"; shift 2 ;;
        --login-var) LOGIN_VAR="${2:-}"; shift 2 ;;
        --bootstrap-var) BOOTSTRAP_VAR="${2:-}"; shift 2 ;;
        --host-var) HOST_VAR="${2:-}"; shift 2 ;;
        --key) KEY_PATH="${2:-}"; shift 2 ;;
        --password-mode) PASSWORD_MODE="${2:-}"; shift 2 ;;
        --sudo-mode) SUDO_MODE="${2:-}"; shift 2 ;;
        --dry-run) DRY_RUN=1; shift ;;
        --stop-on-error) STOP_ON_ERROR=1; shift ;;
        -h|--help) usage; exit 0 ;;
        --*) echo "Unknown option: $1" >&2; usage; exit 2 ;;
        *)
            if [ -n "$ENVIRONMENT" ]; then
                echo "Unexpected argument: $1 (environment already set to $ENVIRONMENT)" >&2
                exit 2
            fi
            ENVIRONMENT="$1"
            shift
            ;;
    esac
done

if [ -n "$ENVIRONMENT" ] && [ -n "$INVENTORY" ]; then
    echo "Pass either ENVIRONMENT or --inventory, not both." >&2
    exit 2
fi

if [ -n "$ENVIRONMENT" ]; then
    if ! printf '%s' "$ENVIRONMENT" | grep -qE '^[a-z0-9-]+$'; then
        echo "Invalid environment name: $ENVIRONMENT (use [a-z0-9-]+)" >&2
        exit 2
    fi
    INVENTORY="$ENV_ROOT/$ENVIRONMENT/inventory.ini"
fi

if [ -z "$INVENTORY" ]; then
    echo "ERROR: pass an environment name (e.g. 'museum') or --inventory PATH." >&2
    echo >&2
    usage >&2
    exit 2
fi

if [ ! -f "$INVENTORY" ]; then
    echo "Inventory not found: $INVENTORY" >&2
    exit 1
fi

case "$PASSWORD_MODE" in
    stored|prompt|random|locked|keep) ;;
    *) echo "Invalid --password-mode: $PASSWORD_MODE" >&2; exit 2 ;;
esac

case "$SUDO_MODE" in
    nopasswd|password|none) ;;
    *) echo "Invalid --sudo-mode: $SUDO_MODE" >&2; exit 2 ;;
esac

if [ ! -x "$BOOTSTRAP" ]; then
    echo "Bootstrap helper is not executable: $BOOTSTRAP" >&2
    exit 1
fi

TMP_DIR="$(mktemp -d)"
PLAN_TSV="$TMP_DIR/plan.tsv"
BOOTSTRAP_INVENTORY="$TMP_DIR/bootstrap.ini"
trap 'rm -rf "$TMP_DIR"' EXIT

python3 - "$INVENTORY" "$HOST_VAR" "$LOGIN_VAR" "$BOOTSTRAP_VAR" "$ANSIBLE_USER" "${LIMITS[@]}" > "$PLAN_TSV" <<'PY'
from __future__ import annotations

import shlex
import sys
from pathlib import Path

path = Path(sys.argv[1])
host_var = sys.argv[2]
login_var = sys.argv[3]
bootstrap_var = sys.argv[4]
ansible_user = sys.argv[5]
limits = set(sys.argv[6:])

current_group = "ungrouped"
hosts: dict[str, dict[str, object]] = {}

for line_no, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
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
        print(f"Skipping unparsable inventory line {line_no}: {raw} ({exc})", file=sys.stderr)
        continue
    if not parts:
        continue
    name = parts[0]
    item = hosts.setdefault(name, {"groups": set(), "vars": {}, "line_no": line_no})
    item["groups"].add(current_group)
    item["line_no"] = line_no
    for part in parts[1:]:
        if "=" in part:
            key, value = part.split("=", 1)
            item["vars"][key] = value

EMPTY = "__TRACK_EMPTY__"

def clean(value: str) -> str:
    return value if value else EMPTY

for name in sorted(hosts):
    groups = sorted(hosts[name]["groups"])
    values = hosts[name]["vars"]
    if limits and name not in limits and not limits.intersection(groups):
        continue
    target = str(values.get(host_var, name))
    current_login = str(values.get(login_var, ""))
    saved_bootstrap = str(values.get(bootstrap_var, ""))
    if saved_bootstrap:
        bootstrap_login = saved_bootstrap
    elif current_login and current_login != ansible_user:
        bootstrap_login = current_login
    else:
        bootstrap_login = ""
    print("\t".join([clean(name), clean(target), clean(current_login), clean(saved_bootstrap), clean(bootstrap_login), clean(",".join(groups))]))
PY

if [ ! -s "$PLAN_TSV" ]; then
    echo "No hosts found in inventory for the selected limits." >&2
    exit 1
fi

check_ansible() {
    local target="$1"
    if [ "$SUDO_MODE" = "nopasswd" ]; then
        ssh -o BatchMode=yes -o ConnectTimeout=6 "$ANSIBLE_USER@$target" "whoami >/dev/null && sudo -n true" >/dev/null 2>&1
    else
        ssh -o BatchMode=yes -o ConnectTimeout=6 "$ANSIBLE_USER@$target" "whoami >/dev/null" >/dev/null 2>&1
    fi
}

echo "Autobootstrap inventory: $INVENTORY"
echo "Management user: $ANSIBLE_USER"
echo "Password mode: $PASSWORD_MODE"
echo "Sudo mode: $SUDO_MODE"
if [ "${#LIMITS[@]}" -gt 0 ]; then
    echo "Limits: ${LIMITS[*]}"
fi
echo

NEEDS_BOOTSTRAP=()
UNBOOTSTRAPPABLE=()
REACHABLE=()

decode_empty() {
    if [ "$1" = "__TRACK_EMPTY__" ]; then
        printf ''
    else
        printf '%s' "$1"
    fi
}

decode_row_vars() {
    groups="${groups:-__TRACK_EMPTY__}"
    name="$(decode_empty "$name")"
    target="$(decode_empty "$target")"
    current_login="$(decode_empty "$current_login")"
    saved_bootstrap="$(decode_empty "$saved_bootstrap")"
    bootstrap_login="$(decode_empty "$bootstrap_login")"
    groups="$(decode_empty "$groups")"
}

while IFS=$'\t' read -r name target current_login saved_bootstrap bootstrap_login groups; do
    encoded_row="$name"$'\t'"$target"$'\t'"$current_login"$'\t'"$saved_bootstrap"$'\t'"$bootstrap_login"$'\t'"$groups"
    decode_row_vars
    printf 'Checking %-24s %s ... ' "$name" "$target"
    if check_ansible "$target"; then
        echo "ansible reachable"
        REACHABLE+=("$encoded_row")
    else
        echo "needs bootstrap"
        if [ -z "$bootstrap_login" ]; then
            UNBOOTSTRAPPABLE+=("$encoded_row")
        else
            NEEDS_BOOTSTRAP+=("$encoded_row")
        fi
    fi
done < "$PLAN_TSV"

if [ "${#UNBOOTSTRAPPABLE[@]}" -gt 0 ]; then
    echo
    echo "Cannot bootstrap these hosts because no bootstrap login is known:"
    for row in "${UNBOOTSTRAPPABLE[@]}"; do
        IFS=$'\t' read -r name target current_login saved_bootstrap bootstrap_login groups <<< "$row"
        decode_row_vars
        echo "  $name ($target): add $BOOTSTRAP_VAR=<known-login> or set $LOGIN_VAR to the current login user"
    done
fi

if [ "${#NEEDS_BOOTSTRAP[@]}" -eq 0 ]; then
    echo
    echo "No bootstrap needed."
else
    BOOTSTRAP_FAILED=0
    {
        echo "[autobootstrap]"
        for row in "${NEEDS_BOOTSTRAP[@]}"; do
            IFS=$'\t' read -r name target current_login saved_bootstrap bootstrap_login groups <<< "$row"
            decode_row_vars
            printf '%s %s=%s %s=%s\n' "$name" "$HOST_VAR" "$target" "$LOGIN_VAR" "$bootstrap_login"
        done
    } > "$BOOTSTRAP_INVENTORY"

    echo
    echo "Bootstrap targets:"
    cat "$BOOTSTRAP_INVENTORY"

    BOOTSTRAP_ARGS=(
        --from-inventory "$BOOTSTRAP_INVENTORY"
        --ansible-user "$ANSIBLE_USER"
        --login-var "$LOGIN_VAR"
        --host-var "$HOST_VAR"
        --password-mode "$PASSWORD_MODE"
        --sudo-mode "$SUDO_MODE"
    )
    if [ -n "$KEY_PATH" ]; then
        BOOTSTRAP_ARGS+=(--key "$KEY_PATH")
    fi
    if [ "$DRY_RUN" = "1" ]; then
        BOOTSTRAP_ARGS+=(--dry-run)
    fi
    if [ "$STOP_ON_ERROR" = "1" ]; then
        BOOTSTRAP_ARGS+=(--stop-on-error)
    fi

    "$BOOTSTRAP" "${BOOTSTRAP_ARGS[@]}" || {
        BOOTSTRAP_FAILED=1
        if [ "$STOP_ON_ERROR" = "1" ]; then
            exit 1
        fi
        echo "Bootstrap helper reported failures; rechecking reachable hosts anyway." >&2
    }
fi

UPDATE_TSV="$TMP_DIR/update.tsv"
: > "$UPDATE_TSV"

for row in "${REACHABLE[@]}" "${NEEDS_BOOTSTRAP[@]}"; do
    [ -n "$row" ] || continue
    IFS=$'\t' read -r name target current_login saved_bootstrap bootstrap_login groups <<< "$row"
    decode_row_vars
    if [ "$DRY_RUN" = "1" ]; then
        if [ "$current_login" != "$ANSIBLE_USER" ]; then
            echo "DRY-RUN: would mark $name as $LOGIN_VAR=$ANSIBLE_USER and preserve $BOOTSTRAP_VAR=${bootstrap_login:-$current_login}"
        fi
        continue
    fi
    if check_ansible "$target"; then
        preserved="${saved_bootstrap:-}"
        if [ -z "$preserved" ] && [ -n "$current_login" ] && [ "$current_login" != "$ANSIBLE_USER" ]; then
            preserved="$current_login"
        fi
        printf '%s\t%s\t%s\n' "$name" "$ANSIBLE_USER" "$preserved" >> "$UPDATE_TSV"
    fi
done

if [ "$DRY_RUN" = "1" ]; then
    echo
    echo "Dry-run complete; inventory not modified."
    exit 0
fi

if [ -s "$UPDATE_TSV" ]; then
    python3 - "$INVENTORY" "$LOGIN_VAR" "$BOOTSTRAP_VAR" "$UPDATE_TSV" <<'PY'
from __future__ import annotations

import re
import shlex
import sys
from pathlib import Path

inventory = Path(sys.argv[1])
login_var = sys.argv[2]
bootstrap_var = sys.argv[3]
updates_path = Path(sys.argv[4])

updates = {}
for raw in updates_path.read_text(encoding="utf-8").splitlines():
    if not raw:
        continue
    host, new_login, bootstrap_login = raw.split("\t")
    updates[host] = (new_login, bootstrap_login)

def replace_or_append(line: str, key: str, value: str) -> str:
    if not value:
        return line
    pattern = rf"(^|\s){re.escape(key)}=\S+"
    if re.search(pattern, line):
        return re.sub(pattern, rf"\1{key}={value}", line)
    return f"{line} {key}={shlex.quote(value)}"

out = []
changed = 0
for line in inventory.read_text(encoding="utf-8").splitlines():
    stripped = line.lstrip()
    if not stripped or stripped.startswith(("#", ";", "[")):
        out.append(line)
        continue
    parts = stripped.split(maxsplit=1)
    host = parts[0]
    if host not in updates:
        out.append(line)
        continue
    new_login, bootstrap_login = updates[host]
    line = replace_or_append(line, login_var, new_login)
    if bootstrap_login and bootstrap_login != new_login:
        line = replace_or_append(line, bootstrap_var, bootstrap_login)
    changed += 1
    out.append(line)

inventory.write_text("\n".join(out) + "\n", encoding="utf-8")
print(f"Updated {changed} inventory host line(s).")
PY
fi

echo
if [ "${BOOTSTRAP_FAILED:-0}" = "1" ]; then
    echo "Autobootstrap finished with bootstrap failures." >&2
    exit 1
fi
echo "Autobootstrap complete."
