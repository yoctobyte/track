from __future__ import annotations

from datetime import UTC, datetime

from flask import Flask, Response, render_template

from netinventory.auth import load_or_create_shared_secret
from netinventory.config import get_app_paths, get_hub_settings
from netinventory.storage.db import Database


def create_hub_web() -> Flask:
    app = Flask(__name__, template_folder="templates")
    app.config["NETINV_PATHS"] = get_app_paths()
    app.config["NETINV_SETTINGS"] = get_hub_settings()

    @app.context_processor
    def inject_globals():
        return {
            "hub_settings": app.config["NETINV_SETTINGS"],
            "now": datetime.now(UTC),
        }

    @app.get("/")
    def index():
        paths = app.config["NETINV_PATHS"]
        settings = app.config["NETINV_SETTINGS"]
        db = Database(paths)
        db.upsert_task_definitions([])
        secret = load_or_create_shared_secret(paths)
        status = db.get_status()
        networks = db.list_networks()[:12]
        recent_runs = db.list_recent_task_runs(limit=12)
        context_rows = db.list_user_context()[:12]
        network_rows = []
        for network in networks:
            latest = db.get_latest_observation(network.network_id)
            facts = latest.get("facts", {}) if latest else {}
            network_rows.append(
                {
                    "summary": network.to_dict(),
                    "latest": latest,
                    "facts": facts,
                }
            )
        return render_template(
            "hub_index.html",
            title="NetInventory",
            subtitle="Agent / Hub / Web",
            status=status.to_dict(),
            network_rows=network_rows,
            recent_runs=recent_runs,
            context_rows=context_rows,
            shared_secret=secret,
            public_url=f"{settings.track_base_url}{settings.public_path}",
            service_bind=settings.ui_bind,
            github_repo=settings.github_repo,
        )

    @app.get("/agents/bootstrap.sh")
    def bootstrap_script():
        settings = app.config["NETINV_SETTINGS"]
        script = f"""#!/bin/bash
set -euo pipefail

REPO_URL="${{TRACK_GITHUB_REPO:-{settings.github_repo}}}"
WORKDIR="${{TRACK_AGENT_DIR:-$HOME/track-agent}}"
TRACK_BASE_URL="${{TRACK_BASE_URL:-{settings.track_base_url}}}"
NETINV_PUBLIC_PATH="${{NETINV_PUBLIC_PATH:-{settings.public_path}}}"

if [ ! -d "$WORKDIR/.git" ]; then
  git clone "$REPO_URL" "$WORKDIR"
else
  git -C "$WORKDIR" pull --ff-only
fi

cd "$WORKDIR/netinventory-client"

if [ ! -d venv-agent ]; then
  python3 -m venv venv-agent
fi

./venv-agent/bin/pip install -q -e .

cat <<EOF
NetInventory agent prepared.

Useful commands:
  ./venv-agent/bin/netinv status
  ./venv-agent/bin/netinv collect --once
  ./venv-agent/bin/netinv export

Hub:
  $TRACK_BASE_URL$NETINV_PUBLIC_PATH

Notes:
  - privileged local capture stays on the laptop/agent side
  - upload/sync remains a separate flow
  - annotate physical context manually while in the field
EOF
"""
        return Response(
            script,
            mimetype="text/x-shellscript",
            headers={"Content-Disposition": 'attachment; filename="netinventory-bootstrap.sh"'},
        )

    return app


def run_hub_web(bind: str) -> int:
    host, port = _parse_bind(bind)
    app = create_hub_web()
    app.run(host=host, port=port, debug=False)
    return 0


def _parse_bind(bind: str) -> tuple[str, int]:
    if ":" not in bind:
        raise ValueError(f"invalid bind address: {bind!r}")
    host, port_text = bind.rsplit(":", 1)
    return host, int(port_text)
