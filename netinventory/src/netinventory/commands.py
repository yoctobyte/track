from __future__ import annotations

from netinventory.auth import load_or_create_shared_secret
from netinventory.config import get_app_paths
from netinventory.context import add_user_context
from netinventory.export import import_export_bundle, write_export_bundle
from netinventory.service import run_service
from netinventory.storage.db import Database
from netinventory.tasks import list_task_definitions, run_task_once
from netinventory.core.tasks import TaskTrigger


def handle_status() -> int:
    paths = get_app_paths()
    db = Database(paths)
    secret = load_or_create_shared_secret(paths)
    db.upsert_task_definitions(list_task_definitions())
    status = db.get_status()
    task_count = len(db.list_task_definitions())

    print(f"db_path: {status.db_path}")
    print(f"device_id: {status.device_id}")
    print(f"schema_version: {status.schema_version}")
    print(f"networks: {status.network_count}")
    print(f"observations: {status.observation_count}")
    print(f"active_network: {status.active_network_id or 'none'}")
    print(f"task_definitions: {task_count}")
    print(f"secret_path: {paths.secret_path}")
    print(f"secret_fingerprint: {secret[:6]}...{secret[-4:]}")
    return 0


def handle_current() -> int:
    db = Database(get_app_paths())
    current = db.get_current_network()
    if current is None:
        print("current network: none")
        return 0
    observation = db.get_latest_observation(current.network_id)
    facts = observation.get("facts", {}) if observation is not None else {}

    print(f"network_id: {current.network_id}")
    print(f"display_name: {current.display_name or '-'}")
    print(f"seen_count: {current.seen_count}")
    print(f"confidence: {current.confidence:.2f}")
    print(f"first_seen: {current.first_seen or '-'}")
    print(f"last_seen: {current.last_seen or '-'}")
    if observation is not None:
        print(f"observed_at: {observation['observed_at']}")
        print(f"kind: {observation['kind']}")
    print(f"primary_ip: {facts.get('primary_ip') or '-'}")
    print(f"default_gateway: {facts.get('default_gateway') or '-'}")
    print(f"default_route_interface: {facts.get('default_route_interface') or '-'}")
    print(f"dns_servers: {', '.join(facts.get('dns_servers', [])) or '-'}")
    print(f"search_domains: {', '.join(facts.get('search_domains', [])) or '-'}")
    print(f"active_interfaces: {', '.join(facts.get('active_interfaces', [])) or '-'}")
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
    db = Database(get_app_paths())
    db.upsert_task_definitions(list_task_definitions())
    return run_service(bind)


def handle_export(output_path: str | None) -> int:
    bundle = write_export_bundle(output_path)
    print(bundle)
    return 0


def handle_import(input_path: str) -> int:
    result = import_export_bundle(input_path)
    print(f"records_seen: {result['records_seen']}")
    print(f"observations_imported: {result['observations_imported']}")
    print(f"task_runs_imported: {result['task_runs_imported']}")
    print(f"user_context_imported: {result['user_context_imported']}")
    print(f"records_skipped: {result['records_skipped']}")
    return 0


def handle_collect_once() -> int:
    db = Database(get_app_paths())
    db.upsert_task_definitions(list_task_definitions())
    run = run_task_once(db, "current_network_probe", TaskTrigger.MANUAL)

    print(f"task_run_id: {run.run_id}")
    print(f"task_id: {run.task_id}")
    print(f"state: {run.state.value}")
    print(f"started_at: {run.started_at}")
    if run.finished_at:
        print(f"finished_at: {run.finished_at}")
    if run.detail:
        print(f"detail: {run.detail}")
    return 0


def handle_recent() -> int:
    db = Database(get_app_paths())
    db.upsert_task_definitions(list_task_definitions())
    recent = db.list_recent_task_runs()
    if not recent:
        print("recent task runs: none")
        return 0

    for run in recent:
        print(
            f"{run['started_at']}  "
            f"source={run['source_device_id'] or '-'}  "
            f"{run['task_id']}  "
            f"trigger={run['trigger']}  "
            f"state={run['state']}  "
            f"detail={run['detail'] or '-'}"
        )
    return 0


def handle_annotate(entity_kind: str, entity_id: str, field: str, value: str) -> int:
    db = Database(get_app_paths())
    db.upsert_task_definitions(list_task_definitions())
    run = add_user_context(db, entity_kind=entity_kind, entity_id=entity_id, field=field, value=value)

    print(f"task_run_id: {run.run_id}")
    print(f"entity: {entity_kind}:{entity_id}")
    print(f"field: {field}")
    print(f"value: {value}")
    return 0


def handle_context(entity_kind: str | None, entity_id: str | None) -> int:
    db = Database(get_app_paths())
    rows = db.list_user_context(entity_kind=entity_kind, entity_id=entity_id)
    if not rows:
        print("user context: none")
        return 0

    for row in rows:
        print(
            f"{row['created_at']}  "
            f"source={row['source_device_id'] or '-'}  "
            f"{row['entity_kind']}:{row['entity_id']}  "
            f"{row['field']}={row['value']}"
        )
    return 0
