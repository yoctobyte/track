from __future__ import annotations

import json
import os
import platform
import secrets
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from flask import Flask, Response, abort, jsonify, redirect, render_template, request, send_from_directory, url_for
from werkzeug.utils import secure_filename


BASE_DIR = Path(__file__).resolve().parent.parent
SIMPLE_DIR = BASE_DIR.parent / "netinventory-simple"


def load_secret_key() -> str:
    configured = os.environ.get("NETINVENTORY_HOST_SECRET_KEY", "").strip()
    if configured:
        return configured
    secret_path = BASE_DIR / ".secret_key"
    if secret_path.exists():
        return secret_path.read_text(encoding="utf-8").strip()
    secret = f"netinventory-host-{secrets.token_urlsafe(32)}"
    secret_path.write_text(secret + "\n", encoding="utf-8")
    secret_path.chmod(0o600)
    return secret


def instance_name() -> str:
    return os.environ.get("NETINVENTORY_HOST_INSTANCE", "testing").strip() or "testing"


def data_root() -> Path:
    configured = os.environ.get("NETINVENTORY_HOST_DATA_DIR", "").strip()
    if configured:
        root = Path(configured).expanduser()
    else:
        root = BASE_DIR / "data" / "environments" / instance_name()
    root.mkdir(parents=True, exist_ok=True)
    return root


def runtime_paths() -> dict[str, Path]:
    root = data_root()
    paths = {
        "root": root,
        "clients": root / "clients",
        "host_reports": root / "host-reports",
        "downloads": root / "downloads",
        "manifests": root / "manifests",
        "rack_inventory": root / "rack-inventory",
        "rack_photos": root / "rack-photos",
        "rack_history": root / "rack-history",
        "simple_registrations": root / "simple-registrations.jsonl",
        "simple_upload_token": root / ".simple-upload-token",
    }
    for key, path in paths.items():
        if key in {"simple_registrations", "simple_upload_token"}:
            continue
        path.mkdir(parents=True, exist_ok=True)
    return paths


def load_manifest(paths: dict[str, Path]) -> dict[str, object]:
    manifest_path = paths["manifests"] / "overview.json"
    if not manifest_path.exists():
        return {
            "last_updated": None,
            "client_packages": [],
            "registered_hosts": [],
            "recent_ingest": [],
        }
    with manifest_path.open(encoding="utf-8") as handle:
        loaded = json.load(handle)
    if isinstance(loaded, dict):
        return loaded
    return {
        "last_updated": None,
        "client_packages": [],
        "registered_hosts": [],
        "recent_ingest": [],
    }


def load_or_create_simple_upload_token() -> str:
    token_path = runtime_paths()["simple_upload_token"]
    if token_path.exists():
        return token_path.read_text(encoding="utf-8").strip()
    token = secrets.token_urlsafe(24)
    token_path.write_text(token + "\n", encoding="utf-8")
    token_path.chmod(0o600)
    return token


def read_simple_registrations(limit: int = 25) -> list[dict[str, Any]]:
    path = runtime_paths()["simple_registrations"]
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return list(reversed(rows[-limit:]))


def append_simple_registration(payload: dict[str, Any]) -> None:
    path = runtime_paths()["simple_registrations"]
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=True) + "\n")


def slugify(value: str) -> str:
    cleaned = "".join(char.lower() if char.isalnum() else "-" for char in value.strip())
    collapsed = "-".join(part for part in cleaned.split("-") if part)
    return collapsed[:64] or f"rack-{uuid.uuid4().hex[:8]}"


def rack_inventory_path(rack_id: str) -> Path:
    return runtime_paths()["rack_inventory"] / f"{rack_id}.json"


def rack_history_path(rack_id: str) -> Path:
    return runtime_paths()["rack_history"] / f"{rack_id}.jsonl"


def now_iso() -> str:
    return datetime.now(UTC).isoformat()


def default_rack_record() -> dict[str, Any]:
    return {
        "id": "",
        "name": "",
        "site": instance_name(),
        "building": "",
        "location": "",
        "area": "",
        "description": "",
        "notes": "",
        "photos": [],
        "devices": [],
        "created_at": None,
        "updated_at": None,
    }


def generated_rack_name(site: str, building: str, location: str, area: str) -> str:
    parts = [part for part in [site, building, location, area] if part]
    if parts:
        return " / ".join(parts) + f" / {datetime.now(UTC).strftime('%Y-%m-%d %H:%M')}"
    return f"Untitled rack {datetime.now(UTC).strftime('%Y-%m-%d %H:%M')}"


