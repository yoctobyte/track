import json
from datetime import timedelta

from . import db
from .models import Asset, Frame, Observation, Session, utcnow
from .storage import store_original, store_preview
from .metadata import extract_metadata, generate_preview


MANUAL_CAPTURE_SESSION_TIMEOUT = timedelta(minutes=30)


def ingest_image(file_data: bytes, original_filename: str, session: Session,
                 location_id: int | None = None,
                 sensor_data: dict | None = None) -> Frame:
    """Full ingest pipeline for a single image.

    1. Hash and store original
    2. Create asset record
    3. Extract metadata
    4. Generate preview
    5. Create frame record
    6. Create observation (location assignment) if location given
    """
    # Store original file
    storage_info = store_original(file_data, original_filename, session.id)

    # Create asset
    asset = Asset(
        session_id=session.id,
        type="image",
        original_filename=original_filename,
        storage_path=storage_info["storage_path"],
        hash_sha256=storage_info["hash_sha256"],
        file_size=storage_info["file_size"],
        mime_type=storage_info["mime_type"],
    )
    db.session.add(asset)
    db.session.flush()  # get asset.id

    # Extract metadata
    meta = extract_metadata(file_data)

    # Create frame
    frame = Frame(
        asset_id=asset.id,
        timestamp_original=meta["timestamp_original"],
        timestamp_imported=utcnow(),
        width=meta["width"],
        height=meta["height"],
        metadata_json=json.dumps(meta["metadata_json"]),
        sensor_json=json.dumps(sensor_data) if sensor_data else "{}",
        processing_status="processing",
    )
    db.session.add(frame)
    db.session.flush()  # get frame.id

    # Generate and store preview
    preview_data = generate_preview(file_data)
    if preview_data:
        frame.preview_path = store_preview(preview_data, frame.id)

    frame.processing_status = "done"

    # Create observation if location assigned
    if location_id:
        obs = Observation(
            frame_id=frame.id,
            assigned_location_id=location_id,
            assignment_method="manual",
        )
        db.session.add(obs)

    session.end_time = utcnow()
    db.session.commit()
    return frame


def get_or_create_session(building_id: int, label: str = "",
                          source_type: str = "file_upload",
                          capture_run_key: str = "",
                          capture_mode: str = "",
                          device_name: str = "") -> Session:
    """Get an open session or create a new one."""
    if source_type == "manual_capture":
        now = utcnow()
        session = None

        if capture_run_key:
            session = (Session.query
                       .filter_by(
                           building_id=building_id,
                           source_type=source_type,
                           capture_run_key=capture_run_key,
                       )
                       .order_by(Session.id.desc())
                       .first())
        else:
            recent_cutoff = now - MANUAL_CAPTURE_SESSION_TIMEOUT
            session = (Session.query
                       .filter(
                           Session.building_id == building_id,
                           Session.source_type == source_type,
                           Session.end_time.isnot(None),
                           Session.end_time >= recent_cutoff,
                       )
                       .order_by(Session.end_time.desc(), Session.id.desc())
                       .first())

        if session is not None:
            if capture_mode:
                if not session.capture_mode:
                    session.capture_mode = capture_mode
                elif session.capture_mode != capture_mode:
                    session.capture_mode = "mixed"
            if device_name and not session.device_name:
                session.device_name = device_name
            session.end_time = now
            db.session.flush()
            return session

    session = Session(
        building_id=building_id,
        label=label or (
            f"Capture run {utcnow().strftime('%Y-%m-%d %H:%M')}"
            if source_type == "manual_capture"
            else f"Upload {utcnow().strftime('%Y-%m-%d %H:%M')}"
        ),
        source_type=source_type,
        capture_run_key=capture_run_key,
        capture_mode=capture_mode,
        device_name=device_name,
        end_time=utcnow() if source_type == "manual_capture" else None,
    )
    db.session.add(session)
    db.session.flush()
    return session
