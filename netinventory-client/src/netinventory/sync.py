from __future__ import annotations

import base64
import json
import logging
import threading
import time
import urllib.error
import urllib.request

from netinventory.config import get_app_paths, get_hub_settings
from netinventory.storage.db import Database

logger = logging.getLogger(__name__)

SYNC_KEYS = (
    "sync_target_url",
    "sync_username",
    "sync_password",
    "sync_shared_secret",
    "sync_enabled",
    "sync_last_status",
    "sync_last_attempt_at",
    "sync_targets",
)


def get_sync_settings(db: Database) -> dict[str, str]:
    state = db.get_app_state_many("sync_")
    target = state.get("sync_target_url", "")
    return {
        "target_url": target,
        "username": state.get("sync_username", ""),
        "password": state.get("sync_password", ""),
        "shared_secret": state.get("sync_shared_secret", ""),
        "enabled": state.get("sync_enabled", "1"),
        "last_status": state.get("sync_last_status", ""),
        "last_attempt_at": state.get("sync_last_attempt_at", ""),
    }


def get_sync_targets(db: Database) -> list[dict[str, str]]:
    raw = db.get_app_state("sync_targets") or "[]"
    try:
        data = json.loads(raw)
    except (TypeError, ValueError):
        return []
    if not isinstance(data, list):
        return []
    cleaned: list[dict[str, str]] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        url = str(item.get("target_url") or "").strip()
        if not url:
            continue
        cleaned.append({
            "name": str(item.get("name") or url),
            "target_url": url,
            "username": str(item.get("username") or ""),
            "password": str(item.get("password") or ""),
            "shared_secret": str(item.get("shared_secret") or ""),
        })
    return cleaned


def save_sync_targets(db: Database, targets: list[dict[str, str]]) -> None:
    db.set_app_state("sync_targets", json.dumps(targets))


def upsert_sync_target(db: Database, *, name: str, target_url: str, username: str, password: str, shared_secret: str) -> list[dict[str, str]]:
    target_url = target_url.strip()
    if not target_url:
        return get_sync_targets(db)
    targets = get_sync_targets(db)
    entry = {
        "name": name.strip() or target_url,
        "target_url": target_url,
        "username": username.strip(),
        "password": password,
        "shared_secret": shared_secret.strip(),
    }
    found = False
    for i, t in enumerate(targets):
        if t["target_url"] == target_url:
            targets[i] = entry
            found = True
            break
    if not found:
        targets.append(entry)
    save_sync_targets(db, targets)
    return targets


def remove_sync_target(db: Database, target_url: str) -> list[dict[str, str]]:
    targets = [t for t in get_sync_targets(db) if t.get("target_url") != target_url]
    save_sync_targets(db, targets)
    return targets


def has_credentials(settings: dict[str, str]) -> bool:
    if (settings.get("shared_secret") or "").strip():
        return True
    return bool((settings.get("username") or "").strip() and (settings.get("password") or ""))


def save_sync_settings(
    db: Database,
    *,
    target_url: str,
    username: str,
    password: str,
    shared_secret: str,
    enabled: bool,
) -> None:
    db.set_app_state("sync_target_url", target_url.strip())
    db.set_app_state("sync_username", username.strip())
    db.set_app_state("sync_password", password)
    db.set_app_state("sync_shared_secret", shared_secret.strip())
    db.set_app_state("sync_enabled", "1" if enabled else "0")


