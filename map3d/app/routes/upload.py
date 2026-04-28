import json
import shutil
import uuid
from pathlib import Path

from flask import Blueprint, current_app, jsonify, render_template, request, redirect, url_for, flash
from .. import db
from ..models import Building, Location, Session
from ..ingest import ingest_image, ingest_video, ingest_video_file, get_or_create_session, upload_source_type

bp = Blueprint("upload", __name__)

ALLOWED_IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".tiff", ".tif", ".webp"}
ALLOWED_VIDEO_EXTENSIONS = {".mp4", ".mov", ".m4v", ".avi", ".mkv", ".webm", ".mpg", ".mpeg"}
VIDEO_CHUNK_SIZE = 5 * 1024 * 1024


def allowed_image_file(filename: str) -> bool:
    return "." in filename and ("." + filename.rsplit(".", 1)[1].lower()) in ALLOWED_IMAGE_EXTENSIONS


def allowed_video_file(filename: str) -> bool:
    return "." in filename and ("." + filename.rsplit(".", 1)[1].lower()) in ALLOWED_VIDEO_EXTENSIONS


def upload_root() -> Path:
    root = Path(current_app.config["DATA_DIR"]) / "incoming_uploads"
    root.mkdir(parents=True, exist_ok=True)
    return root


def upload_meta_path(upload_id: str) -> Path:
    return upload_root() / upload_id / "meta.json"


def load_upload_meta(upload_id: str) -> dict | None:
    path = upload_meta_path(upload_id)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def save_upload_meta(upload_id: str, meta: dict) -> None:
    upload_dir = upload_root() / upload_id
    upload_dir.mkdir(parents=True, exist_ok=True)
    upload_meta_path(upload_id).write_text(json.dumps(meta, indent=2), encoding="utf-8")


def resolve_target_session(building_id: int, session_id: int | None, source_type: str):
    if session_id:
        session = db.session.get(Session, int(session_id))
        if session is None:
            raise ValueError("session not found")
        if session.building_id != int(building_id):
            raise ValueError("session belongs to a different building")
        if session.source_type != source_type:
            session.source_type = "mixed_upload"
        return session
    return get_or_create_session(building_id, source_type=source_type)


@bp.route("/upload", methods=["GET", "POST"])
def upload():
    buildings = Building.query.order_by(Building.name).all()
    append_session = None
    append_session_id = request.args.get("session_id", type=int)
    if append_session_id:
        append_session = db.session.get(Session, append_session_id)

    if request.method == "POST":
        building_id = request.form.get("building_id", type=int)
        location_id = request.form.get("location_id", type=int) or None
        session_id = request.form.get("session_id", type=int) or None
        photo_files = [f for f in request.files.getlist("photos") if f.filename]
        video_files = [f for f in request.files.getlist("videos") if f.filename]

        if not building_id:
            flash("Please select a building.")
            return redirect(url_for("upload.upload"))

        if not photo_files and not video_files:
            flash("No files selected. Add photos or videos.")
            return redirect(url_for("upload.upload"))

        try:
            session = resolve_target_session(
                building_id,
                session_id,
                upload_source_type(len(photo_files), len(video_files)),
            )
        except ValueError as exc:
            flash(str(exc))
            return redirect(url_for("upload.upload"))
        image_count = 0
        video_count = 0
        for f in photo_files:
            if allowed_image_file(f.filename):
                data = f.read()
                if data:
                    ingest_image(data, f.filename, session, location_id)
                    image_count += 1
        for f in video_files:
            if allowed_video_file(f.filename):
                data = f.read()
                if data:
                    ingest_video(data, f.filename, session, location_id)
                    video_count += 1

        if session.assets.count() == 0:
            db.session.delete(session)
            db.session.commit()
            flash("No valid media files found.")
        else:
            db.session.commit()
            parts = []
            if image_count:
                parts.append(f"{image_count} image(s)")
            if video_count:
                parts.append(f"{video_count} video(s)")
            flash(f"Uploaded {' and '.join(parts)}.")
            return redirect(url_for("gallery.session_detail", session_id=session.id))

        return redirect(url_for("upload.upload"))

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
                           append_session=append_session,
                           buildings_json=json.dumps(buildings_json),
                           locations_by_building_json=json.dumps(locs_json),
                           video_chunk_size=VIDEO_CHUNK_SIZE)


