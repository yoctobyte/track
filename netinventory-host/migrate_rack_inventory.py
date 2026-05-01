#!/usr/bin/env python3
"""Migrate legacy rack-inventory/*.json blobs into the unified LocationDB.

Runs per environment under data/environments/<env>/. For each rack JSON,
calls the host's own save_rack_record() so migrated records are
indistinguishable from records created via the web form. Also surfaces
rack photos as media_records (target_type=cabinet) so other TRACK apps
can find them.

Idempotent — re-running only adds what's missing.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(APP_DIR))
sys.path.insert(0, str(APP_DIR.parent))


def list_environments() -> list[str]:
    base = APP_DIR / "data" / "environments"
    if not base.exists():
        return []
    return sorted(p.name for p in base.iterdir() if p.is_dir())


def migrate_environment(env: str) -> dict[str, int]:
    os.environ["NETINVENTORY_HOST_INSTANCE"] = env
    # Force fresh import paths for the host module so runtime_paths() picks
    # up the new env var on every call.
    for mod_name in list(sys.modules):
        if mod_name == "app" or mod_name.startswith("app."):
            del sys.modules[mod_name]

    from app import (  # type: ignore[import-not-found]
        get_location_db,
        runtime_paths,
        save_rack_record,
    )

    paths = runtime_paths()
    rack_dir = paths["rack_inventory"]
    if not rack_dir.exists():
        return {"racks_seen": 0, "racks_migrated": 0, "photos_linked": 0}

    db = get_location_db()
    counts = {"racks_seen": 0, "racks_migrated": 0, "photos_linked": 0}

    for rack_file in sorted(rack_dir.glob("*.json")):
        try:
            with rack_file.open(encoding="utf-8") as handle:
                record = json.load(handle)
        except (OSError, json.JSONDecodeError) as exc:
            print(f"  [skip] {rack_file.name}: {exc}")
            continue

        if not record.get("id"):
            record["id"] = rack_file.stem

        counts["racks_seen"] += 1
        save_rack_record(record)
        counts["racks_migrated"] += 1

        rack_id = record["id"]
        existing_media = {m.get("uri") for m in db.list_media_records(target_type="cabinet", target_id=rack_id)}
        for photo in record.get("photos") or []:
            filename = photo.get("filename")
            if not filename:
                continue
            uri = f"/rack-photos/{rack_id}/{filename}"
            if uri in existing_media:
                continue
            db.create_media_record(
                target_type="cabinet",
                target_id=rack_id,
                source_app="netinventory-host",
                uri=uri,
                mime_type="image/jpeg",
            )
            counts["photos_linked"] += 1

        print(f"  [ok] {record.get('name') or rack_id}")

    return counts


def main(argv: list[str]) -> int:
    if len(argv) > 1:
        envs = argv[1:]
    else:
        envs = list_environments()
        if not envs:
            print("No environments found under data/environments/")
            return 1

    print(f"Environments to process: {', '.join(envs)}")
    grand_total = {"racks_seen": 0, "racks_migrated": 0, "photos_linked": 0}
    for env in envs:
        print(f"\n=== {env} ===")
        result = migrate_environment(env)
        for key, value in result.items():
            grand_total[key] += value
        print(f"  → racks: {result['racks_migrated']}/{result['racks_seen']} migrated, photos linked: {result['photos_linked']}")

    print()
    print(f"Total: {grand_total['racks_migrated']} racks migrated, {grand_total['photos_linked']} photos linked.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
