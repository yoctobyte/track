from __future__ import annotations

import uuid
from datetime import UTC, datetime

from flask import Flask, Response, jsonify, render_template, request

from netinventory.auth import load_or_create_shared_secret
from netinventory.config import get_app_paths, get_hub_settings
from netinventory.context import add_user_context
from netinventory.core.context import UserContextRecord
from netinventory.realtime import gather_realtime
from netinventory.storage.db import Database
from netinventory.sync import get_sync_settings, run_sync_once, save_sync_settings


LOCATION_ENTITY_KIND = "current_location"
LOCATION_ENTITY_ID = "active"
LOCATION_FIELDS = ("building", "sublocation", "cabinet", "switch", "switch_port", "notes")


def create_hub_web() -> Flask:
    app = Flask(__name__, template_folder="templates")
    app.config["NETINV_PATHS"] = get_app_paths()
    app.config["NETINV_SETTINGS"] = get_hub_settings()

    @app.context_processor
    def inject_globals():
        return {
            "hub_settings": app.config["NETINV_SETTINGS"],
            "now": datetime.now(UTC),
            "track_base_url": app.config["NETINV_SETTINGS"].track_base_url,
        }

    @app.get("/")
    def index():
        paths = app.config["NETINV_PATHS"]
        settings = app.config["NETINV_SETTINGS"]
        db = Database(paths)
        db.upsert_task_definitions([])
        secret = load_or_create_shared_secret(paths)
        status = db.get_status()
        networks = db.list_networks()[:8]
        recent_runs = db.list_recent_task_runs(limit=8)
        context_rows = db.list_user_context()[:10]
        last_change = db.get_app_state("last_material_change_at")
        sync_settings = get_sync_settings(db)
        location = current_location(db)

        network_rows = []
        for network in networks:
            latest = db.get_latest_observation(network.network_id)
            facts = latest.get("facts", {}) if latest else {}
            network_rows.append({"summary": network.to_dict(), "latest": latest, "facts": facts})

        return render_template(
            "hub_index.html",
            title="NetInventory",
            subtitle="Standalone field client",
            status=status.to_dict(),
            network_rows=network_rows,
            recent_runs=recent_runs,
            context_rows=context_rows,
            shared_secret=secret,
            public_url=f"{settings.track_base_url}{settings.public_path}",
            service_bind=settings.ui_bind,
            github_repo=settings.github_repo,
            last_change=last_change,
            sync_settings=sync_settings,
            location=location,
            location_fields=LOCATION_FIELDS,
        )

    @app.get("/api/realtime")
    def api_realtime():
        paths = app.config["NETINV_PATHS"]
        db = Database(paths)
        data = gather_realtime()
        data["last_material_change_at"] = db.get_app_state("last_material_change_at")
        data["active_network_id"] = db.get_status().active_network_id
        data["sync_last_status"] = db.get_app_state("sync_last_status") or ""
        data["sync_last_attempt_at"] = db.get_app_state("sync_last_attempt_at") or ""
        return jsonify(data)

    @app.post("/api/location")
    def api_location():
        data = request.get_json(silent=True) or {}
        paths = app.config["NETINV_PATHS"]
        db = Database(paths)
        saved: dict[str, str] = {}
        for field in LOCATION_FIELDS:
            if field not in data:
                continue
            value = str(data[field] or "").strip()
            db.add_user_context(
                UserContextRecord(
                    context_id=str(uuid.uuid4()),
                    created_at=datetime.now(UTC).isoformat(),
                    entity_kind=LOCATION_ENTITY_KIND,
                    entity_id=LOCATION_ENTITY_ID,
                    field=field,
                    value=value,
                )
            )
            saved[field] = value
        return jsonify({"ok": True, "saved": saved, "location": current_location(db)})

    @app.post("/api/sync/settings")
    def api_sync_settings():
        data = request.get_json(silent=True) or {}
        db = Database(app.config["NETINV_PATHS"])
        save_sync_settings(
            db,
            target_url=str(data.get("target_url", "")),
            username=str(data.get("username", "")),
            password=str(data.get("password", "")),
            shared_secret=str(data.get("shared_secret", "")),
            enabled=bool(data.get("enabled", True)),
        )
        return jsonify({"ok": True, "settings": get_sync_settings(db)})

    @app.post("/api/sync/run")
    def api_sync_run():
        db = Database(app.config["NETINV_PATHS"])
        result = run_sync_once(db)
        now = datetime.now(UTC).isoformat()
        db.set_app_state("sync_last_attempt_at", now)
        if result.get("ok") and not result.get("skipped"):
            db.set_app_state("sync_last_status", f"ok: {result.get('records', 0)} records")
        elif result.get("ok"):
            db.set_app_state("sync_last_status", f"idle: {result.get('reason', 'no records')}")
        else:
            db.set_app_state("sync_last_status", f"failed: {result.get('error') or result.get('reason', 'unknown')}")
        return jsonify(result)

    @app.post("/api/scan")
    def api_scan():
        db = Database(app.config["NETINV_PATHS"])
        from netinventory.tasks import run_task_once
        from netinventory.core.tasks import TaskTrigger
        run = run_task_once(db, "current_network_probe", TaskTrigger.MANUAL)
        return jsonify({"ok": True, "run": run.to_dict()})

    @app.post("/annotate_current")
    def annotate_current():
        data = request.get_json(silent=True) or {}
        location = str(data.get("rack_location", "")).strip()
        if not location:
            return jsonify({"ok": False, "error": "missing location"}), 400
        paths = app.config["NETINV_PATHS"]
        db = Database(paths)
        status = db.get_status()
        active = status.active_network_id
        if not active:
            return jsonify({"ok": False, "error": "no active network to annotate"}), 400
        add_user_context(
            db,
            entity_kind="network_summary",
            entity_id=active,
            field="rack_location",
            value=location,
        )
        return jsonify({"ok": True, "network_id": active, "rack_location": location})

    @app.get("/agents/bootstrap.sh")
    def bootstrap_script():
        settings = app.config["NETINV_SETTINGS"]
        script = f"""#!/bin/bash
set -euo pipefail

REPO_URL="${{TRACK_GITHUB_REPO:-{settings.github_repo}}}"
WORKDIR="${{TRACK_AGENT_DIR:-$HOME/track-agent}}"
TRACK_BASE_URL="${{TRACK_BASE_URL:-{settings.track_base_url}}}"
NETINV_PUBLIC_PATH="${{NETINV_PUBLIC_PATH:-{settings.public_path}}}"

if [ ! -d "$WORKDIR/.git" ]; then
  git clone "$REPO_URL" "$WORKDIR"
else
  git -C "$WORKDIR" pull --ff-only
fi

cd "$WORKDIR/netinventory-client"

if [ ! -d venv-agent ]; then
  python3 -m venv venv-agent
fi

./venv-agent/bin/pip install -q -e .

cat <<EOF
NetInventory agent prepared.

Useful commands:
  ./venv-agent/bin/netinv status
  ./venv-agent/bin/netinv collect --once
  ./venv-agent/bin/netinv export

Hub:
  $TRACK_BASE_URL$NETINV_PUBLIC_PATH

Notes:
  - privileged local capture stays on the laptop/agent side
  - upload/sync remains a separate flow
  - annotate physical context manually while in the field
EOF
"""
        return Response(
            script,
            mimetype="text/x-shellscript",
            headers={"Content-Disposition": 'attachment; filename="netinventory-bootstrap.sh"'},
        )

    return app


def current_location(db: Database) -> dict[str, str]:
    rows = db.list_user_context(entity_kind=LOCATION_ENTITY_KIND, entity_id=LOCATION_ENTITY_ID)
    latest: dict[str, str] = {field: "" for field in LOCATION_FIELDS}
    seen: set[str] = set()
    for row in rows:
        field = row.get("field", "")
        if field in latest and field not in seen:
            latest[field] = row.get("value", "") or ""
            seen.add(field)
        if len(seen) == len(LOCATION_FIELDS):
            break
    return latest


def run_hub_web(bind: str) -> int:
    host, port = _parse_bind(bind)
    app = create_hub_web()
    app.run(host=host, port=port, debug=False)
    return 0


def _parse_bind(bind: str) -> tuple[str, int]:
    if ":" not in bind:
        raise ValueError(f"invalid bind address: {bind!r}")
    host, port_text = bind.rsplit(":", 1)
    return host, int(port_text)
