import json

from flask import Blueprint, render_template
from ..models import Building, Location

bp = Blueprint("capture", __name__)


@bp.route("/capture")
def capture():
    buildings = Building.query.order_by(Building.name).all()

    locations_by_building = {}
    for b in buildings:
        locations_by_building[b.id] = Location.query.filter_by(
            building_id=b.id
        ).order_by(Location.sort_order, Location.name).all()

    locs_json = {
        str(b.id): [{"id": l.id, "name": l.name, "type": l.type}
                     for l in locations_by_building[b.id]]
        for b in buildings
    }

    return render_template("capture.html",
                           buildings=buildings,
                           locations_by_building_json=json.dumps(locs_json))
