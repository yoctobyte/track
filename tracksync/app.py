from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path

import requests
from flask import Flask, abort, redirect, render_template, request, session, url_for

from sync_core import ConfigStore, sign_request, utcnow_iso, verify_signature


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
        if not verify_signature(secret, request.method, request.path, timestamp, body, signature):
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
        if request.endpoint in {"login", "static", "api_hello", "api_manifest"}:
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
        return render_template("index.html", config=current_config())

    @app.route("/peers", methods=["POST"])
    def add_peer():
        try:
            app.config["TRACKSYNC_STORE"].add_peer(
                request.form.get("name", ""),
                request.form.get("base_url", ""),
                request.form.get("secret", ""),
            )
        except ValueError as exc:
            return render_template("index.html", config=current_config(), error=str(exc)), 400
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
            status = f"ok: {hello.json().get('host_id', 'unknown')} / {len(manifest.json().get('records', []))} records"
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
        return {
            "host_id": cfg.host_id,
            "generated_at": utcnow_iso(),
            "records": [],
            "files": [],
            "adapters": [],
        }

    return app


def main() -> None:
    parser = argparse.ArgumentParser(description="TRACK multi-host sync coordinator")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=int(os.environ.get("TRACKSYNC_PORT", "5099")))
    args = parser.parse_args()
    create_app().run(host=args.host, port=args.port)


if __name__ == "__main__":
    main()

