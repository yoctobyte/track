from __future__ import annotations

import json
import os
import secrets
from datetime import UTC, datetime
from pathlib import Path

from flask import Flask, Response, render_template


BASE_DIR = Path(__file__).resolve().parent.parent


def load_secret_key() -> str:
    configured = os.environ.get("NETINVENTORY_HOST_SECRET_KEY", "").strip()
    if configured:
        return configured
    secret_path = BASE_DIR / ".secret_key"
    if secret_path.exists():
        return secret_path.read_text(encoding="utf-8").strip()
    secret = f"netinventory-host-{secrets.token_urlsafe(32)}"
    secret_path.write_text(secret + "\n", encoding="utf-8")
    secret_path.chmod(0o600)
    return secret


def instance_name() -> str:
    return os.environ.get("NETINVENTORY_HOST_INSTANCE", "testing").strip() or "testing"


def data_root() -> Path:
    configured = os.environ.get("NETINVENTORY_HOST_DATA_DIR", "").strip()
    if configured:
        root = Path(configured).expanduser()
    else:
        root = BASE_DIR / "data" / "environments" / instance_name()
    root.mkdir(parents=True, exist_ok=True)
    return root


def runtime_paths() -> dict[str, Path]:
    root = data_root()
    paths = {
        "root": root,
        "clients": root / "clients",
        "host_reports": root / "host-reports",
        "downloads": root / "downloads",
        "manifests": root / "manifests",
    }
    for path in paths.values():
        path.mkdir(parents=True, exist_ok=True)
    return paths


def load_manifest(paths: dict[str, Path]) -> dict[str, object]:
    manifest_path = paths["manifests"] / "overview.json"
    if not manifest_path.exists():
        return {
            "last_updated": None,
            "client_packages": [],
            "registered_hosts": [],
            "recent_ingest": [],
        }
    with manifest_path.open(encoding="utf-8") as handle:
        loaded = json.load(handle)
    if isinstance(loaded, dict):
        return loaded
    return {
        "last_updated": None,
        "client_packages": [],
        "registered_hosts": [],
        "recent_ingest": [],
    }


def create_app() -> Flask:
    app = Flask(__name__, template_folder=str(BASE_DIR / "templates"))
    app.config["SECRET_KEY"] = load_secret_key()
    app.config["NETINV_HOST_INSTANCE"] = instance_name()
    app.config["NETINV_HOST_BIND"] = os.environ.get("NETINVENTORY_HOST_BIND", "127.0.0.1").strip() or "127.0.0.1"
    app.config["NETINV_HOST_PORT"] = int(os.environ.get("NETINVENTORY_HOST_PORT", "8888").strip() or "8888")
    app.config["NETINV_HOST_TRACK_BASE"] = (
        os.environ.get("TRACK_BASE_URL", "https://track.praktijkpioniers.com").rstrip("/")
    )
    app.config["NETINV_HOST_PUBLIC_PATH"] = "/netinventory/"
    app.config["NETINV_CLIENT_PUBLIC_PATH"] = "/netinventory-client/"
    app.config["NETINV_GITHUB_REPO"] = os.environ.get(
        "TRACK_GITHUB_REPO",
        "https://github.com/yoctobyte/track.git",
    ).strip()

    @app.context_processor
    def inject_globals():
        return {
            "instance_name": app.config["NETINV_HOST_INSTANCE"],
            "track_base": app.config["NETINV_HOST_TRACK_BASE"],
            "netinventory_public_path": app.config["NETINV_HOST_PUBLIC_PATH"],
            "netinventory_client_public_path": app.config["NETINV_CLIENT_PUBLIC_PATH"],
            "github_repo": app.config["NETINV_GITHUB_REPO"],
            "now": datetime.now(UTC),
        }

    @app.get("/")
    def index():
        paths = runtime_paths()
        manifest = load_manifest(paths)
        client_packages = manifest.get("client_packages", [])
        registered_hosts = manifest.get("registered_hosts", [])
        recent_ingest = manifest.get("recent_ingest", [])
        cards = [
            {
                "label": "Client Packages",
                "value": str(len(client_packages)),
                "hint": "Published laptop-side bundles and bootstrap targets.",
            },
            {
                "label": "Registered Hosts",
                "value": str(len(registered_hosts)),
                "hint": "Remote devices that can later report passive statistics.",
            },
            {
                "label": "Recent Ingest Events",
                "value": str(len(recent_ingest)),
                "hint": "Most recent uploads or synchronization attempts recorded here.",
            },
        ]
        return render_template(
            "index.html",
            title="NetInventory Host",
            subtitle="Host-side intake, publishing, and aggregation surface",
            cards=cards,
            manifest=manifest,
            client_packages=client_packages,
            registered_hosts=registered_hosts,
            recent_ingest=recent_ingest,
            paths={key: str(value) for key, value in paths.items()},
        )

    @app.get("/downloads/netinventory-client-bootstrap.sh")
    def download_bootstrap():
        repo = app.config["NETINV_GITHUB_REPO"]
        script = f"""#!/bin/bash
set -euo pipefail

REPO_URL="${{TRACK_GITHUB_REPO:-{repo}}}"
WORKDIR="${{TRACK_NETINVENTORY_CLIENT_DIR:-$HOME/track-netinventory-client}}"

if [ ! -d "$WORKDIR/.git" ]; then
  git clone "$REPO_URL" "$WORKDIR"
else
  git -C "$WORKDIR" pull --ff-only
fi

cd "$WORKDIR/netinventory-client"
./run-track.sh
"""
        return Response(
            script,
            mimetype="text/x-shellscript",
            headers={"Content-Disposition": 'attachment; filename="netinventory-client-bootstrap.sh"'},
        )

    @app.get("/health")
    def health():
        return {
            "status": "ok",
            "service": "netinventory-host",
            "instance": app.config["NETINV_HOST_INSTANCE"],
            "timestamp": datetime.now(UTC).isoformat(),
        }

    return app
