from __future__ import annotations

from netinventory.auth import load_or_create_shared_secret
from netinventory.collect.collector import collect_once
from netinventory.config import get_app_paths
from netinventory.export import write_export_bundle
from netinventory.service import run_service
from netinventory.storage.db import Database


def handle_status() -> int:
    paths = get_app_paths()
    db = Database(paths)
    secret = load_or_create_shared_secret(paths)
    status = db.get_status()

    print(f"db_path: {status.db_path}")
    print(f"device_id: {status.device_id}")
    print(f"schema_version: {status.schema_version}")
    print(f"networks: {status.network_count}")
    print(f"observations: {status.observation_count}")
    print(f"active_network: {status.active_network_id or 'none'}")
    print(f"secret_path: {paths.secret_path}")
    print(f"secret_fingerprint: {secret[:6]}...{secret[-4:]}")
    return 0


def handle_current() -> int:
    db = Database(get_app_paths())
    current = db.get_current_network()
    if current is None:
        print("current network: none")
        return 0

    print(f"network_id: {current.network_id}")
    print(f"display_name: {current.display_name or '-'}")
    print(f"seen_count: {current.seen_count}")
    print(f"confidence: {current.confidence:.2f}")
    print(f"first_seen: {current.first_seen or '-'}")
    print(f"last_seen: {current.last_seen or '-'}")
    if current.notes:
        print(f"notes: {current.notes}")
    return 0


def handle_networks() -> int:
    db = Database(get_app_paths())
    networks = db.list_networks()
    if not networks:
        print("known networks: none")
        return 0

    for network in networks:
        name = network.display_name or "-"
        first_seen = network.first_seen or "-"
        last_seen = network.last_seen or "-"
        print(
            f"{network.network_id}  "
            f"seen={network.seen_count}  "
            f"confidence={network.confidence:.2f}  "
            f"first={first_seen}  "
            f"last={last_seen}  "
            f"name={name}"
        )
    return 0


def handle_serve(bind: str) -> int:
    return run_service(bind)


def handle_export(output_path: str | None) -> int:
    bundle = write_export_bundle(output_path)
    print(bundle)
    return 0


def handle_collect_once() -> int:
    db = Database(get_app_paths())
    observation = collect_once()
    db.record_observation(observation)

    print(f"observation_id: {observation.observation_id}")
    print(f"observed_at: {observation.observed_at}")
    print(f"network_id: {observation.network_id}")
    print(f"kind: {observation.kind}")
    return 0
