#!/usr/bin/env bash
set -euo pipefail

python3 - <<'PY'
import argparse
import secrets

parser = argparse.ArgumentParser(description="Generate NetInventory Host role passwords.")
parser.add_argument("environment", nargs="?", help="Optional environment slug, e.g. testing, museum, lab.")
args = parser.parse_args()

def env_name(role):
    if not args.environment:
        return f"NETINVENTORY_{role.upper()}_PASSWORD"
    slug = "".join(ch.upper() if ch.isalnum() else "_" for ch in args.environment)
    return f"NETINVENTORY_{slug}_{role.upper()}_PASSWORD"

print("# NetInventory Host role passwords")
print("# Store these in your service environment, not in git.")
if args.environment:
    print(f"# Environment: {args.environment}")
for role in ("admin", "privileged", "user"):
    password = secrets.token_urlsafe(18)
    print(f"export {env_name(role)}='{password}'  # {role}")
PY
