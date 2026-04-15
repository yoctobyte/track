#!/bin/bash
set -euo pipefail

if [ "$#" -lt 1 ]; then
    echo "Usage: tools/check-host.sh HOST [USER]" >&2
    exit 2
fi

HOST="$1"
USER="${2:-ansible}"

echo "Checking SSH connectivity to $USER@$HOST"
ssh -o BatchMode=yes "$USER@$HOST" "whoami; hostname; command -v sudo >/dev/null && sudo -n true && echo sudo-ok || echo sudo-needs-password"
