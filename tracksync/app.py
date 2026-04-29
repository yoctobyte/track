from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path

import requests
from flask import Flask, abort, redirect, render_template, request, send_file, session, url_for

from sync_core import (
    ConfigStore,
    default_pull_policy,
    discover_subprojects,
    public_environments,
    pull_artifacts,
    resolve_artifact_file,
    safe_slug,
    scan_artifact_roots,
    sign_request,
    subproject_of,
    utcnow_iso,
    verify_signature,
)


BASE_DIR = Path(__file__).resolve().parent


def create_app() -> Flask:
    data_dir = Path(os.environ.get("TRACKSYNC_DATA_DIR", BASE_DIR / "data")).expanduser().resolve()
    store = ConfigStore(data_dir)
    config = store.load()

    app = Flask(__name__)
    app.config["SECRET_KEY"] = os.environ.get("TRACKSYNC_FLASK_SECRET", config.secret)
    app.config["SESSION_COOKIE_NAME"] = "tracksync_session"
    app.config["SESSION_COOKIE_HTTPONLY"] = True
    app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
    app.config["TRACKSYNC_STORE"] = store

    def current_config():
        return app.config["TRACKSYNC_STORE"].load()

    def admin_password() -> str:
        return os.environ.get("TRACKSYNC_ADMIN_PASSWORD", "tracksync-admin")

    def signature_path() -> str:
        raw_uri = request.environ.get("RAW_URI") or request.environ.get("REQUEST_URI") or request.path
        return str(raw_uri).split("?", 1)[0]

    def require_admin():
        if session.get("tracksync_admin"):
            return None
        return redirect(url_for("login", next=request.full_path.rstrip("?")))

    def require_signed_request():
        cfg = current_config()
        remote_host = request.headers.get("X-Track-Sync-Host", "").strip()
        timestamp = request.headers.get("X-Track-Sync-Timestamp", "").strip()
        signature = request.headers.get("X-Track-Sync-Signature", "").strip()
        body = request.get_data() or b""
        if remote_host == cfg.host_id:
            secret = cfg.secret
        else:
            peer = next((item for item in cfg.peers if item.get("id") == remote_host), None)
            secret = str(peer.get("secret", "")) if peer else ""
        if not verify_signature(secret, request.method, signature_path(), timestamp, body, signature):
            abort(401)

    def signed_get(peer: dict, path: str):
        cfg = current_config()
        body = b""
        timestamp = str(int(time.time()))
        url = f"{str(peer['base_url']).rstrip('/')}{path}"
        headers = {
            "X-Track-Sync-Host": cfg.host_id,
            "X-Track-Sync-Timestamp": timestamp,
            "X-Track-Sync-Signature": sign_request(str(peer["secret"]), "GET", path, timestamp, body),
        }
        return requests.get(url, headers=headers, timeout=10)

    @app.before_request
    def gate_admin_pages():
        if request.endpoint in {"login", "static", "api_hello", "api_manifest", "api_file"}:
            return None
        if request.path.startswith("/api/"):
            require_signed_request()
            return None
        return require_admin()

    @app.route("/login", methods=["GET", "POST"])
    def login():
        error = ""
        if request.method == "POST":
            if request.form.get("password", "") == admin_password():
                session["tracksync_admin"] = True
                return redirect(request.args.get("next") or url_for("index"))
            error = "Invalid password"
        return render_template("login.html", error=error)

    @app.route("/logout")
    def logout():
        session.clear()
        return redirect(url_for("login"))

    @app.route("/")
    def index():
        cfg = current_config()
        known = discover_subprojects(cfg)
        peer_policies = []
        for peer in cfg.peers:
            policy = peer.get("pull_policy") or default_pull_policy()
            subprojects = dict(policy.get("subprojects") or {})
            rows = []
            for name in sorted(set(known) | set(subprojects.keys())):
                if name in subprojects:
                    state = "on" if subprojects[name] else "off"
                else:
                    state = "default"
                rows.append({"name": name, "state": state})
            peer_policies.append({
                "peer_id": peer.get("id"),
                "default_on": bool(policy.get("default", True)),
                "rows": rows,
            })
        return render_template(
            "index.html",
            config=cfg,
            peer_policies={item["peer_id"]: item for item in peer_policies},
        )

    @app.route("/peers", methods=["POST"])
    def add_peer():
        try:
            app.config["TRACKSYNC_STORE"].add_peer(
                request.form.get("name", ""),
                request.form.get("base_url", ""),
                request.form.get("secret", ""),
                location_slug=request.form.get("location_slug", ""),
                username=request.form.get("username", ""),
                password=request.form.get("password", ""),
            )
        except ValueError as exc:
            return render_template("index.html", config=current_config(), error=str(exc)), 400
        return redirect(url_for("index"))

    @app.route("/environments", methods=["POST"])
    def add_environment():
        app.config["TRACKSYNC_STORE"].add_environment(
            request.form.get("slug", ""),
            request.form.get("name", ""),
            request.form.get("username", ""),
            request.form.get("password", ""),
        )
        return redirect(url_for("index"))

    @app.route("/peers/<peer_id>/policy", methods=["POST"])
    def update_peer_policy(peer_id: str):
        default_on = request.form.get("default", "on") == "on"
        subprojects: dict[str, bool] = {}
        for key, value in request.form.items():
            if not key.startswith("sub_"):
                continue
            name = key[len("sub_"):]
            if value == "on":
                subprojects[name] = True
            elif value == "off":
                subprojects[name] = False
        new_name = request.form.get("new_subproject", "").strip()
        new_state = request.form.get("new_state", "")
        if new_name and new_state in {"on", "off"}:
            subprojects[safe_slug(new_name)] = (new_state == "on")
        try:
            app.config["TRACKSYNC_STORE"].update_peer_policy(peer_id, default_on, subprojects)
        except KeyError:
            abort(404)
        return redirect(url_for("index"))

    @app.route("/sync/<peer_id>", methods=["POST"])
    def sync_peer(peer_id: str):
        cfg = current_config()
        peer = next((item for item in cfg.peers if item.get("id") == peer_id), None)
        if peer is None:
            abort(404)
        try:
            hello = signed_get(peer, "/api/v1/hello")
            hello.raise_for_status()
            manifest = signed_get(peer, "/api/v1/manifest")
            manifest.raise_for_status()
            manifest_data = manifest.json()
            counts = pull_artifacts(
                cfg,
                peer,
                manifest_data,
                lambda path: signed_get(peer, path),
            )
            status = (
                f"ok: {hello.json().get('host_id', 'unknown')} / "
                f"{len(manifest_data.get('records', []))} records / "
                f"{len(manifest_data.get('files', []))} files / "
                f"pulled {counts['pulled']} / "
                f"skipped {counts['skipped_policy']}p {counts['skipped_exists']}e / "
                f"failed {counts['failed']}"
            )
        except Exception as exc:
            status = f"failed: {exc}"
        app.config["TRACKSYNC_STORE"].update_peer_status(peer_id, status)
        return redirect(url_for("index"))

    @app.route("/api/v1/hello")
    def api_hello():
        require_signed_request()
        cfg = current_config()
        return {
            "app": "tracksync",
            "host_id": cfg.host_id,
            "now": utcnow_iso(),
            "protocol": "track-sync-v1",
        }

    @app.route("/api/v1/manifest")
    def api_manifest():
        require_signed_request()
        cfg = current_config()
        files = scan_artifact_roots(cfg)
        return {
            "host_id": cfg.host_id,
            "generated_at": utcnow_iso(),
            "environments": public_environments(cfg),
            "records": [],
            "files": files,
            "adapters": [
                {
                    "id": "artifact_roots",
                    "type": "file-manifest",
                    "roots": [
                        {
                            "id": item.get("id") or item.get("name"),
                            "tier": item.get("tier", "artifact"),
                            "record_type": item.get("record_type"),
                            "enabled": item.get("enabled", True),
                        }
                        for item in cfg.artifact_roots
                    ],
                }
            ],
        }

    @app.route("/api/v1/files/<root_id>/<path:relative_path>")
    def api_file(root_id: str, relative_path: str):
        require_signed_request()
        path = resolve_artifact_file(current_config(), root_id, relative_path)
        if path is None:
            abort(404)
        return send_file(path, as_attachment=True, download_name=path.name)

    return app


def main() -> None:
    parser = argparse.ArgumentParser(description="TRACK multi-host sync coordinator")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=int(os.environ.get("TRACKSYNC_PORT", "5099")))
    args = parser.parse_args()
    create_app().run(host=args.host, port=args.port)


if __name__ == "__main__":
    main()