@bp.route("/api/uploads/start", methods=["POST"])
def start_chunked_upload():
    data = request.get_json(silent=True) or {}
    filename = (data.get("filename") or "").strip()
    building_id = data.get("building_id")
    location_id = data.get("location_id") or None
    file_size = int(data.get("file_size") or 0)
    content_type = (data.get("content_type") or "").strip()
    session_id = data.get("session_id")

    if not building_id:
        return jsonify({"error": "building_id required"}), 400
    building = db.session.get(Building, int(building_id))
    if building is None:
        return jsonify({"error": "building not found"}), 404
    if not filename or not allowed_video_file(filename):
        return jsonify({"error": "valid video filename required"}), 400
    if location_id:
        location = db.session.get(Location, int(location_id))
        if location is None or location.building_id != building.id:
            return jsonify({"error": "invalid location"}), 400

    upload_id = uuid.uuid4().hex
    upload_dir = upload_root() / upload_id
    upload_dir.mkdir(parents=True, exist_ok=True)
    save_upload_meta(upload_id, {
        "upload_id": upload_id,
        "filename": filename,
        "building_id": int(building_id),
        "session_id": int(session_id) if session_id else None,
        "location_id": int(location_id) if location_id else None,
        "file_size": file_size,
        "content_type": content_type,
        "received_chunks": [],
        "status": "started",
    })
    return jsonify({
        "upload_id": upload_id,
        "chunk_size": VIDEO_CHUNK_SIZE,
    }), 201


@bp.route("/api/uploads/<upload_id>/chunk", methods=["POST"])
def upload_chunk(upload_id: str):
    meta = load_upload_meta(upload_id)
    if meta is None:
        return jsonify({"error": "upload not found"}), 404
    chunk_index = request.form.get("chunk_index", type=int)
    chunk_file = request.files.get("chunk")
    if chunk_index is None or chunk_index < 0 or chunk_file is None:
        return jsonify({"error": "chunk_index and chunk file required"}), 400
    upload_dir = upload_root() / upload_id
    chunk_path = upload_dir / f"chunk_{chunk_index:06d}.part"
    chunk_file.save(chunk_path)
    received = set(meta.get("received_chunks") or [])
    received.add(int(chunk_index))
    meta["received_chunks"] = sorted(received)
    meta["status"] = "uploading"
    save_upload_meta(upload_id, meta)
    return jsonify({
        "ok": True,
        "received_chunks": len(meta["received_chunks"]),
    })


@bp.route("/api/uploads/<upload_id>/finish", methods=["POST"])
def finish_chunked_upload(upload_id: str):
    meta = load_upload_meta(upload_id)
    if meta is None:
        return jsonify({"error": "upload not found"}), 404
    total_chunks = request.get_json(silent=True) or {}
    total_chunks = int(total_chunks.get("total_chunks") or 0)
    if total_chunks <= 0:
        return jsonify({"error": "total_chunks required"}), 400
    received = set(meta.get("received_chunks") or [])
    missing = [index for index in range(total_chunks) if index not in received]
    if missing:
        return jsonify({"error": "missing chunks", "missing": missing[:10]}), 400

    upload_dir = upload_root() / upload_id
    assembled_path = upload_dir / meta["filename"]
    with assembled_path.open("wb") as assembled:
        for index in range(total_chunks):
            chunk_path = upload_dir / f"chunk_{index:06d}.part"
            with chunk_path.open("rb") as src:
                shutil.copyfileobj(src, assembled)

    try:
        session = resolve_target_session(
            int(meta["building_id"]),
            meta.get("session_id"),
            "video_import",
        )
    except ValueError as exc:
        shutil.rmtree(upload_dir, ignore_errors=True)
        return jsonify({"error": str(exc)}), 400
    asset = ingest_video_file(
        assembled_path,
        meta["filename"],
        session,
        location_id=meta.get("location_id"),
    )
    shutil.rmtree(upload_dir, ignore_errors=True)
    return jsonify({
        "ok": True,
        "session_id": session.id,
        "asset_id": asset.id,
        "redirect_url": url_for("gallery.session_detail", session_id=session.id),
    }), 201
