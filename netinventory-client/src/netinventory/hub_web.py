from __future__ import annotations

import hashlib
import json
import uuid
from datetime import UTC, datetime

from flask import Flask, Response, abort, jsonify, render_template, request

from netinventory.auth import load_or_create_shared_secret
from netinventory.collect.collector import CollectedObservation
from netinventory.config import get_app_paths, get_hub_settings
from netinventory.context import add_user_context
from netinventory.core.context import UserContextRecord
from netinventory.probes import PROBE_IDS, PROBE_LABELS, gather_probe_tooling, run_probe
from netinventory.realtime import gather_realtime
from netinventory.storage.db import Database
from netinventory.sync import (
    get_sync_settings,
    get_sync_targets,
    has_credentials,
    remove_sync_target,
    run_sync_once,
    save_sync_settings,
    upsert_sync_target,
)


LOCATION_ENTITY_KIND = "current_location"
LOCATION_ENTITY_ID = "active"
LOCATION_FIELDS = ("building", "sublocation", "cabinet", "switch", "switch_port", "notes")
SNAPSHOT_KIND = "location_snapshot"
PROBE_ENABLED_KEY_PREFIX = "probe_enabled."


def probe_enabled_lookup(db: Database):
    state = db.get_app_state_many(PROBE_ENABLED_KEY_PREFIX)

    def _lookup(probe_id: str) -> bool:
        key = f"{PROBE_ENABLED_KEY_PREFIX}{probe_id}"
        if key not in state:
            return True  # default: enabled
        return state[key] != "0"

    return _lookup


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
        sync_targets = get_sync_targets(db)
        sync_logged_in = has_credentials(sync_settings)
        location = current_location(db)
        snapshots = list_recent_snapshots(db, limit=5)

        network_rows = []
        for network in networks:
            latest = db.get_latest_observation(network.network_id)
            facts = latest.get("facts", {}) if latest else {}
            network_rows.append({"summary": network.to_dict(), "latest": latest, "facts": facts})

        targets = {}
        try:
            ldb = db.location_db
            targets = {
                "buildings": ldb.list_buildings(),
                "locations": ldb.list_locations(),
                "cabinets": ldb.list_cabinets(),
                "devices": ldb.list_devices(),
            }
        except Exception:
            pass

        tooling = gather_probe_tooling(probe_enabled_lookup(db))
        probe_options = [
            {"id": row["id"], "label": row["label"], "satisfied": row["satisfied"]}
            for row in tooling
            if row["enabled"]
        ]
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
            sync_targets=sync_targets,
            sync_logged_in=sync_logged_in,
            location=location,
            location_fields=LOCATION_FIELDS,
            probe_options=probe_options,
            probe_tooling=tooling,
            snapshots=snapshots,
            targets=targets,
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
            
        _ensure_local_location_db(db, saved)
        return jsonify({"ok": True, "saved": saved, "location": current_location(db)})

    @app.post("/api/sync/settings")
    def api_sync_settings():
        data = request.get_json(silent=True) or {}
        db = Database(app.config["NETINV_PATHS"])
        target_url = str(data.get("target_url", "")).strip()
        username = str(data.get("username", ""))
        password = str(data.get("password", ""))
        shared_secret = str(data.get("shared_secret", ""))
        enabled = bool(data.get("enabled", True))
        save_sync_settings(
            db,
            target_url=target_url,
            username=username,
            password=password,
            shared_secret=shared_secret,
            enabled=enabled,
        )
        if target_url and bool(data.get("remember", True)):
            upsert_sync_target(
                db,
                name=str(data.get("name", "") or target_url),
                target_url=target_url,
                username=username,
                password=password,
                shared_secret=shared_secret,
            )

        if enabled and target_url:
            try:
                import threading
                threading.Thread(target=run_sync_once, args=(db,), daemon=True).start()
            except Exception:
                pass

        return jsonify({
            "ok": True,
            "settings": get_sync_settings(db),
            "targets": get_sync_targets(db),
            "logged_in": has_credentials(get_sync_settings(db)),
        })

    @app.get("/api/sync/targets")
    def api_sync_targets_list():
        db = Database(app.config["NETINV_PATHS"])
        return jsonify({"targets": get_sync_targets(db), "active_url": get_sync_settings(db).get("target_url", "")})

    @app.post("/api/sync/targets/select")
    def api_sync_target_select():
        data = request.get_json(silent=True) or {}
        url = str(data.get("target_url", "")).strip()
        if not url:
            abort(400)
        db = Database(app.config["NETINV_PATHS"])
        target = next((t for t in get_sync_targets(db) if t["target_url"] == url), None)
        if not target:
            abort(404)
        save_sync_settings(
            db,
            target_url=target["target_url"],
            username=target["username"],
            password=target["password"],
            shared_secret=target["shared_secret"],
            enabled=get_sync_settings(db).get("enabled", "1") == "1",
        )
        return jsonify({"ok": True, "settings": get_sync_settings(db)})

    @app.post("/api/sync/targets/delete")
    def api_sync_target_delete():
        data = request.get_json(silent=True) or {}
        url = str(data.get("target_url", "")).strip()
        if not url:
            abort(400)
        db = Database(app.config["NETINV_PATHS"])
        targets = remove_sync_target(db, url)
        return jsonify({"ok": True, "targets": targets})

    @app.post("/api/sync/logout")
    def api_sync_logout():
        db = Database(app.config["NETINV_PATHS"])
        current = get_sync_settings(db)
        save_sync_settings(
            db,
            target_url=current["target_url"],
            username="",
            password="",
            shared_secret="",
            enabled=current.get("enabled", "1") == "1",
        )
        return jsonify({"ok": True, "settings": get_sync_settings(db), "logged_in": False})

    @app.post("/api/sync/run")
    def api_sync_run():
        db = Database(app.config["NETINV_PATHS"])
        result = run_sync_once(db, manual=True)
        now = datetime.now(UTC).isoformat()
        db.set_app_state("sync_last_attempt_at", now)
        if result.get("ok") and not result.get("skipped"):
            db.set_app_state("sync_last_status", f"ok: {result.get('records', 0)} records")
        elif result.get("ok"):
            db.set_app_state("sync_last_status", f"idle: {result.get('reason', 'no records')}")
        else:
            db.set_app_state("sync_last_status", f"failed: {result.get('error') or result.get('reason', 'unknown')}")
        return jsonify(result)

    @app.get("/api/tooling")
    def api_tooling():
        db = Database(app.config["NETINV_PATHS"])
        return jsonify({"probes": gather_probe_tooling(probe_enabled_lookup(db))})

    @app.post("/api/tooling/<probe_id>")
    def api_tooling_set(probe_id: str):
        if probe_id not in PROBE_IDS:
            abort(404)
        data = request.get_json(silent=True) or {}
        enabled = bool(data.get("enabled", True))
        db = Database(app.config["NETINV_PATHS"])
        db.set_app_state(f"{PROBE_ENABLED_KEY_PREFIX}{probe_id}", "1" if enabled else "0")
        return jsonify({"ok": True, "id": probe_id, "enabled": enabled})

    @app.post("/api/snapshot")
    def api_snapshot():
        data = request.get_json(silent=True) or {}
        location_input = {f: str(data.get(f, "") or "").strip() for f in LOCATION_FIELDS}
        is_enabled = probe_enabled_lookup(Database(app.config["NETINV_PATHS"]))
        requested_probes = [
            p for p in (data.get("probes") or [])
            if p in PROBE_IDS and is_enabled(p)
        ]
        probe_kwargs: dict[str, dict] = data.get("probe_options") or {}

        paths = app.config["NETINV_PATHS"]
        db = Database(paths)

        for field, value in location_input.items():
            if value or current_location(db).get(field):
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

        _ensure_local_location_db(db, location_input)

        probe_results: dict[str, dict] = {}
        for probe_id in requested_probes:
            probe_results[probe_id] = run_probe(probe_id, **(probe_kwargs.get(probe_id) or {}))

        status = db.get_status()
        active_network = status.active_network_id or "unknown"
        snapshot_id = str(uuid.uuid4())
        observed_at = datetime.now(UTC).isoformat()
        location_summary = " / ".join(v for v in (location_input[f] for f in LOCATION_FIELDS) if v) or "(no location set)"

        facts: dict[str, object] = {
            "snapshot_id": snapshot_id,
            "location": {f: location_input[f] for f in LOCATION_FIELDS},
            "probes_requested": list(requested_probes),
            "probes": probe_results,
        }
        material_seed = json.dumps({"snapshot": snapshot_id, "at": observed_at}, sort_keys=True).encode("utf-8")
        material_fp = hashlib.sha256(material_seed).hexdigest()
        observation = CollectedObservation(
            observation_id=snapshot_id,
            observed_at=observed_at,
            network_id=active_network,
            kind=SNAPSHOT_KIND,
            facts=facts,
            material_fingerprint=material_fp,
            summary=location_summary,
            display_name=location_summary[:80],
            confidence=0.95,
        )
        db.record_observation(observation)
        return jsonify(
            {
                "ok": True,
                "snapshot_id": snapshot_id,
                "observed_at": observed_at,
                "location": current_location(db),
                "probes": probe_results,
                "summary": location_summary,
            }
        )

    @app.get("/api/snapshots")
    def api_snapshots():
        db = Database(app.config["NETINV_PATHS"])
        return jsonify({"snapshots": list_recent_snapshots(db, limit=20)})

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


