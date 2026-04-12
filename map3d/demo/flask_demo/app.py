"""
Flask demo — patterns relevant to map3d:
  - SQLite via SQLAlchemy
  - file upload + storage
  - template rendering (gallery)
  - JSON API endpoint
  - background processing (threading)
"""

import hashlib
import threading
import time
from pathlib import Path

from flask import Flask, render_template, request, jsonify, redirect, url_for
from flask_sqlalchemy import SQLAlchemy

# --- App setup ---

app = Flask(__name__)
app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///demo.db"
app.config["UPLOAD_FOLDER"] = Path(__file__).parent / "uploads"
app.config["UPLOAD_FOLDER"].mkdir(exist_ok=True)

db = SQLAlchemy(app)


# --- Models ---

class Location(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    parent_id = db.Column(db.Integer, db.ForeignKey("location.id"))
    children = db.relationship("Location", backref=db.backref("parent", remote_side=[id]))
    photos = db.relationship("Photo", backref="location")


class Photo(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    filename = db.Column(db.String(255), nullable=False)
    storage_path = db.Column(db.String(500), nullable=False)
    sha256 = db.Column(db.String(64))
    location_id = db.Column(db.Integer, db.ForeignKey("location.id"))
    status = db.Column(db.String(20), default="pending")  # pending, processing, done


# --- Background task ---

def process_photo(photo_id):
    """Simulate slow processing (metadata extraction, thumbnail, etc.)."""
    time.sleep(2)
    with app.app_context():
        photo = db.session.get(Photo, photo_id)
        if photo:
            photo.status = "done"
            db.session.commit()


# --- Routes: HTML pages ---

@app.route("/")
def index():
    locations = Location.query.filter_by(parent_id=None).all()
    return render_template("index.html", locations=locations)


@app.route("/upload", methods=["GET", "POST"])
def upload():
    if request.method == "POST":
        location_id = request.form.get("location_id", type=int)
        file = request.files.get("photo")
        if not file or not file.filename:
            return redirect(url_for("upload"))

        # Store original
        data = file.read()
        sha = hashlib.sha256(data).hexdigest()
        dest = app.config["UPLOAD_FOLDER"] / f"{sha}_{file.filename}"
        dest.write_bytes(data)

        # Create record
        photo = Photo(
            filename=file.filename,
            storage_path=str(dest),
            sha256=sha,
            location_id=location_id,
            status="processing",
        )
        db.session.add(photo)
        db.session.commit()

        # Kick off background work
        threading.Thread(target=process_photo, args=(photo.id,)).start()

        return redirect(url_for("gallery"))

    locations = Location.query.all()
    return render_template("upload.html", locations=locations)


@app.route("/gallery")
def gallery():
    photos = Photo.query.order_by(Photo.id.desc()).all()
    return render_template("gallery.html", photos=photos)


# --- Routes: JSON API ---

@app.route("/api/locations", methods=["GET"])
def api_list_locations():
    locations = Location.query.all()
    return jsonify([
        {"id": l.id, "name": l.name, "parent_id": l.parent_id}
        for l in locations
    ])


@app.route("/api/locations", methods=["POST"])
def api_create_location():
    data = request.get_json()
    loc = Location(name=data["name"], parent_id=data.get("parent_id"))
    db.session.add(loc)
    db.session.commit()
    return jsonify({"id": loc.id, "name": loc.name}), 201


@app.route("/api/photos/<int:photo_id>")
def api_photo_detail(photo_id):
    photo = db.session.get(Photo, photo_id)
    if not photo:
        return jsonify({"error": "not found"}), 404
    return jsonify({
        "id": photo.id,
        "filename": photo.filename,
        "sha256": photo.sha256,
        "location": photo.location.name if photo.location else None,
        "status": photo.status,
    })


# --- Init ---

with app.app_context():
    db.create_all()
    # Seed some locations if empty
    if not Location.query.first():
        museum = Location(name="Museum")
        db.session.add(museum)
        db.session.flush()
        for room in ["Ground Floor", "First Floor", "Basement"]:
            db.session.add(Location(name=room, parent_id=museum.id))
        db.session.commit()


if __name__ == "__main__":
    app.run(debug=True, port=5000)
