from __future__ import annotations

import json
import os
import platform
import secrets
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from flask import Flask, Response, jsonify, render_template, request


BASE_DIR = Path(__file__).resolve().parent.parent
SIMPLE_DIR = BASE_DIR.parent / "netinventory-simple"


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
        "simple_registrations": root / "simple-registrations.jsonl",
        "simple_upload_token": root / ".simple-upload-token",
    }
    for key, path in paths.items():
        if key in {"simple_registrations", "simple_upload_token"}:
            continue
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


def load_or_create_simple_upload_token() -> str:
    token_path = runtime_paths()["simple_upload_token"]
    if token_path.exists():
        return token_path.read_text(encoding="utf-8").strip()
    token = secrets.token_urlsafe(24)
    token_path.write_text(token + "\n", encoding="utf-8")
    token_path.chmod(0o600)
    return token


def read_simple_registrations(limit: int = 25) -> list[dict[str, Any]]:
    path = runtime_paths()["simple_registrations"]
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return list(reversed(rows[-limit:]))


def append_simple_registration(payload: dict[str, Any]) -> None:
    path = runtime_paths()["simple_registrations"]
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=True) + "\n")


def simple_template_path(name: str) -> Path:
    return SIMPLE_DIR / "templates" / name


def render_simple_template(name: str, replacements: dict[str, str]) -> str:
    text = simple_template_path(name).read_text(encoding="utf-8")
    for key, value in replacements.items():
        text = text.replace(key, value)
    return text


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
            "simple_upload_token": load_or_create_simple_upload_token(),
            "now": datetime.now(UTC),
        }

    @app.get("/")
    def index():
        paths = runtime_paths()
        manifest = load_manifest(paths)
        client_packages = manifest.get("client_packages", [])
        registered_hosts = manifest.get("registered_hosts", [])
        recent_ingest = manifest.get("recent_ingest", [])
        simple_recent = read_simple_registrations()
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
            {
                "label": "Simple Registrations",
                "value": str(len(simple_recent)),
                "hint": "Low-friction browser or script registrations for ordinary devices.",
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
            simple_recent=simple_recent,
            paths={key: str(value) for key, value in paths.items()},
            current_host=platform.node(),
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

    @app.post("/api/simple-browser")
    def simple_browser():
        payload = request.get_json(silent=True) or {}
        if not isinstance(payload, dict):
            return jsonify({"ok": False, "error": "invalid payload"}), 400
        entry = {
            "kind": "browser",
            "timestamp": datetime.now(UTC).isoformat(),
            "instance": app.config["NETINV_HOST_INSTANCE"],
            "description": str(payload.get("description", "")).strip(),
            "browser": payload.get("browser") if isinstance(payload.get("browser"), dict) else {},
            "client": {
                "remote_addr": request.headers.get("X-Forwarded-For", request.remote_addr or ""),
                "user_agent": request.headers.get("User-Agent", ""),
                "forwarded_host": request.headers.get("X-Forwarded-Host", ""),
                "forwarded_proto": request.headers.get("X-Forwarded-Proto", ""),
            },
        }
        append_simple_registration(entry)
        return jsonify({"ok": True, "stored": entry["timestamp"]})

    @app.post("/api/simple-ingest")
    def simple_ingest():
        token = request.headers.get("X-NetInventory-Simple-Token", "").strip()
        if token != load_or_create_simple_upload_token():
            return jsonify({"ok": False, "error": "invalid token"}), 403
        payload = request.get_json(silent=True) or {}
        if not isinstance(payload, dict):
            return jsonify({"ok": False, "error": "invalid payload"}), 400
        entry = {
            "kind": str(payload.get("kind", "script")).strip() or "script",
            "timestamp": datetime.now(UTC).isoformat(),
            "instance": app.config["NETINV_HOST_INSTANCE"],
            "description": str(payload.get("description", "")).strip(),
            "payload": payload,
            "client": {
                "remote_addr": request.headers.get("X-Forwarded-For", request.remote_addr or ""),
                "user_agent": request.headers.get("User-Agent", ""),
            },
        }
        append_simple_registration(entry)
        return jsonify({"ok": True, "stored": entry["timestamp"]})

    @app.get("/downloads/register-device.sh")
    def download_simple_shell():
        base = app.config["NETINV_HOST_TRACK_BASE"]
        instance = app.config["NETINV_HOST_INSTANCE"]
        token = load_or_create_simple_upload_token()
        script = render_simple_template(
            "register-device.sh.tmpl",
            {
                "__TARGET_URL__": f"{base}/netinventory/api/simple-ingest?env={instance}",
                "__TOKEN__": token,
            },
        )
        return Response(
            script,
            mimetype="text/x-shellscript",
            headers={"Content-Disposition": 'attachment; filename="register-device.sh"'},
        )

    @app.get("/downloads/register-device.bat")
    def download_simple_batch():
        base = app.config["NETINV_HOST_TRACK_BASE"]
        instance = app.config["NETINV_HOST_INSTANCE"]
        token = load_or_create_simple_upload_token()
        script = render_simple_template(
            "register-device.bat.tmpl",
            {
                "__TARGET_URL__": f"{base}/netinventory/api/simple-ingest?env={instance}",
                "__TOKEN__": token,
            },
        )
        return Response(
            script,
            mimetype="text/plain",
            headers={"Content-Disposition": 'attachment; filename="register-device.bat"'},
        )

    @app.get("/health")
    def health():
        return {
            "status": "ok",
            "service": "netinventory-host",
            "instance": app.config["NETINV_HOST_INSTANCE"],
            "timestamp": datetime.now(UTC).isoformat(),
            "simple_registrations": len(read_simple_registrations(limit=10000)),
        }

    return app
