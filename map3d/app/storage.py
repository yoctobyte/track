import hashlib
import mimetypes
from pathlib import Path

from flask import current_app


def get_data_dir() -> Path:
    return current_app.config["DATA_DIR"]


def store_original(file_data: bytes, original_filename: str, session_id: int) -> dict:
    """Store an original file and return storage info.

    Returns dict with: storage_path, hash_sha256, file_size, mime_type
    """
    sha256 = hashlib.sha256(file_data).hexdigest()
    mime, _ = mimetypes.guess_type(original_filename)

    session_dir = get_data_dir() / "originals" / f"session_{session_id:04d}"
    session_dir.mkdir(parents=True, exist_ok=True)

    # Use hash prefix to avoid collisions, keep original name for readability
    safe_name = Path(original_filename).name
    dest = session_dir / f"{sha256[:12]}_{safe_name}"

    # Don't overwrite if identical file already exists
    if not dest.exists():
        dest.write_bytes(file_data)

    return {
        "storage_path": str(dest.relative_to(get_data_dir())),
        "hash_sha256": sha256,
        "file_size": len(file_data),
        "mime_type": mime or "application/octet-stream",
    }


def store_preview(image_data: bytes, frame_id: int, ext: str = ".jpg") -> str:
    """Store a preview/thumbnail and return the relative path."""
    preview_dir = get_data_dir() / "previews"
    preview_dir.mkdir(parents=True, exist_ok=True)

    dest = preview_dir / f"frame_{frame_id:06d}{ext}"
    dest.write_bytes(image_data)
    return str(dest.relative_to(get_data_dir()))


def get_absolute_path(relative_path: str) -> Path:
    """Resolve a data-relative path to an absolute path."""
    return get_data_dir() / relative_path
