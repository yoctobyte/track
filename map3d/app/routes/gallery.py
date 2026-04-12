import json

from flask import Blueprint, render_template, request, redirect, url_for, send_from_directory
from .. import db
from ..models import Asset, Building, Location, Frame, Observation, Session
from ..storage import get_absolute_path

bp = Blueprint("gallery", __name__)


@bp.route("/gallery")
def gallery():
    building_id = request.args.get("building_id", type=int)
    location_id = request.args.get("location_id", type=int)
    session_id = request.args.get("session_id", type=int)

    query = Frame.query.join(Asset, Frame.asset_id == Asset.id)

    if session_id:
        query = query.filter(Asset.session_id == session_id)
    if building_id:
        query = query.join(Session, Asset.session_id == Session.id).filter(
            Session.building_id == building_id
        )
    if location_id:
        query = query.filter(Frame.observations.any(
            Observation.assigned_location_id == location_id
        ))

    frames = query.order_by(Frame.timestamp_imported.desc()).limit(200).all()

    buildings = Building.query.order_by(Building.name).all()
    sessions = Session.query.order_by(Session.start_time.desc()).limit(50).all()

    return render_template("gallery.html",
                           frames=frames,
                           buildings=buildings,
                           sessions=sessions,
                           current_building_id=building_id,
                           current_location_id=location_id,
                           current_session_id=session_id)


@bp.route("/frame/<int:frame_id>")
def frame_detail(frame_id):
    frame = db.session.get(Frame, frame_id)
    observation = frame.observations.first()
    metadata = json.loads(frame.metadata_json) if frame.metadata_json else {}
    sensor = json.loads(frame.sensor_json) if frame.sensor_json else {}

    # Get all locations for the correction dropdown
    locations = []
    if frame.asset.session.building_id:
        locations = Location.query.filter_by(
            building_id=frame.asset.session.building_id
        ).order_by(Location.sort_order, Location.name).all()

    return render_template("frame_detail.html",
                           frame=frame,
                           observation=observation,
                           metadata=metadata,
                           sensor=sensor,
                           locations=locations)


@bp.route("/frame/<int:frame_id>/assign", methods=["POST"])
def assign_location(frame_id):
    frame = db.session.get(Frame, frame_id)
    location_id = request.form.get("location_id", type=int)

    # Check for existing observation
    obs = frame.observations.first()
    if obs:
        obs.assigned_location_id = location_id
        obs.assignment_method = "corrected"
    else:
        obs = Observation(
            frame_id=frame_id,
            assigned_location_id=location_id,
            assignment_method="manual",
        )
        db.session.add(obs)

    db.session.commit()
    return redirect(url_for("gallery.frame_detail", frame_id=frame_id))


@bp.route("/data/<path:filepath>")
def serve_data(filepath):
    """Serve files from the data directory (previews, originals)."""
    data_dir = get_absolute_path("")
    return send_from_directory(data_dir, filepath)
