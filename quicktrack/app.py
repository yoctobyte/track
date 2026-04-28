from __future__ import annotations

import argparse
import json
import os
import re
import secrets
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from flask import Flask, Response, abort, make_response, redirect, render_template, request, send_file, url_for
from werkzeug.datastructures import FileStorage
from werkzeug.utils import secure_filename


BASE_DIR = Path(__file__).resolve().parent
ALLOWED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".heic", ".heif"}


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def timestamp_slug(now: datetime | None = None) -> str:
    return (now or utcnow()).strftime("%Y%m%dT%H%M%S%fZ")


def clean_sender_id(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_.@-]+", "-", value.strip()).strip("-")
    return cleaned[:80]


def clean_text(value: str, limit: int) -> str:
    return value.strip()[:limit]


def parse_float(value: str) -> float | None:
    text = value.strip()
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def load_secret_key(data_dir: Path) -> str:
    configured = os.environ.get("QUICKTRACK_SECRET_KEY", "").strip()
    if configured:
        return configured
    data_dir.mkdir(parents=True, exist_ok=True)
    secret_path = data_dir / ".quicktrack-secret-key"
    if secret_path.exists():
        return secret_path.read_text(encoding="utf-8").strip()
    secret = secrets.token_urlsafe(48)
    secret_path.write_text(secret + "\n", encoding="utf-8")
    secret_path.chmod(0o600)
    return secret


def data_paths(data_dir: Path) -> dict[str, Path]:
    paths = {
        "records": data_dir / "records",
        "photos": data_dir / "photos",
    }
    for path in paths.values():
        path.mkdir(parents=True, exist_ok=True)
    return paths


def record_id_for(sender_id: str, now: datetime | None = None) -> str:
    sender_part = clean_sender_id(sender_id).lower() or "anonymous"
    return f"{timestamp_slug(now)}-{sender_part}-{secrets.token_hex(4)}"


def save_photo(upload: FileStorage, photos_dir: Path, record_id: str) -> dict[str, Any]:
    original_name = secure_filename(upload.filename or "photo")
    suffix = Path(original_name).suffix.lower()
    if suffix not in ALLOWED_EXTENSIONS:
        raise ValueError("Upload a photo file: jpg, png, webp, gif, heic, or heif.")
    stored_name = f"{record_id}{suffix}"
    photo_path = photos_dir / stored_name
    upload.save(photo_path)
    if photo_path.stat().st_size == 0:
        photo_path.unlink(missing_ok=True)
        raise ValueError("Uploaded photo was empty.")
    return {
        "original_name": original_name,
        "stored_name": stored_name,
        "relative_path": f"photos/{stored_name}",
        "size_bytes": photo_path.stat().st_size,
        "content_type": upload.mimetype or "",
    }


def write_record(records_dir: Path, record: dict[str, Any]) -> None:
    record_path = records_dir / f"{record['id']}.json"
    with record_path.open("w", encoding="utf-8") as handle:
        json.dump(record, handle, indent=2, sort_keys=True)
        handle.write("\n")


def read_records(records_dir: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for path in sorted(records_dir.glob("*.json"), reverse=True):
        try:
            with path.open(encoding="utf-8") as handle:
                data = json.load(handle)
            if isinstance(data, dict):
                records.append(data)
        except (OSError, json.JSONDecodeError):
            continue
    return records


def create_app() -> Flask:
    data_dir = Path(os.environ.get("QUICKTRACK_DATA_DIR", BASE_DIR / "data")).expanduser().resolve()
    paths = data_paths(data_dir)

    app = Flask(__name__)
    app.config["SECRET_KEY"] = load_secret_key(data_dir)
    app.config["SESSION_COOKIE_NAME"] = "quicktrack_session"
    app.config["QUICKTRACK_DATA_DIR"] = data_dir
    app.config["MAX_CONTENT_LENGTH"] = int(os.environ.get("QUICKTRACK_MAX_UPLOAD_MB", "32")) * 1024 * 1024

    @app.context_processor
    def inject_base_state():
        return {
            "app_title": "QuickTrack",
            "public_prefix": request.headers.get("X-Forwarded-Prefix", "").rstrip("/"),
        }

    @app.get("/")
    def index():
        records = read_records(paths["records"])[:30]
        sender_id = request.cookies.get("quicktrack_sender_id", "")
        return render_template("index.html", records=records, sender_id=sender_id)

    @app.post("/submit")
    def submit():
        photo = request.files.get("photo")
        if photo is None or not photo.filename:
            return render_template(
                "index.html",
                records=read_records(paths["records"])[:30],
                sender_id=request.form.get("sender_id", ""),
                error="Photo is required.",
            ), 400

        received_at = utcnow()
        sender_id = clean_sender_id(request.form.get("sender_id", ""))
        record_id = record_id_for(sender_id, received_at)
        latitude = parse_float(request.form.get("latitude", ""))
        longitude = parse_float(request.form.get("longitude", ""))
        accuracy_m = parse_float(request.form.get("accuracy_m", ""))

        try:
            photo_meta = save_photo(photo, paths["photos"], record_id)
        except ValueError as exc:
            return render_template(
                "index.html",
                records=read_records(paths["records"])[:30],
                sender_id=sender_id,
                error=str(exc),
            ), 400

        record = {
            "id": record_id,
            "type": "quicktrack.photo_observation",
            "schema_version": 1,
            "created_at": received_at.isoformat().replace("+00:00", "Z"),
            "sender_id": sender_id,
            "description": clean_text(request.form.get("description", ""), 2000),
            "location": {
                "latitude": latitude,
                "longitude": longitude,
                "accuracy_m": accuracy_m,
                "captured_at": clean_text(request.form.get("location_captured_at", ""), 80),
            } if latitude is not None and longitude is not None else None,
            "photo": photo_meta,
        }
        write_record(paths["records"], record)

        response = make_response(redirect(url_for("index", saved=record_id)))
        if sender_id:
            response.set_cookie(
                "quicktrack_sender_id",
                sender_id,
                max_age=60 * 60 * 24 * 365,
                httponly=False,
                samesite="Lax",
            )
        return response

    @app.get("/photos/<path:filename>")
    def photo(filename: str):
        safe_name = secure_filename(filename)
        if safe_name != filename:
            abort(404)
        path = paths["photos"] / safe_name
        if not path.exists():
            abort(404)
        return send_file(path)

    @app.get("/api/v1/records")
    def api_records():
        return {
            "app": "quicktrack",
            "records": read_records(paths["records"]),
        }

    @app.after_request
    def no_store_dynamic(response: Response):
        if request.path == "/" or request.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        return response

    return app


def main() -> None:
    parser = argparse.ArgumentParser(description="QuickTrack photo observation capture")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=int(os.environ.get("QUICKTRACK_PORT", "5107")))
    args = parser.parse_args()
    create_app().run(host=args.host, port=args.port)


if __name__ == "__main__":
    main()
