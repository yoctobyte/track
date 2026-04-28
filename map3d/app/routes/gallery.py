import json

from flask import Blueprint, render_template, request, redirect, url_for, send_from_directory, session as flask_session
from .. import db
from ..model_tools import session_model_runs
from ..models import Asset, Building, Location, Frame, Observation, Session
from ..storage import get_absolute_path
from ..video_pipeline import ffmpeg_available, parse_asset_metadata

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


@bp.route("/session/<int:session_id>")
def session_detail(session_id):
    capture_session = db.session.get(Session, session_id)
    if capture_session is None:
        return redirect(url_for("gallery.gallery"))

    assets = capture_session.assets.order_by(Asset.created_at.asc(), Asset.id.asc()).all()
    image_assets = [asset for asset in assets if asset.type == "image"]
    video_assets = [asset for asset in assets if asset.type == "video"]
    image_frames = (
        Frame.query.join(Asset, Frame.asset_id == Asset.id)
        .filter(Asset.session_id == session_id, Asset.type == "image")
        .order_by(Frame.id.asc())
        .all()
    )

    environment = flask_session.get("trackhub_environment", "").strip()
    env_args = f" --environment {environment}" if environment else ""
    prepare_command = f"./map3d-prepare-session.sh{env_args} --session {session_id:04d}"
    reconstruct_command = f"./map3d-reconstruct.sh{env_args} --session {session_id:04d}"
    model_hyworld_command = f"./map3d-model.sh all{env_args} --backend hyworld --session {session_id:04d}"
    model_lyra_command = f"./map3d-model.sh all{env_args} --backend lyra --session {session_id:04d}"
    model_install_hyworld_command = "./map3d-model.sh install --backend hyworld"
    model_install_lyra_command = "./map3d-model.sh install --backend lyra"
    model_runs = session_model_runs(get_absolute_path(""), session_id)

    data_root = get_absolute_path("")
    for run in model_runs:
        run.viewer_url = None
        run.points_url = None
        run.gaussians_url = None
        run.camera_url = None
        run.timing = None
        if run.points_path:
            run.viewer_url = url_for("viewer.model_viewer_detail", session_id=session_id, backend=run.backend, geometry="points")
            run.points_url = url_for("gallery.serve_data", filepath=str(run.points_path.relative_to(data_root)))
        if run.gaussians_path:
            if run.viewer_url is None:
                run.viewer_url = url_for("viewer.model_viewer_detail", session_id=session_id, backend=run.backend, geometry="gaussians")
            run.gaussians_url = url_for("gallery.serve_data", filepath=str(run.gaussians_path.relative_to(data_root)))
        if run.camera_path:
            run.camera_url = url_for("gallery.serve_data", filepath=str(run.camera_path.relative_to(data_root)))
            try:
                run.timing = json.loads(run.timing_path.read_text()) if run.timing_path and run.timing_path.exists() else None
            except Exception:
                run.timing = None

    return render_template(
        "session_detail.html",
        capture_session=capture_session,
        assets=assets,
        image_assets=image_assets,
        video_assets=video_assets,
        image_frames=image_frames,
        parse_asset_metadata=parse_asset_metadata,
        ffmpeg_ready=ffmpeg_available(),
        prepare_command=prepare_command,
        reconstruct_command=reconstruct_command,
        model_hyworld_command=model_hyworld_command,
        model_lyra_command=model_lyra_command,
        model_install_hyworld_command=model_install_hyworld_command,
        model_install_lyra_command=model_install_lyra_command,
        model_runs=model_runs,
    )


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

    frame_meta = json.loads(frame.metadata_json) if frame.metadata_json else {}
    original_path = frame_meta.get("original_storage_path") or frame.asset.storage_path

    return render_template("frame_detail.html",
                           frame=frame,
                           observation=observation,
                           metadata=metadata,
                           sensor=sensor,
                           locations=locations,
                           original_path=original_path)


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
