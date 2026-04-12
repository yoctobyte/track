import json

from flask import Blueprint, render_template, request, redirect, url_for, flash
from .. import db
from ..models import Building, Location
from ..ingest import ingest_image, get_or_create_session

bp = Blueprint("upload", __name__)

ALLOWED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".tiff", ".tif", ".webp"}


def allowed_file(filename: str) -> bool:
    return "." in filename and ("." + filename.rsplit(".", 1)[1].lower()) in ALLOWED_EXTENSIONS


@bp.route("/upload", methods=["GET", "POST"])
def upload():
    buildings = Building.query.order_by(Building.name).all()

    if request.method == "POST":
        building_id = request.form.get("building_id", type=int)
        location_id = request.form.get("location_id", type=int) or None
        files = request.files.getlist("photos")

        if not building_id:
            flash("Please select a building.")
            return redirect(url_for("upload.upload"))

        if not files or all(f.filename == "" for f in files):
            flash("No files selected.")
            return redirect(url_for("upload.upload"))

        session = get_or_create_session(building_id)
        count = 0
        for f in files:
            if f.filename and allowed_file(f.filename):
                data = f.read()
                if data:
                    ingest_image(data, f.filename, session, location_id)
                    count += 1

        if session.assets.count() == 0:
            db.session.delete(session)
            db.session.commit()
            flash("No valid image files found.")
        else:
            db.session.commit()
            flash(f"Uploaded {count} image(s).")

        return redirect(url_for("gallery.gallery"))

    # Build location options grouped by building
    locations_by_building = {}
    for b in buildings:
        locations_by_building[b.id] = Location.query.filter_by(
            building_id=b.id
        ).order_by(Location.sort_order, Location.name).all()

    buildings_json = [{"id": b.id, "name": b.name} for b in buildings]
    locs_json = {
        str(b.id): [{"id": l.id, "name": l.name, "type": l.type}
                     for l in locations_by_building[b.id]]
        for b in buildings
    }

    return render_template("upload.html",
                           buildings=buildings,
                           buildings_json=json.dumps(buildings_json),
                           locations_by_building_json=json.dumps(locs_json))
