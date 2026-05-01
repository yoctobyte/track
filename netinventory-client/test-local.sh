#!/usr/bin/env bash
set -euo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV="$DIR/venv"

if [ ! -d "$VENV" ]; then
  python3 -m venv "$VENV"
fi

"$VENV/bin/python" -m pip install -q -e "$DIR"

NETINV_HOME="$(mktemp -d)"
export NETINV_HOME
trap 'rm -rf "$NETINV_HOME"' EXIT

unset TRACK_BASE_URL
unset TRACK_GITHUB_REPO
unset NETINV_PUBLIC_PATH
unset NETINV_UI_BIND

"$VENV/bin/python" - <<'PY'
from netinventory.config import get_hub_settings
from netinventory.hub_web import create_hub_web

settings = get_hub_settings()
assert settings.track_base_url == ""
assert settings.public_path == "/"
assert settings.github_repo == "git@github.com:yoctobyte/track.git"
assert settings.ui_bind == "127.0.0.1:8888"

client = create_hub_web().test_client()
response = client.get("/agents/bootstrap.sh")
assert response.status_code == 200
body = response.get_data(as_text=True)
assert "git@github.com:yoctobyte/track.git" in body
assert ("https://github.com/" + "praktijkpioniers" + "/track.git") not in body
assert ("track." + "praktijkpioniers" + ".com") not in body
assert 'NETINV_PUBLIC_PATH="${NETINV_PUBLIC_PATH:-/}"' in body
assert "/netinventory-client/" not in body

print("netinventory-client local tests passed")
PY
