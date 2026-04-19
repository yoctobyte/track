#!/bin/bash
set -u

# Source config file if it exists
CONF_FILE="/etc/netinventory-minimal.conf"
if [ -r "$CONF_FILE" ]; then
  # shellcheck disable=SC1090
  . "$CONF_FILE"
fi

TARGET_URL="${TRACK_SIMPLE_URL:-}"
CLIENT_ID="${TRACK_CLIENT_ID:-}"

if [ -z "$TARGET_URL" ] || [ -z "$CLIENT_ID" ]; then
  echo "ERROR: TRACK_SIMPLE_URL or TRACK_CLIENT_ID not set. Please configure /etc/netinventory-minimal.conf" >&2
  exit 1
fi

export HOSTNAME_VALUE="$(hostname 2>/dev/null || echo unknown)"
export IP_BRIEF_VALUE="$(ip -brief address 2>/dev/null | tr '\n' ';' || true)"
export ROUTE_VALUE="$(ip route show 2>/dev/null | tr '\n' ';' || true)"
export NEIGH_VALUE="$(ip neigh show 2>/dev/null | tr '\n' ';' || true)"
export WLAN_LINK_VALUE="$(iw dev wlan0 link 2>/dev/null | tr '\n' ';' || true)"

export EXTERNAL_IP_VALUE=""
if command -v curl >/dev/null 2>&1; then
  EXTERNAL_IP_VALUE="$(curl -4fsS --max-time 4 https://api.ipify.org 2>/dev/null || true)"
elif command -v wget >/dev/null 2>&1; then
  EXTERNAL_IP_VALUE="$(wget -4qO- --timeout=4 https://api.ipify.org 2>/dev/null || true)"
fi

PAYLOAD="$(python3 - <<'PY'
import json
import os

def split_semicolon(value: str):
    return [item.strip() for item in value.split(";") if item.strip()]

payload = {
    "kind": "script-minimal",
    "description": os.environ.get("HOSTNAME_VALUE", ""),
    "host": {
        "hostname": os.environ.get("HOSTNAME_VALUE", ""),
    },
    "network": {
        "interface_addresses": split_semicolon(os.environ.get("IP_BRIEF_VALUE", "")),
        "routes": split_semicolon(os.environ.get("ROUTE_VALUE", "")),
        "arp_table": split_semicolon(os.environ.get("NEIGH_VALUE", "")),
        "external_ip": os.environ.get("EXTERNAL_IP_VALUE", ""),
        "wlan0_link": split_semicolon(os.environ.get("WLAN_LINK_VALUE", "")),
    }
}
print(json.dumps(payload, ensure_ascii=True))
PY
)"

if command -v curl >/dev/null 2>&1; then
  curl -fsS "$TARGET_URL" \
    -H "Content-Type: application/json" \
    -H "X-Track-Client-Id: $CLIENT_ID" \
    --data "$PAYLOAD" >/dev/null
elif command -v wget >/dev/null 2>&1; then
  wget -qO- \
    --header="Content-Type: application/json" \
    --header="X-Track-Client-Id: $CLIENT_ID" \
    --post-data="$PAYLOAD" \
    "$TARGET_URL" >/dev/null
else
  echo "curl or wget is required" >&2
  exit 1
fi
