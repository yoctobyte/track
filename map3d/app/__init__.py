import os
from datetime import timedelta

from flask import Flask, jsonify, redirect, request, session, url_for
from flask_sqlalchemy import SQLAlchemy
from pathlib import Path

db = SQLAlchemy()

DATA_DIR = Path(__file__).parent.parent / "data"


def create_app():
    app = Flask(__name__)
    app.config["SECRET_KEY"] = os.environ.get("MAP3D_SECRET_KEY", "dev-key-change-in-production")
    app.config["SQLALCHEMY_DATABASE_URI"] = f"sqlite:///{DATA_DIR / 'database.sqlite'}"
    app.config["DATA_DIR"] = DATA_DIR
    app.config["MAP3D_PASSWORD"] = os.environ.get("MAP3D_PASSWORD", "map3d__ok!aY3")
    app.config["SESSION_PERMANENT"] = True
    app.config["PERMANENT_SESSION_LIFETIME"] = timedelta(days=365)
    app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
    app.config["SESSION_COOKIE_HTTPONLY"] = True

    db.init_app(app)

    from . import models  # noqa: F401
    from .routes import auth, locations, upload, gallery, capture, api
    app.register_blueprint(auth.bp)
    app.register_blueprint(locations.bp)
    app.register_blueprint(upload.bp)
    app.register_blueprint(gallery.bp)
    app.register_blueprint(capture.bp)
    app.register_blueprint(api.bp)

    @app.before_request
    def require_password():
        allowed_endpoints = {"auth.login", "auth.logout", "static"}
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

    return app