def list_recent_snapshots(db: Database, limit: int = 5) -> list[dict[str, object]]:
    rows = db.list_observations_by_kind(SNAPSHOT_KIND, limit=limit)
    snapshots: list[dict[str, object]] = []
    for row in rows:
        facts = row.get("facts") or {}
        if not isinstance(facts, dict):
            facts = {}
        probes = facts.get("probes") if isinstance(facts.get("probes"), dict) else {}
        snapshots.append(
            {
                "snapshot_id": row.get("observation_id"),
                "observed_at": row.get("observed_at"),
                "summary": row.get("summary"),
                "location": facts.get("location") or {},
                "probes_requested": facts.get("probes_requested") or [],
                "probes": probes,
                "network_id": row.get("network_id"),
            }
        )
    return snapshots


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

def _ensure_local_location_db(db: Database, location_input: dict[str, str]) -> None:
    try:
        ldb = db.location_db
        b_name = location_input.get("building", "").strip()
        l_name = location_input.get("sublocation", "").strip()
        c_name = location_input.get("cabinet", "").strip()
        d_name = location_input.get("switch", "").strip()

        b_id, l_id, c_id = None, None, None

        if b_name:
            b = next((x for x in ldb.list_buildings() if x["name"] == b_name), None)
            if not b:
                b = ldb.create_building(name=b_name)
            b_id = b["id"]

        if l_name and b_id:
            loc = next((x for x in ldb.list_locations(building_id=b_id) if x["name"] == l_name), None)
            if not loc:
                loc = ldb.create_location(building_id=b_id, name=l_name, type="room")
            l_id = loc["id"]

        if c_name and l_id:
            cab = next((x for x in ldb.list_cabinets(location_id=l_id) if x["name"] == c_name), None)
            if not cab:
                cab = ldb.create_cabinet(location_id=l_id, name=c_name)
            c_id = cab["id"]

        if d_name and c_id:
            dev = next((x for x in ldb.list_devices(cabinet_id=c_id) if x["name"] == d_name), None)
            if not dev:
                ldb.create_device(cabinet_id=c_id, location_id=l_id, name=d_name, kind="switch")

    except Exception as e:
        import logging
        logging.getLogger(__name__).warning("Failed to insert local location DB: %s", e)