def _pull_locations(db: Database, settings: dict[str, str]) -> None:
    target = settings["target_url"]
    if not target or "/api/simple-ingest" not in target:
        return
    export_url = target.replace("/api/simple-ingest", "/api/core/locations/export")
    
    headers = {}
    if settings["shared_secret"]:
        headers["X-NetInv-Token"] = settings["shared_secret"]
    if settings["username"] and settings["password"]:
        token = base64.b64encode(f"{settings['username']}:{settings['password']}".encode("utf-8")).decode("ascii")
        headers["Authorization"] = f"Basic {token}"
        
    request = urllib.request.Request(export_url, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            if response.status == 200:
                data = json.loads(response.read().decode("utf-8"))
                ldb = db.location_db
                for b in data.get("buildings", []):
                    if not ldb.get_building(b["id"]):
                        ldb.create_building(name=b["name"], description=b.get("description", ""), id=b["id"])
                for l in data.get("locations", []):
                    if not ldb.get_location(l["id"]):
                        ldb.create_location(building_id=l["building_id"], name=l["name"], type=l.get("type", "room"), id=l["id"])
                for c in data.get("cabinets", []):
                    if not ldb.get_cabinet(c["id"]):
                        ldb.create_cabinet(location_id=c["location_id"], name=c["name"], id=c["id"])
                for d in data.get("devices", []):
                    if not ldb.get_device(d["id"]):
                        ldb.create_device(cabinet_id=d.get("cabinet_id"), location_id=d.get("location_id"), name=d["name"], kind=d.get("kind", ""), id=d["id"])
    except Exception as exc:
        logger.warning(f"Failed to pull locations: {exc}")

def run_sync_once(db: Database, *, manual: bool = False) -> dict[str, object]:
    settings = get_sync_settings(db)
    if not manual and settings["enabled"] != "1":
        return {"ok": False, "skipped": True, "reason": "sync disabled"}

    target = settings["target_url"]
    if not target:
        return {"ok": False, "skipped": True, "reason": "no target configured"}

    if not has_credentials(settings):
        return {"ok": False, "skipped": True, "reason": "logged out (no credentials)"}

    _pull_locations(db, settings)

    last_sync = db.get_last_sync_time()
    bundle = db.export_bundle_data(since_iso=last_sync)
    records = bundle.get("records", [])
    if not records:
        return {"ok": True, "skipped": True, "reason": "no new records", "records": 0}

    payload = {
        "kind": "sync-bundle",
        "description": f"Delta Sync ({len(records)} records)",
        "payload": bundle,
    }
    body = json.dumps(payload, ensure_ascii=True).encode("utf-8")
    headers = {
        "Content-Type": "application/json",
        "X-Track-Client-Id": str(bundle.get("source_device_id", "unknown")),
    }
    if settings["shared_secret"]:
        headers["X-NetInv-Token"] = settings["shared_secret"]
    if settings["username"] and settings["password"]:
        token = base64.b64encode(f"{settings['username']}:{settings['password']}".encode("utf-8")).decode("ascii")
        headers["Authorization"] = f"Basic {token}"

    request = urllib.request.Request(target, data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            status = response.status
    except urllib.error.HTTPError as exc:
        return {"ok": False, "error": f"http {exc.code}: {exc.reason}"}
    except urllib.error.URLError as exc:
        return {"ok": False, "error": f"connection failed: {exc.reason}"}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}

    if status != 200:
        return {"ok": False, "error": f"unexpected status {status}"}

    newest: str | None = None
    for rec in records:
        if not isinstance(rec, dict):
            continue
        cat = rec.get("created_at") or rec.get("observed_at")
        if isinstance(cat, str) and (newest is None or cat > newest):
            newest = cat
    if newest:
        db.set_last_sync_time(newest)

    return {"ok": True, "records": len(records), "newest": newest}


def run_sync_worker() -> None:
    db = Database(get_app_paths())
    while True:
        try:
            settings = get_sync_settings(db)
            if settings["enabled"] != "1":
                time.sleep(30)
                continue
            result = run_sync_once(db)
            from datetime import UTC, datetime
            now = datetime.now(UTC).isoformat()
            db.set_app_state("sync_last_attempt_at", now)
            if result.get("ok"):
                if result.get("skipped"):
                    db.set_app_state("sync_last_status", f"idle: {result.get('reason', 'no records')}")
                else:
                    db.set_app_state("sync_last_status", f"ok: {result.get('records', 0)} records")
                    logger.info(f"Sync ok ({result.get('records', 0)} records)")
            else:
                db.set_app_state("sync_last_status", f"failed: {result.get('error') or result.get('reason', 'unknown')}")
                logger.warning(f"Sync failed: {result}")
        except Exception as exc:
            logger.warning(f"Sync worker error: {exc}")
        time.sleep(60)


def start_sync_worker() -> None:
    logger.info("Starting Auto-Sync background worker...")
    t = threading.Thread(target=run_sync_worker, daemon=True, name="AutoSyncWorker")
    t.start()