def normalise_device(device: dict[str, Any], index: int) -> dict[str, Any]:
    name = str(device.get("name", "")).strip()
    if not name:
        return {}
    kind = str(device.get("kind", "")).strip()
    brand = str(device.get("brand", "")).strip()
    notes = str(device.get("notes", "")).strip()
    ports_raw = str(device.get("port_count", "")).strip()
    units_raw = str(device.get("unit_size", "")).strip()
    position_raw = str(device.get("u_position", "")).strip()
    try:
        port_count = max(0, min(256, int(ports_raw))) if ports_raw else 0
    except ValueError:
        port_count = 0
    try:
        unit_size = max(1, min(20, int(units_raw))) if units_raw else 1
    except ValueError:
        unit_size = 1
    try:
        u_position = max(1, min(48, int(position_raw))) if position_raw else None
    except ValueError:
        u_position = None
    return {
        "id": str(device.get("id", "")).strip() or f"dev-{index + 1}",
        "name": name,
        "kind": kind,
        "brand": brand,
        "notes": notes,
        "port_count": port_count,
        "unit_size": unit_size,
        "u_position": u_position,
    }


def rack_form_data(form: Any) -> dict[str, Any]:
    devices: list[dict[str, Any]] = []
    names = form.getlist("device_name")
    for index, name in enumerate(names):
        device = normalise_device(
            {
                "id": form.getlist("device_id")[index] if index < len(form.getlist("device_id")) else "",
                "name": name,
                "kind": form.getlist("device_kind")[index] if index < len(form.getlist("device_kind")) else "",
                "brand": form.getlist("device_brand")[index] if index < len(form.getlist("device_brand")) else "",
                "notes": form.getlist("device_notes")[index] if index < len(form.getlist("device_notes")) else "",
                "port_count": form.getlist("device_port_count")[index]
                if index < len(form.getlist("device_port_count"))
                else "",
                "unit_size": form.getlist("device_unit_size")[index]
                if index < len(form.getlist("device_unit_size"))
                else "",
                "u_position": form.getlist("device_u_position")[index]
                if index < len(form.getlist("device_u_position"))
                else "",
            },
            index,
        )
        if device:
            devices.append(device)
    return {
        "name": str(form.get("name", "")).strip(),
        "site": str(form.get("site", "")).strip() or instance_name(),
        "building": str(form.get("building", "")).strip(),
        "location": str(form.get("location", "")).strip(),
        "area": str(form.get("area", "")).strip(),
        "description": str(form.get("description", "")).strip(),
        "notes": str(form.get("notes", "")).strip(),
        "devices": devices,
    }


