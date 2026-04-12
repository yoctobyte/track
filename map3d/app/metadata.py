import io
import json
from datetime import datetime

from PIL import Image, ExifTags


def extract_metadata(file_data: bytes) -> dict:
    """Extract metadata from image bytes. Returns a dict safe for JSON storage."""
    result = {
        "width": None,
        "height": None,
        "timestamp_original": None,
        "metadata_json": {},
    }

    try:
        img = Image.open(io.BytesIO(file_data))
    except Exception:
        return result

    result["width"] = img.width
    result["height"] = img.height

    exif_data = {}
    try:
        raw_exif = img.getexif()
        if raw_exif:
            for tag_id, value in raw_exif.items():
                tag_name = ExifTags.TAGS.get(tag_id, str(tag_id))
                # Convert non-serializable types to strings
                try:
                    json.dumps(value)
                    exif_data[tag_name] = value
                except (TypeError, ValueError):
                    exif_data[tag_name] = str(value)
    except Exception:
        pass

    result["metadata_json"] = exif_data

    # Try to extract original timestamp
    for field in ("DateTimeOriginal", "DateTimeDigitized", "DateTime"):
        val = exif_data.get(field)
        if val and isinstance(val, str):
            for fmt in ("%Y:%m:%d %H:%M:%S", "%Y-%m-%d %H:%M:%S"):
                try:
                    result["timestamp_original"] = datetime.strptime(val, fmt)
                    break
                except ValueError:
                    continue
            if result["timestamp_original"]:
                break

    return result


def generate_preview(file_data: bytes, max_size: int = 800) -> bytes | None:
    """Generate a JPEG preview/thumbnail. Returns bytes or None on failure."""
    try:
        img = Image.open(io.BytesIO(file_data))
        img.thumbnail((max_size, max_size), Image.LANCZOS)
        # Convert to RGB if needed (e.g. PNG with alpha)
        if img.mode not in ("RGB", "L"):
            img = img.convert("RGB")
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=85)
        return buf.getvalue()
    except Exception:
        return None
