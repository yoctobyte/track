import hashlib
import mimetypes
import shutil
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


def store_original_path(source_path: Path, original_filename: str, session_id: int) -> dict:
    """Store an existing file path as an original asset without loading it all into memory."""
    source_path = Path(source_path)
    mime, _ = mimetypes.guess_type(original_filename)
    sha256 = hashlib.sha256()
    with source_path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            sha256.update(chunk)
    session_dir = get_data_dir() / "originals" / f"session_{session_id:04d}"
    session_dir.mkdir(parents=True, exist_ok=True)

    safe_name = Path(original_filename).name
    dest = session_dir / f"{sha256.hexdigest()[:12]}_{safe_name}"
    if not dest.exists():
        with source_path.open("rb") as src, dest.open("wb") as dst:
            shutil.copyfileobj(src, dst)

    return {
        "storage_path": str(dest.relative_to(get_data_dir())),
        "hash_sha256": sha256.hexdigest(),
        "file_size": source_path.stat().st_size,
        "mime_type": mime or "application/octet-stream",
    }


def store_preview(image_data: bytes, frame_id: int, ext: str = ".jpg") -> str:
    """Store a preview/thumbnail and return the relative path."""
    preview_dir = get_data_dir() / "previews"
    preview_dir.mkdir(parents=True, exist_ok=True)

    dest = preview_dir / f"frame_{frame_id:06d}{ext}"
    dest.write_bytes(image_data)
    return str(dest.relative_to(get_data_dir()))


def store_asset_preview(image_data: bytes, asset_id: int, ext: str = ".jpg") -> str:
    """Store an asset-level preview and return the relative path."""
    preview_dir = get_data_dir() / "previews"
    preview_dir.mkdir(parents=True, exist_ok=True)

    dest = preview_dir / f"asset_{asset_id:06d}{ext}"
    dest.write_bytes(image_data)
    return str(dest.relative_to(get_data_dir()))


def store_extracted_frame(image_data: bytes, session_id: int, source_asset_id: int, filename: str) -> dict:
    """Store a derived frame extracted from a video asset."""
    sha256 = hashlib.sha256(image_data).hexdigest()
    session_dir = get_data_dir() / "extracted_frames" / f"session_{session_id:04d}" / f"video_asset_{source_asset_id:04d}"
    session_dir.mkdir(parents=True, exist_ok=True)

    safe_name = Path(filename).name
    dest = session_dir / f"{sha256[:12]}_{safe_name}"
    if not dest.exists():
        dest.write_bytes(image_data)

    return {
        "storage_path": str(dest.relative_to(get_data_dir())),
        "hash_sha256": sha256,
        "file_size": len(image_data),
        "mime_type": "image/jpeg",
    }


def get_absolute_path(relative_path: str) -> Path:
    """Resolve a data-relative path to an absolute path."""
    return get_data_dir() / relative_path