def save_rack_record(record: dict[str, Any]) -> None:
    path = rack_inventory_path(record["id"])
    path.write_text(json.dumps(record, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")


def load_rack_record(rack_id: str) -> dict[str, Any] | None:
    path = rack_inventory_path(rack_id)
    if not path.exists():
        return None
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    if not isinstance(loaded, dict):
        return None
    record = default_rack_record()
    record.update(loaded)
    record["photos"] = loaded.get("photos", []) if isinstance(loaded.get("photos"), list) else []
    record["devices"] = loaded.get("devices", []) if isinstance(loaded.get("devices"), list) else []
    return record


def list_racks() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path in sorted(runtime_paths()["rack_inventory"].glob("*.json")):
        rack = load_rack_record(path.stem)
        if not rack:
            continue
        rows.append(rack)
    rows.sort(key=lambda item: item.get("updated_at") or "", reverse=True)
    return rows


def append_rack_history(rack_id: str, event: dict[str, Any]) -> None:
    path = rack_history_path(rack_id)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(event, ensure_ascii=True) + "\n")


def read_rack_history(rack_id: str, limit: int = 20) -> list[dict[str, Any]]:
    path = rack_history_path(rack_id)
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return list(reversed(rows[-limit:]))


def allowed_photo(filename: str) -> bool:
    suffix = Path(filename).suffix.lower()
    return suffix in {".jpg", ".jpeg", ".png", ".webp", ".gif"}


def save_uploaded_photos(rack_id: str, uploaded_files: list[Any]) -> list[dict[str, Any]]:
    saved: list[dict[str, Any]] = []
    photo_dir = runtime_paths()["rack_photos"] / rack_id
    photo_dir.mkdir(parents=True, exist_ok=True)
    for uploaded in uploaded_files:
        if not uploaded or not getattr(uploaded, "filename", ""):
            continue
        filename = secure_filename(uploaded.filename)
        if not filename or not allowed_photo(filename):
            continue
        final_name = f"{datetime.now(UTC).strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:8]}{Path(filename).suffix.lower()}"
        target = photo_dir / final_name
        uploaded.save(target)
        saved.append(
            {
                "filename": final_name,
                "original_name": filename,
                "stored_at": now_iso(),
                "size_bytes": target.stat().st_size,
            }
        )
    return saved


def rack_summary(record: dict[str, Any]) -> str:
    parts = [record.get("name") or record.get("id") or "rack"]
    location_parts = [record.get("site"), record.get("building"), record.get("location"), record.get("area")]
    joined = " / ".join(part for part in location_parts if part)
    if joined:
        parts.append(joined)
    return " - ".join(parts)


def rack_visual_devices(record: dict[str, Any]) -> list[dict[str, Any]]:
    devices = record.get("devices", []) if isinstance(record.get("devices"), list) else []
    rows: list[dict[str, Any]] = []
    next_position = 1
    for index, device in enumerate(devices):
        if not isinstance(device, dict):
            continue
        unit_size = max(1, int(device.get("unit_size") or 1))
        requested = device.get("u_position")
        try:
            position = int(requested) if requested else next_position
        except (TypeError, ValueError):
            position = next_position
        position = max(1, min(42, position))
        next_position = max(next_position, position + unit_size)
        rows.append(
            {
                **device,
                "row_start": position,
                "row_span": unit_size,
                "display_index": index + 1,
            }
        )
    return rows


def simple_template_path(name: str) -> Path:
    return SIMPLE_DIR / "templates" / name


def render_simple_template(name: str, replacements: dict[str, str]) -> str:
    text = simple_template_path(name).read_text(encoding="utf-8")
    for key, value in replacements.items():
        text = text.replace(key, value)
    return text


def simple_ingest_url(app: Flask) -> str:
    return f'{app.config["NETINV_HOST_TRACK_BASE"]}/netinventory/api/simple-ingest?env={app.config["NETINV_HOST_INSTANCE"]}'


def simple_download_response(app: Flask, template_name: str, download_name: str, mimetype: str) -> Response:
    script = render_simple_template(
        template_name,
        {
            "__TARGET_URL__": simple_ingest_url(app),
            "__TOKEN__": load_or_create_simple_upload_token(),
        },
    )
    return Response(
        script,
        mimetype=mimetype,
        headers={"Content-Disposition": f'attachment; filename="{download_name}"'},
    )


def create_app() -> Flask:
    app = Flask(__name__, template_folder=str(BASE_DIR / "templates"))
    app.config["SECRET_KEY"] = load_secret_key()
    app.config["NETINV_HOST_INSTANCE"] = instance_name()
    app.config["NETINV_HOST_BIND"] = os.environ.get("NETINVENTORY_HOST_BIND", "127.0.0.1").strip() or "127.0.0.1"
    app.config["NETINV_HOST_PORT"] = int(os.environ.get("NETINVENTORY_HOST_PORT", "8888").strip() or "8888")
    app.config["NETINV_HOST_TRACK_BASE"] = (
        os.environ.get("TRACK_BASE_URL", "https://track.praktijkpioniers.com").rstrip("/")
    )
    app.config["NETINV_HOST_PUBLIC_PATH"] = "/netinventory/"
    app.config["NETINV_CLIENT_PUBLIC_PATH"] = "/netinventory-client/"
    app.config["NETINV_GITHUB_REPO"] = os.environ.get(
        "TRACK_GITHUB_REPO",
        "https://github.com/yoctobyte/track.git",
    ).strip()

    @app.context_processor
    def inject_globals():
        return {
            "instance_name": app.config["NETINV_HOST_INSTANCE"],
            "track_base": app.config["NETINV_HOST_TRACK_BASE"],
            "netinventory_public_path": app.config["NETINV_HOST_PUBLIC_PATH"],
            "netinventory_client_public_path": app.config["NETINV_CLIENT_PUBLIC_PATH"],
            "github_repo": app.config["NETINV_GITHUB_REPO"],
            "simple_upload_token": load_or_create_simple_upload_token(),
            "now": datetime.now(UTC),
        }

    @app.get("/")
    def index():
        racks = list_racks()
        paths = runtime_paths()
        manifest = load_manifest(paths)
        client_packages = manifest.get("client_packages", [])
        registered_hosts = manifest.get("registered_hosts", [])
        recent_ingest = manifest.get("recent_ingest", [])
        simple_recent = read_simple_registrations()
        cards = [
            {
                "label": "Rack Records",
                "value": str(len(racks)),
                "hint": "Cabinets, wall racks, or device clusters being documented here.",
            },
            {
                "label": "Client Packages",
                "value": str(len(client_packages)),
                "hint": "Published laptop-side bundles and bootstrap targets.",
            },
            {
                "label": "Registered Hosts",
                "value": str(len(registered_hosts)),
                "hint": "Remote devices that can later report passive statistics.",
            },
            {
                "label": "Recent Ingest Events",
                "value": str(len(recent_ingest)),
                "hint": "Most recent uploads or synchronization attempts recorded here.",
            },
            {
                "label": "Simple Registrations",
                "value": str(len(simple_recent)),
                "hint": "Low-friction browser or script registrations for ordinary devices.",
            },
        ]
        return render_template(
            "index.html",
            title="NetInventory Host",
            subtitle="Rack inventory intake, publishing, and aggregation surface",
            cards=cards,
            racks=racks,
            manifest=manifest,
            client_packages=client_packages,
            registered_hosts=registered_hosts,
            recent_ingest=recent_ingest,
            simple_recent=simple_recent,
            paths={key: str(value) for key, value in paths.items()},
            current_host=platform.node(),
        )

    @app.get("/racks/new")
    def rack_new():
        record = default_rack_record()
        record["devices"] = [{} for _ in range(6)]
        return render_template(
            "rack_form.html",
            title="New Rack",
            subtitle="Create a cabinet, rack, or device cluster record",
            rack=record,
            history=[],
            rack_devices=[],
            photo_count=0,
            mode="new",
        )

    @app.get("/racks/<rack_id>")
    def rack_detail(rack_id: str):
        record = load_rack_record(rack_id)
        if not record:
            abort(404)
        form_rack = {**record}
        form_rack["devices"] = list(record.get("devices", [])) + [{} for _ in range(3)]
        return render_template(
            "rack_form.html",
            title=record.get("name") or rack_id,
            subtitle="Edit rack location, photos, and device list",
            rack=form_rack,
            history=read_rack_history(rack_id),
            rack_devices=rack_visual_devices(record),
            photo_count=len(record.get("photos", [])),
            mode="edit",
        )

    @app.post("/racks")
    def rack_create():
        record = default_rack_record()
        posted = rack_form_data(request.form)
        record.update(posted)
        if not record["name"]:
            record["name"] = generated_rack_name(
                record.get("site", ""),
                record.get("building", ""),
                record.get("location", ""),
                record.get("area", ""),
            )
        rack_id = slugify(record["name"])
        while rack_inventory_path(rack_id).exists():
            rack_id = f"{slugify(record['name'])}-{uuid.uuid4().hex[:4]}"
        timestamp = now_iso()
        record["id"] = rack_id
        record["created_at"] = timestamp
        record["updated_at"] = timestamp
        record["photos"] = save_uploaded_photos(rack_id, request.files.getlist("photos"))
        save_rack_record(record)
        append_rack_history(
            rack_id,
            {
                "timestamp": timestamp,
                "action": "created",
                "summary": rack_summary(record),
                "photo_count": len(record["photos"]),
                "device_count": len(record["devices"]),
            },
        )
        return redirect(url_for("rack_detail", rack_id=rack_id, saved="created"))

    @app.post("/racks/<rack_id>")
    def rack_update(rack_id: str):
        record = load_rack_record(rack_id)
        if not record:
            abort(404)
        posted = rack_form_data(request.form)
        if not posted["name"]:
            posted["name"] = record.get("name") or generated_rack_name(
                posted.get("site", "") or record.get("site", ""),
                posted.get("building", "") or record.get("building", ""),
                posted.get("location", "") or record.get("location", ""),
                posted.get("area", "") or record.get("area", ""),
            )
        before = json.dumps(record, sort_keys=True)
        record.update(posted)
        new_photos = save_uploaded_photos(rack_id, request.files.getlist("photos"))
        record["photos"] = list(record.get("photos", [])) + new_photos
        record["updated_at"] = now_iso()
        save_rack_record(record)
        after = json.dumps(record, sort_keys=True)
        append_rack_history(
            rack_id,
            {
                "timestamp": record["updated_at"],
                "action": "updated",
                "summary": rack_summary(record),
                "photo_count": len(new_photos),
                "device_count": len(record["devices"]),
                "changed": before != after,
            },
        )
        return redirect(url_for("rack_detail", rack_id=rack_id, saved="updated"))

    @app.get("/rack-photos/<rack_id>/<filename>")
    def rack_photo(rack_id: str, filename: str):
        photo_dir = runtime_paths()["rack_photos"] / rack_id
        return send_from_directory(photo_dir, filename)

    @app.get("/downloads/netinventory-client-bootstrap.sh")
    def download_bootstrap():
        repo = app.config["NETINV_GITHUB_REPO"]
        script = f"""#!/bin/bash
set -euo pipefail

REPO_URL="${{TRACK_GITHUB_REPO:-{repo}}}"
WORKDIR="${{TRACK_NETINVENTORY_CLIENT_DIR:-$HOME/track-netinventory-client}}"

if [ ! -d "$WORKDIR/.git" ]; then
  git clone "$REPO_URL" "$WORKDIR"
else
  git -C "$WORKDIR" pull --ff-only
fi

cd "$WORKDIR/netinventory-client"
./run-track.sh
"""
        return Response(
            script,
            mimetype="text/x-shellscript",
            headers={"Content-Disposition": 'attachment; filename="netinventory-client-bootstrap.sh"'},
        )

    @app.post("/api/simple-browser")
    def simple_browser():
        payload = request.get_json(silent=True) or {}
        if not isinstance(payload, dict):
            return jsonify({"ok": False, "error": "invalid payload"}), 400
        entry = {
            "kind": "browser",
            "timestamp": datetime.now(UTC).isoformat(),
            "instance": app.config["NETINV_HOST_INSTANCE"],
            "description": str(payload.get("description", "")).strip(),
            "browser": payload.get("browser") if isinstance(payload.get("browser"), dict) else {},
            "client": {
                "remote_addr": request.headers.get("X-Forwarded-For", request.remote_addr or ""),
                "user_agent": request.headers.get("User-Agent", ""),
                "forwarded_host": request.headers.get("X-Forwarded-Host", ""),
                "forwarded_proto": request.headers.get("X-Forwarded-Proto", ""),
            },
        }
        append_simple_registration(entry)
        return jsonify({"ok": True, "stored": entry["timestamp"]})

    @app.post("/api/simple-ingest")
    def simple_ingest():
        token = request.headers.get("X-NetInventory-Simple-Token", "").strip()
        if token != load_or_create_simple_upload_token():
            return jsonify({"ok": False, "error": "invalid token"}), 403
        payload = request.get_json(silent=True) or {}
        if not isinstance(payload, dict):
            return jsonify({"ok": False, "error": "invalid payload"}), 400
        entry = {
            "kind": str(payload.get("kind", "script")).strip() or "script",
            "timestamp": datetime.now(UTC).isoformat(),
            "instance": app.config["NETINV_HOST_INSTANCE"],
            "description": str(payload.get("description", "")).strip(),
            "payload": payload,
            "client": {
                "remote_addr": request.headers.get("X-Forwarded-For", request.remote_addr or ""),
                "user_agent": request.headers.get("User-Agent", ""),
            },
        }
        append_simple_registration(entry)
        return jsonify({"ok": True, "stored": entry["timestamp"]})

    @app.get("/downloads/register-device-user.sh")
    def download_simple_shell_user():
        return simple_download_response(
            app,
            "register-device-user.sh.tmpl",
            "register-device-user.sh",
            "text/x-shellscript",
        )

    @app.get("/downloads/register-device-admin.sh")
    def download_simple_shell_admin():
        return simple_download_response(
            app,
            "register-device-admin.sh.tmpl",
            "register-device-admin.sh",
            "text/x-shellscript",
        )

    @app.get("/downloads/register-device-user.bat")
    def download_simple_batch_user():
        return simple_download_response(
            app,
            "register-device-user.bat.tmpl",
            "register-device-user.bat",
            "text/plain",
        )

    @app.get("/downloads/register-device-admin.bat")
    def download_simple_batch_admin():
        return simple_download_response(
            app,
            "register-device-admin.bat.tmpl",
            "register-device-admin.bat",
            "text/plain",
        )

    @app.get("/health")
    def health():
        return {
            "status": "ok",
            "service": "netinventory-host",
            "instance": app.config["NETINV_HOST_INSTANCE"],
            "timestamp": datetime.now(UTC).isoformat(),
            "simple_registrations": len(read_simple_registrations(limit=10000)),
        }

    return app
