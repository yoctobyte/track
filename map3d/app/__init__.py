import os
from datetime import timedelta
from urllib.parse import urlunsplit

from flask import Flask, jsonify, redirect, request, session, url_for
from flask_sqlalchemy import SQLAlchemy
from pathlib import Path
from sqlalchemy import text
from werkzeug.middleware.proxy_fix import ProxyFix

db = SQLAlchemy()

DEFAULT_DATA_DIR = Path(__file__).parent.parent / "data"
DATA_DIR = Path(os.environ.get("MAP3D_DATA_DIR", DEFAULT_DATA_DIR)).expanduser().resolve()


def ensure_data_dirs(data_dir: Path) -> None:
    for path in (
        data_dir,
        data_dir / "originals",
        data_dir / "previews",
        data_dir / "extracted_frames",
        data_dir / "incoming_uploads",
        data_dir / "derived" / "features",
        data_dir / "derived" / "matches",
        data_dir / "derived" / "reconstructions",
    ):
        path.mkdir(parents=True, exist_ok=True)


def ensure_schema(app):
    with app.app_context():
        session_columns = {
            row[1] for row in db.session.execute(text("PRAGMA table_info(session)")).fetchall()
        }
        if "capture_run_key" not in session_columns:
            db.session.execute(text(
                "ALTER TABLE session ADD COLUMN capture_run_key VARCHAR(64) DEFAULT ''"
            ))
        if "capture_mode" not in session_columns:
            db.session.execute(text(
                "ALTER TABLE session ADD COLUMN capture_mode VARCHAR(20) DEFAULT ''"
            ))
        asset_columns = {
            row[1] for row in db.session.execute(text("PRAGMA table_info(asset)")).fetchall()
        }
        if "metadata_json" not in asset_columns:
            db.session.execute(text(
                "ALTER TABLE asset ADD COLUMN metadata_json TEXT DEFAULT '{}'"
            ))
        db.session.commit()


def create_app():
    ensure_data_dirs(DATA_DIR)

    app = Flask(__name__)
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=0, x_proto=1, x_host=1, x_prefix=1)
    app.config["SECRET_KEY"] = os.environ.get("MAP3D_SECRET_KEY", "dev-key-change-in-production")
    app.config["SQLALCHEMY_DATABASE_URI"] = f"sqlite:///{DATA_DIR / 'database.sqlite'}"
    app.config["DATA_DIR"] = DATA_DIR
    app.config["MAP3D_PASSWORD"] = os.environ.get("MAP3D_PASSWORD", "map3d__ok!aY3")
    app.config["SESSION_PERMANENT"] = True
    app.config["SESSION_COOKIE_NAME"] = "map3d_session"
    app.config["PERMANENT_SESSION_LIFETIME"] = timedelta(days=365)
    app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
    app.config["SESSION_COOKIE_HTTPONLY"] = True
    app.config["TRACK_BASE_URL"] = os.environ.get("TRACK_BASE_URL", "/").rstrip("/") or "/"

    db.init_app(app)

    from . import models  # noqa: F401
    from .routes import auth, locations, upload, gallery, capture, api, viewer
    app.register_blueprint(auth.bp)
    app.register_blueprint(locations.bp)
    app.register_blueprint(upload.bp)
    app.register_blueprint(gallery.bp)
    app.register_blueprint(capture.bp)
    app.register_blueprint(api.bp)
    app.register_blueprint(viewer.bp)

    @app.context_processor
    def inject_track_globals():
        track_base_url = app.config["TRACK_BASE_URL"]
        forwarded_host = request.headers.get("X-Forwarded-Host", "").strip()
        forwarded_proto = request.headers.get("X-Forwarded-Proto", "").strip() or request.scheme
        if forwarded_host:
            track_base_url = urlunsplit((forwarded_proto, forwarded_host, "", "", "")) or track_base_url
        return {
            "track_base_url": track_base_url,
        }

    @app.before_request
    def require_password():
        allowed_endpoints = {"auth.login", "auth.logout", "static"}
        trusted_proxy = request.remote_addr in {"127.0.0.1", "::1"}
        trusted_trackhub = False
        if (
            trusted_proxy
            and request.headers.get("X-Trackhub-Authenticated") == "true"
            and request.headers.get("X-Trackhub-Environment")
        ):
            trusted_trackhub = True
            session["authenticated"] = True
            session["trackhub_environment"] = request.headers.get("X-Trackhub-Environment")
            session.permanent = True
        if trusted_trackhub and request.endpoint == "auth.login":
            next_url = request.args.get("next") or "/"
            if not next_url.startswith("/") or next_url.startswith("//"):
                next_url = "/"
            return redirect(next_url)
        if request.endpoint in allowed_endpoints:
            return None
        if session.get("authenticated"):
            session.permanent = True
            return None
        if request.path.startswith("/api/"):
            return jsonify({"error": "authentication required"}), 401
        return redirect(url_for("auth.login", next=request.full_path if request.query_string else request.path))

    with app.app_context():
        db.create_all()
        ensure_schema(app)

    return app
