from flask import Blueprint, render_template, request, redirect, url_for
from .. import db
from ..models import Building, Location

bp = Blueprint("locations", __name__)


def delete_location_subtree(loc: Location):
    for child in list(loc.children):
        delete_location_subtree(child)
    db.session.delete(loc)


@bp.route("/")
def index():
    buildings = Building.query.order_by(Building.name).all()
    return render_template("index.html", buildings=buildings)


@bp.route("/buildings/new", methods=["POST"])
def create_building():
    name = request.form.get("name", "").strip()
    if name:
        lat = request.form.get("latitude", type=float)
        lon = request.form.get("longitude", type=float)
        radius = request.form.get("geo_radius", 100.0, type=float)
        b = Building(
            name=name,
            description=request.form.get("description", ""),
            latitude=lat,
            longitude=lon,
            geo_radius=radius,
        )
        db.session.add(b)
        db.session.commit()
    return redirect(url_for("locations.index"))


@bp.route("/buildings/<int:building_id>")
def building_detail(building_id):
    building = db.session.get(Building, building_id)
    # Get root locations (no parent)
    roots = Location.query.filter_by(
        building_id=building_id, parent_id=None
    ).order_by(Location.sort_order, Location.name).all()
    return render_template("building.html", building=building, roots=roots)


@bp.route("/buildings/<int:building_id>/locations/new", methods=["POST"])
def create_location(building_id):
    name = request.form.get("name", "").strip()
    if name:
        parent_id = request.form.get("parent_id", type=int) or None
        loc = Location(
            building_id=building_id,
            parent_id=parent_id,
            name=name,
            type=request.form.get("type", "room"),
            environment=request.form.get("environment", "auto"),
            notes=request.form.get("notes", ""),
        )
        db.session.add(loc)
        db.session.commit()
    return redirect(url_for("locations.building_detail", building_id=building_id))


@bp.route("/locations/<int:location_id>/edit", methods=["POST"])
def edit_location(location_id):
    loc = db.session.get(Location, location_id)
    loc.name = request.form.get("name", loc.name).strip()
    loc.type = request.form.get("type", loc.type)
    loc.environment = request.form.get("environment", loc.environment)
    loc.notes = request.form.get("notes", loc.notes)
    loc.sort_order = request.form.get("sort_order", loc.sort_order, type=int)
    db.session.commit()
    return redirect(url_for("locations.building_detail", building_id=loc.building_id))


@bp.route("/locations/<int:location_id>/delete", methods=["POST"])
def delete_location(location_id):
    loc = db.session.get(Location, location_id)
    if not loc:
        return redirect(url_for("locations.index"))
    building_id = loc.building_id
    if loc.can_delete:
        delete_location_subtree(loc)
        db.session.commit()
    return redirect(url_for("locations.building_detail", building_id=building_id))
