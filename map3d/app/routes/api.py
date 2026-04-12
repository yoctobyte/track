import base64
import json
import math

from flask import Blueprint, jsonify, request
from .. import db
from ..models import Building, Location, Frame
from ..ingest import ingest_image, get_or_create_session


def haversine_meters(lat1, lon1, lat2, lon2):
    """Distance in meters between two GPS points."""
    R = 6371000
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (math.sin(dlat / 2) ** 2 +
         math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) *
         math.sin(dlon / 2) ** 2)
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))

bp = Blueprint("api", __name__, url_prefix="/api")


@bp.route("/buildings")
def list_buildings():
    buildings = Building.query.order_by(Building.name).all()
    return jsonify([
        {"id": b.id, "name": b.name, "description": b.description,
         "latitude": b.latitude, "longitude": b.longitude,
         "geo_radius": b.geo_radius}
        for b in buildings
    ])


@bp.route("/buildings/nearest")
def nearest_building():
    """Find the nearest building to given coordinates.

    Query params: lat, lon
    Returns the closest building within its geo_radius, or null.
    """
    lat = request.args.get("lat", type=float)
    lon = request.args.get("lon", type=float)
    if lat is None or lon is None:
        return jsonify({"error": "lat and lon required"}), 400

    buildings = Building.query.filter(
        Building.latitude.isnot(None),
        Building.longitude.isnot(None),
    ).all()

    best = None
    best_dist = float("inf")
    for b in buildings:
        dist = haversine_meters(lat, lon, b.latitude, b.longitude)
        if dist < b.geo_radius and dist < best_dist:
            best = b
            best_dist = dist

    if best:
        return jsonify({
            "building": {"id": best.id, "name": best.name},
            "distance_m": round(best_dist, 1),
        })
    return jsonify({"building": None, "distance_m": None})


@bp.route("/buildings/<int:building_id>/locations")
def list_locations(building_id):
    locations = Location.query.filter_by(building_id=building_id).order_by(
        Location.sort_order, Location.name
    ).all()
    return jsonify([
        {
            "id": l.id,
            "name": l.name,
            "type": l.type,
            "environment": l.effective_environment,
            "parent_id": l.parent_id,
            "sort_order": l.sort_order,
        }
        for l in locations
    ])


@bp.route("/locations/<int:location_id>/children")
def location_children(location_id):
    """Return child locations — used by dynamic dropdowns."""
    children = Location.query.filter_by(parent_id=location_id).order_by(
        Location.sort_order, Location.name
    ).all()
    return jsonify([
        {"id": l.id, "name": l.name, "type": l.type}
        for l in children
    ])


@bp.route("/capture", methods=["POST"])
def capture():
    """Accept a photo + sensor data from the browser capture UI.

    Expects JSON with:
      - image: base64-encoded JPEG from canvas
      - building_id: int
      - location_id: int (optional)
      - sensor: dict with any/all of:
          - accelerometer: {x, y, z}
          - gyroscope: {x, y, z}
          - magnetometer: {x, y, z}  (from AbsoluteOrientationSensor or compass)
          - orientation: {alpha, beta, gamma}  (DeviceOrientation)
          - geolocation: {latitude, longitude, altitude, accuracy, heading, speed}
          - barometer: {pressure}  (if available)
          - timestamp: capture moment (ms since epoch)
    """
    data = request.get_json()
    if not data or "image" not in data:
        return jsonify({"error": "missing image data"}), 400

    building_id = data.get("building_id")
    if not building_id:
        return jsonify({"error": "missing building_id"}), 400

    # Decode base64 image
    image_b64 = data["image"]
    if "," in image_b64:
        image_b64 = image_b64.split(",", 1)[1]
    image_bytes = base64.b64decode(image_b64)

    location_id = data.get("location_id") or None
    sensor_data = data.get("sensor", {})

    session = get_or_create_session(building_id, source_type="manual_capture")
    frame = ingest_image(
        image_bytes, "capture.jpg", session,
        location_id=location_id,
        sensor_data=sensor_data,
    )

    return jsonify({
        "ok": True,
        "frame_id": frame.id,
        "sensor_keys": list(sensor_data.keys()),
    }), 201
