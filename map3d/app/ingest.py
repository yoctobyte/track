import json

from . import db
from .models import Asset, Frame, Observation, Session, utcnow
from .storage import store_original, store_preview
from .metadata import extract_metadata, generate_preview


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

    db.session.commit()
    return frame


def get_or_create_session(building_id: int, label: str = "",
                          source_type: str = "file_upload") -> Session:
    """Get an open session or create a new one."""
    session = Session(
        building_id=building_id,
        label=label or f"Upload {utcnow().strftime('%Y-%m-%d %H:%M')}",
        source_type=source_type,
    )
    db.session.add(session)
    db.session.flush()
    return session
