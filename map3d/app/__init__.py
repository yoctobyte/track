from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from pathlib import Path

db = SQLAlchemy()

DATA_DIR = Path(__file__).parent.parent / "data"


def create_app():
    app = Flask(__name__)
    app.config["SECRET_KEY"] = "dev-key-change-in-production"
    app.config["SQLALCHEMY_DATABASE_URI"] = f"sqlite:///{DATA_DIR / 'database.sqlite'}"
    app.config["DATA_DIR"] = DATA_DIR

    db.init_app(app)

    from . import models  # noqa: F401
    from .routes import locations, upload, gallery, capture, api
    app.register_blueprint(locations.bp)
    app.register_blueprint(upload.bp)
    app.register_blueprint(gallery.bp)
    app.register_blueprint(capture.bp)
    app.register_blueprint(api.bp)

    with app.app_context():
        db.create_all()

    return app
