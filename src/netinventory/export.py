from __future__ import annotations

import io
import json
import tarfile
from datetime import UTC, datetime
from pathlib import Path

from netinventory.config import get_app_paths
from netinventory.storage.db import Database


def build_export_bundle_bytes() -> bytes:
    db = Database(get_app_paths())
    payload = db.export_bundle_data()
    payload["exported_at"] = datetime.now(UTC).isoformat()

    json_bytes = json.dumps(payload, indent=2, sort_keys=True).encode("utf-8")
    bundle_name = f"netinventory-export-{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}.tar.gz"

    out = io.BytesIO()
    with tarfile.open(fileobj=out, mode="w:gz") as archive:
        info = tarfile.TarInfo(name="export.json")
        info.size = len(json_bytes)
        archive.addfile(info, io.BytesIO(json_bytes))
    out.seek(0)
    return out.read()


def write_export_bundle(output_path: str | None = None) -> Path:
    paths = get_app_paths()
    paths.state_dir.mkdir(parents=True, exist_ok=True)

    if output_path is None:
        output = paths.state_dir / f"netinventory-export-{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}.tar.gz"
    else:
        output = Path(output_path).expanduser()
        output.parent.mkdir(parents=True, exist_ok=True)

    output.write_bytes(build_export_bundle_bytes())
    return output
