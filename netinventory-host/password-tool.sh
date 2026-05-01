#!/usr/bin/env bash
set -euo pipefail

python3 - <<'PY'
import secrets

roles = {
    "admin": "NETINVENTORY_ADMIN_PASSWORD",
    "privileged": "NETINVENTORY_PRIVILEGED_PASSWORD",
    "user": "NETINVENTORY_USER_PASSWORD",
}

print("# NetInventory Host role passwords")
print("# Store these in your service environment, not in git.")
for role, env_name in roles.items():
    password = secrets.token_urlsafe(18)
    print(f"export {env_name}='{password}'  # {role}")
PY
