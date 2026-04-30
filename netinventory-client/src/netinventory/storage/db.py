from __future__ import annotations

import json
import sqlite3
import uuid
from contextlib import contextmanager

from netinventory.collect.collector import CollectedObservation
from netinventory.config import AppPaths
from netinventory.core.context import UserContextRecord
from netinventory.core.models import NetworkSummary, ObservationIngestResult, StatusSnapshot
from netinventory.core.tasks import TaskDefinition, TaskRunRecord

SCHEMA_VERSION = 1


class Database:
    def __init__(self, paths: AppPaths):
        self.paths = paths

    def initialize(self) -> None:
        self.paths.root.mkdir(parents=True, exist_ok=True)
        self.paths.evidence_dir.mkdir(parents=True, exist_ok=True)
        self.paths.state_dir.mkdir(parents=True, exist_ok=True)

        with self.connect() as conn:
            conn.executescript(
                """
                PRAGMA journal_mode=WAL;

                CREATE TABLE IF NOT EXISTS app_meta (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS network_summaries (
                    network_id TEXT PRIMARY KEY,
                    first_seen TEXT,
                    last_seen TEXT,
                    seen_count INTEGER NOT NULL DEFAULT 0,
                    confidence REAL NOT NULL DEFAULT 0.0,
                    display_name TEXT,
                    notes TEXT
                );

                CREATE TABLE IF NOT EXISTS observations (
                    observation_id TEXT PRIMARY KEY,
                    observed_at TEXT NOT NULL,
                    device_id TEXT NOT NULL,
                    network_id TEXT,
                    kind TEXT NOT NULL,
                    material_fingerprint TEXT,
                    facts_json TEXT,
                    summary TEXT,
                    evidence_path TEXT,
                    FOREIGN KEY(network_id) REFERENCES network_summaries(network_id)
                );

                CREATE TABLE IF NOT EXISTS app_state (
                    key TEXT PRIMARY KEY,
                    value TEXT
                );

                CREATE TABLE IF NOT EXISTS task_definitions (
                    task_id TEXT PRIMARY KEY,
                    task_class TEXT NOT NULL,
                    description TEXT NOT NULL,
                    triggers_json TEXT NOT NULL,
                    expected_cost TEXT NOT NULL,
                    long_running INTEGER NOT NULL DEFAULT 0
                );

                CREATE TABLE IF NOT EXISTS task_runs (
                    run_id TEXT PRIMARY KEY,
                    source_device_id TEXT,
                    task_id TEXT NOT NULL,
                    trigger TEXT NOT NULL,
                    state TEXT NOT NULL,
                    started_at TEXT NOT NULL,
                    finished_at TEXT,
                    detail TEXT,
                    FOREIGN KEY(task_id) REFERENCES task_definitions(task_id)
                );

                CREATE TABLE IF NOT EXISTS user_context (
                    context_id TEXT PRIMARY KEY,
                    created_at TEXT NOT NULL,
                    source_device_id TEXT,
                    entity_kind TEXT NOT NULL,
                    entity_id TEXT NOT NULL,
                    field TEXT NOT NULL,
                    value TEXT NOT NULL,
                    source TEXT NOT NULL
                );
                """
            )
            conn.execute(
                "INSERT OR REPLACE INTO app_meta(key, value) VALUES('schema_version', ?)",
                (str(SCHEMA_VERSION),),
            )
            conn.execute(
                "INSERT OR IGNORE INTO app_meta(key, value) VALUES('device_id', ?)",
                (str(uuid.uuid4()),),
            )
            _ensure_column(conn, "observations", "material_fingerprint", "TEXT")
            _ensure_column(conn, "observations", "facts_json", "TEXT")
            _ensure_column(conn, "task_runs", "source_device_id", "TEXT")
            _ensure_column(conn, "user_context", "source_device_id", "TEXT")

    @contextmanager
    def connect(self):
        conn = sqlite3.connect(self.paths.db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def get_status(self) -> StatusSnapshot:
        self.initialize()
        with self.connect() as conn:
            device_id = _scalar(conn, "SELECT value FROM app_meta WHERE key = 'device_id'")
            schema_version = int(
                _scalar(conn, "SELECT value FROM app_meta WHERE key = 'schema_version'") or SCHEMA_VERSION
            )
            network_count = int(_scalar(conn, "SELECT COUNT(*) FROM network_summaries") or 0)
            observation_count = int(_scalar(conn, "SELECT COUNT(*) FROM observations") or 0)
            active_network_id = _scalar(conn, "SELECT value FROM app_state WHERE key = 'active_network_id'")

        return StatusSnapshot(
            db_path=str(self.paths.db_path),
            device_id=device_id or "unknown",
            schema_version=schema_version,
            network_count=network_count,
            observation_count=observation_count,
            active_network_id=active_network_id,
        )

    def get_current_network(self) -> NetworkSummary | None:
        self.initialize()
        with self.connect() as conn:
            active_network_id = _scalar(conn, "SELECT value FROM app_state WHERE key = 'active_network_id'")
            if not active_network_id:
                return None

            row = conn.execute(
                """
                SELECT network_id, first_seen, last_seen, seen_count, confidence, display_name, notes
                FROM network_summaries
                WHERE network_id = ?
                """,
                (active_network_id,),
            ).fetchone()
            return _row_to_summary(row)

    def get_latest_observation(self, network_id: str | None = None) -> dict[str, object] | None:
        self.initialize()
        with self.connect() as conn:
            if network_id is None:
                row = conn.execute(
                    """
                    SELECT observation_id, observed_at, device_id, network_id, kind, material_fingerprint, facts_json, summary
                    FROM observations
                    ORDER BY observed_at DESC, observation_id DESC
                    LIMIT 1
                    """
                ).fetchone()
            else:
                row = conn.execute(
                    """
                    SELECT observation_id, observed_at, device_id, network_id, kind, material_fingerprint, facts_json, summary
                    FROM observations
                    WHERE network_id = ?
                    ORDER BY observed_at DESC, observation_id DESC
                    LIMIT 1
                    """,
                    (network_id,),
                ).fetchone()

        if row is None:
            return None

        item = dict(row)
        facts_json = item.get("facts_json")
        item["facts"] = _json_loads(facts_json) if isinstance(facts_json, str) and facts_json else {}
        return item

    def list_networks(self) -> list[NetworkSummary]:
        self.initialize()
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT network_id, first_seen, last_seen, seen_count, confidence, display_name, notes
                FROM network_summaries
                ORDER BY last_seen DESC, seen_count DESC, network_id ASC
                """
            ).fetchall()
            return [_row_to_summary(row) for row in rows if row is not None]

    def export_bundle_data(self, since_iso: str | None = None) -> dict[str, object]:
        self.initialize()
        with self.connect() as conn:
            source_device_id = _scalar(conn, "SELECT value FROM app_meta WHERE key = 'device_id'") or "unknown"
            app_meta = {
                row["key"]: row["value"]
                for row in conn.execute("SELECT key, value FROM app_meta ORDER BY key ASC").fetchall()
            }
            records = self._export_replication_records(conn, since_iso=since_iso)

        return {
            "format": "netinventory-sync-export",
            "schema_version": SCHEMA_VERSION,
            "source_device_id": source_device_id,
            "app_meta": app_meta,
            "records": records,
        }

    def record_observation(self, observation: CollectedObservation) -> ObservationIngestResult:
        self.initialize()
        with self.connect() as conn:
            device_id = _scalar(conn, "SELECT value FROM app_meta WHERE key = 'device_id'") or "unknown"
            active_network_id = _scalar(conn, "SELECT value FROM app_state WHERE key = 'active_network_id'")
            previous = conn.execute(
                """
                SELECT network_id, kind, material_fingerprint
                FROM observations
                ORDER BY observed_at DESC, observation_id DESC
                LIMIT 1
                """
            ).fetchone()
            facts_json = json.dumps(observation.facts, sort_keys=True)
            same_as_previous = (
                previous is not None
                and previous["network_id"] == observation.network_id
                and previous["kind"] == observation.kind
                and previous["material_fingerprint"] == observation.material_fingerprint
            )
            active_network_changed = active_network_id != observation.network_id
            material_change = active_network_changed or not same_as_previous

            if not material_change:
                return ObservationIngestResult(
                    observation_id=observation.observation_id,
                    network_id=observation.network_id,
                    stored=False,
                    material_change=False,
                    active_network_changed=False,
                    reason="suppressed duplicate observation",
                )

            conn.execute(
                """
                INSERT INTO observations(
                    observation_id,
                    observed_at,
                    device_id,
                    network_id,
                    kind,
                    material_fingerprint,
                    facts_json,
                    summary,
                    evidence_path
                ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, NULL)
                """,
                (
                    observation.observation_id,
                    observation.observed_at,
                    device_id,
                    observation.network_id,
                    observation.kind,
                    observation.material_fingerprint,
                    facts_json,
                    observation.summary,
                ),
            )
            conn.execute(
                """
                INSERT INTO network_summaries(
                    network_id,
                    first_seen,
                    last_seen,
                    seen_count,
                    confidence,
                    display_name,
                    notes
                ) VALUES(?, ?, ?, 1, ?, ?, NULL)
                ON CONFLICT(network_id) DO UPDATE SET
                    last_seen = excluded.last_seen,
                    seen_count = network_summaries.seen_count + 1,
                    confidence = MAX(network_summaries.confidence, excluded.confidence),
                    display_name = COALESCE(network_summaries.display_name, excluded.display_name)
                """,
                (
                    observation.network_id,
                    observation.observed_at,
                    observation.observed_at,
                    observation.confidence,
                    observation.display_name,
                ),
            )
            conn.execute(
                """
                INSERT INTO app_state(key, value) VALUES('active_network_id', ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value
                """,
                (observation.network_id,),
            )
            conn.execute(
                """
                INSERT INTO app_state(key, value) VALUES('last_material_change_at', ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value
                """,
                (observation.observed_at,),
            )
            return ObservationIngestResult(
                observation_id=observation.observation_id,
                network_id=observation.network_id,
                stored=True,
                material_change=True,
                active_network_changed=active_network_changed,
                reason="stored material network observation",
            )

    def upsert_task_definitions(self, definitions: list[TaskDefinition]) -> None:
        self.initialize()
        with self.connect() as conn:
            for definition in definitions:
                conn.execute(
                    """
                    INSERT INTO task_definitions(
                        task_id,
                        task_class,
                        description,
                        triggers_json,
                        expected_cost,
                        long_running
                    ) VALUES(?, ?, ?, ?, ?, ?)
                    ON CONFLICT(task_id) DO UPDATE SET
                        task_class = excluded.task_class,
                        description = excluded.description,
                        triggers_json = excluded.triggers_json,
                        expected_cost = excluded.expected_cost,
                        long_running = excluded.long_running
                    """,
                    (
                        definition.task_id,
                        definition.task_class.value,
                        definition.description,
                        _json_dumps([trigger.value for trigger in definition.triggers]),
                        definition.expected_cost,
                        1 if definition.long_running else 0,
                    ),
                )

    def record_task_run(self, run: TaskRunRecord) -> None:
        self.initialize()
        with self.connect() as conn:
            source_device_id = _scalar(conn, "SELECT value FROM app_meta WHERE key = 'device_id'") or "unknown"
            conn.execute(
                """
                INSERT INTO task_runs(
                    run_id,
                    source_device_id,
                    task_id,
                    trigger,
                    state,
                    started_at,
                    finished_at,
                    detail
                ) VALUES(?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(run_id) DO UPDATE SET
                    source_device_id = COALESCE(task_runs.source_device_id, excluded.source_device_id),
                    state = excluded.state,
                    finished_at = excluded.finished_at,
                    detail = excluded.detail
                """,
                (
                    run.run_id,
                    source_device_id,
                    run.task_id,
                    run.trigger.value,
                    run.state.value,
                    run.started_at,
                    run.finished_at,
                    run.detail,
                ),
            )

    def list_recent_task_runs(self, limit: int = 20) -> list[dict[str, object]]:
        self.initialize()
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT run_id, source_device_id, task_id, trigger, state, started_at, finished_at, detail
                FROM task_runs
                ORDER BY started_at DESC, run_id DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
            return [dict(row) for row in rows]

    def list_task_definitions(self) -> list[dict[str, object]]:
        self.initialize()
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT task_id, task_class, description, triggers_json, expected_cost, long_running
                FROM task_definitions
                ORDER BY task_id ASC
                """
            ).fetchall()
            results: list[dict[str, object]] = []
            for row in rows:
                item = dict(row)
                item["triggers"] = _json_loads(item.pop("triggers_json"))
                item["long_running"] = bool(item["long_running"])
                results.append(item)
            return results

    def add_user_context(self, record: UserContextRecord) -> None:
        self.initialize()
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO user_context(
                    context_id,
                    created_at,
                    source_device_id,
                    entity_kind,
                    entity_id,
                    field,
                    value,
                    source
                ) VALUES(?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.context_id,
                    record.created_at,
                    _scalar(conn, "SELECT value FROM app_meta WHERE key = 'device_id'") or "unknown",
                    record.entity_kind,
                    record.entity_id,
                    record.field,
                    record.value,
                    record.source,
                ),
            )

    def list_user_context(self, entity_kind: str | None = None, entity_id: str | None = None) -> list[dict[str, object]]:
        self.initialize()
        with self.connect() as conn:
            query = """
                SELECT context_id, created_at, source_device_id, entity_kind, entity_id, field, value, source
                FROM user_context
            """
            clauses: list[str] = []
            params: list[object] = []
            if entity_kind is not None:
                clauses.append("entity_kind = ?")
                params.append(entity_kind)
            if entity_id is not None:
                clauses.append("entity_id = ?")
                params.append(entity_id)
            if clauses:
                query += " WHERE " + " AND ".join(clauses)
            query += " ORDER BY created_at DESC, context_id DESC"
            rows = conn.execute(query, tuple(params)).fetchall()
            return [dict(row) for row in rows]

    def get_last_sync_time(self) -> str | None:
        self.initialize()
        with self.connect() as conn:
            return _scalar(conn, "SELECT value FROM app_state WHERE key = 'last_sync_time'")

    def set_last_sync_time(self, iso_string: str) -> None:
        self.initialize()
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO app_state(key, value) VALUES('last_sync_time', ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value
                """,
                (iso_string,),
            )

    def get_app_state(self, key: str) -> str | None:
        self.initialize()
        with self.connect() as conn:
            row = conn.execute("SELECT value FROM app_state WHERE key = ?", (key,)).fetchone()
            return row["value"] if row else None

    def set_app_state(self, key: str, value: str | None) -> None:
        self.initialize()
        with self.connect() as conn:
            if value is None:
                conn.execute("DELETE FROM app_state WHERE key = ?", (key,))
                return
            conn.execute(
                """
                INSERT INTO app_state(key, value) VALUES(?, ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value
                """,
                (key, value),
            )

    def get_app_state_many(self, prefix: str) -> dict[str, str]:
        self.initialize()
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT key, value FROM app_state WHERE key LIKE ?", (f"{prefix}%",)
            ).fetchall()
            return {row["key"]: row["value"] for row in rows}

    def import_bundle_data(self, bundle: dict[str, object]) -> dict[str, int]:
        self.initialize()
        records = bundle.get("records")
        if isinstance(records, list):
            return self._import_replication_records(records)
        return self._import_legacy_bundle(bundle)

    def _export_replication_records(self, conn: sqlite3.Connection, since_iso: str | None = None) -> list[dict[str, object]]:
        records: list[dict[str, object]] = []

        if since_iso:
            observation_rows = conn.execute(
                """
                SELECT observation_id, observed_at, device_id, network_id, kind, material_fingerprint, facts_json, summary, evidence_path
                FROM observations
                WHERE observed_at > ?
                ORDER BY observed_at ASC, observation_id ASC
                """,
                (since_iso,)
            ).fetchall()
        else:
            observation_rows = conn.execute(
                """
                SELECT observation_id, observed_at, device_id, network_id, kind, material_fingerprint, facts_json, summary, evidence_path
                FROM observations
                ORDER BY observed_at ASC, observation_id ASC
                """
            ).fetchall()
        for row in observation_rows:
            item = dict(row)
            facts = _json_loads(item["facts_json"]) if item.get("facts_json") else {}
            records.append(
                {
                    "record_id": f"observation:{item['observation_id']}",
                    "record_type": "observation",
                    "source_device_id": item["device_id"],
                    "observed_at": item["observed_at"],
                    "created_at": item["observed_at"],
                    "entity_scope": {"network_id": item["network_id"]},
                    "payload": {
                        **item,
                        "display_name": _observation_display_name(item["network_id"], facts),
                        "confidence": _observation_confidence(item["kind"]),
                    },
                }
            )

        if since_iso:
            task_rows = conn.execute(
                """
                SELECT run_id, source_device_id, task_id, trigger, state, started_at, finished_at, detail
                FROM task_runs
                WHERE started_at > ?
                ORDER BY started_at ASC, run_id ASC
                """,
                (since_iso,)
            ).fetchall()
        else:
            task_rows = conn.execute(
                """
                SELECT run_id, source_device_id, task_id, trigger, state, started_at, finished_at, detail
                FROM task_runs
                ORDER BY started_at ASC, run_id ASC
                """
            ).fetchall()
        for row in task_rows:
            item = dict(row)
            records.append(
                {
                    "record_id": f"task_run:{item['run_id']}",
                    "record_type": "task_run",
                    "source_device_id": item["source_device_id"] or "unknown",
                    "observed_at": item["started_at"],
                    "created_at": item["started_at"],
                    "entity_scope": {"task_id": item["task_id"]},
                    "payload": item,
                }
            )

        if since_iso:
            context_rows = conn.execute(
                """
                SELECT context_id, created_at, source_device_id, entity_kind, entity_id, field, value, source
                FROM user_context
                WHERE created_at > ?
                ORDER BY created_at ASC, context_id ASC
                """,
                (since_iso,)
            ).fetchall()
        else:
            context_rows = conn.execute(
                """
                SELECT context_id, created_at, source_device_id, entity_kind, entity_id, field, value, source
                FROM user_context
                ORDER BY created_at ASC, context_id ASC
                """
            ).fetchall()
        for row in context_rows:
            item = dict(row)
            records.append(
                {
                    "record_id": f"user_context:{item['context_id']}",
                    "record_type": "user_context",
                    "source_device_id": item["source_device_id"] or "unknown",
                    "observed_at": item["created_at"],
                    "created_at": item["created_at"],
                    "entity_scope": {
                        "entity_kind": item["entity_kind"],
                        "entity_id": item["entity_id"],
                    },
                    "payload": item,
                }
            )

        return records

    def _import_replication_records(self, records: list[object]) -> dict[str, int]:
        summary = {
            "records_seen": 0,
            "observations_imported": 0,
            "task_runs_imported": 0,
            "user_context_imported": 0,
            "records_skipped": 0,
        }
        with self.connect() as conn:
            for raw in records:
                if not isinstance(raw, dict):
                    summary["records_skipped"] += 1
                    continue
                summary["records_seen"] += 1
                record_type = raw.get("record_type")
                payload = raw.get("payload")
                if not isinstance(payload, dict):
                    summary["records_skipped"] += 1
                    continue
                if record_type == "observation":
                    inserted = self._import_observation_payload(conn, payload)
                    summary["observations_imported"] += 1 if inserted else 0
                    summary["records_skipped"] += 0 if inserted else 1
                    continue
                if record_type == "task_run":
                    inserted = self._import_task_run_payload(conn, payload)
                    summary["task_runs_imported"] += 1 if inserted else 0
                    summary["records_skipped"] += 0 if inserted else 1
                    continue
                if record_type == "user_context":
                    inserted = self._import_user_context_payload(conn, payload)
                    summary["user_context_imported"] += 1 if inserted else 0
                    summary["records_skipped"] += 0 if inserted else 1
                    continue
                summary["records_skipped"] += 1
        return summary

    def _import_legacy_bundle(self, bundle: dict[str, object]) -> dict[str, int]:
        records: list[dict[str, object]] = []
        for item in bundle.get("observations", []):
            if isinstance(item, dict):
                records.append({"record_type": "observation", "payload": item})
        for item in bundle.get("user_context", []):
            if isinstance(item, dict):
                records.append({"record_type": "user_context", "payload": item})
        return self._import_replication_records(records)

    def _import_observation_payload(self, conn: sqlite3.Connection, payload: dict[str, object]) -> bool:
        cursor = conn.execute(
            """
            INSERT OR IGNORE INTO observations(
                observation_id,
                observed_at,
                device_id,
                network_id,
                kind,
                material_fingerprint,
                facts_json,
                summary,
                evidence_path
            ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                payload.get("observation_id"),
                payload.get("observed_at"),
                payload.get("device_id"),
                payload.get("network_id"),
                payload.get("kind"),
                payload.get("material_fingerprint"),
                payload.get("facts_json"),
                payload.get("summary"),
                payload.get("evidence_path"),
            ),
        )
        if cursor.rowcount == 0:
            return False

        facts = _json_loads(payload["facts_json"]) if payload.get("facts_json") else {}
        conn.execute(
            """
            INSERT INTO network_summaries(
                network_id,
                first_seen,
                last_seen,
                seen_count,
                confidence,
                display_name,
                notes
            ) VALUES(?, ?, ?, 1, ?, ?, NULL)
            ON CONFLICT(network_id) DO UPDATE SET
                first_seen = CASE
                    WHEN network_summaries.first_seen IS NULL THEN excluded.first_seen
                    WHEN excluded.first_seen < network_summaries.first_seen THEN excluded.first_seen
                    ELSE network_summaries.first_seen
                END,
                last_seen = CASE
                    WHEN network_summaries.last_seen IS NULL THEN excluded.last_seen
                    WHEN excluded.last_seen > network_summaries.last_seen THEN excluded.last_seen
                    ELSE network_summaries.last_seen
                END,
                seen_count = network_summaries.seen_count + 1,
                confidence = MAX(network_summaries.confidence, excluded.confidence),
                display_name = COALESCE(network_summaries.display_name, excluded.display_name)
            """,
            (
                payload.get("network_id"),
                payload.get("observed_at"),
                payload.get("observed_at"),
                payload.get("confidence") or _observation_confidence(str(payload.get("kind") or "")),
                payload.get("display_name") or _observation_display_name(str(payload.get("network_id") or "unknown"), facts),
            ),
        )
        return True

    def _import_task_run_payload(self, conn: sqlite3.Connection, payload: dict[str, object]) -> bool:
        cursor = conn.execute(
            """
            INSERT OR IGNORE INTO task_runs(
                run_id,
                source_device_id,
                task_id,
                trigger,
                state,
                started_at,
                finished_at,
                detail
            ) VALUES(?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                payload.get("run_id"),
                payload.get("source_device_id"),
                payload.get("task_id"),
                payload.get("trigger"),
                payload.get("state"),
                payload.get("started_at"),
                payload.get("finished_at"),
                payload.get("detail"),
            ),
        )
        return cursor.rowcount > 0

    def _import_user_context_payload(self, conn: sqlite3.Connection, payload: dict[str, object]) -> bool:
        cursor = conn.execute(
            """
            INSERT OR IGNORE INTO user_context(
                context_id,
                created_at,
                source_device_id,
                entity_kind,
                entity_id,
                field,
                value,
                source
            ) VALUES(?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                payload.get("context_id"),
                payload.get("created_at"),
                payload.get("source_device_id"),
                payload.get("entity_kind"),
                payload.get("entity_id"),
                payload.get("field"),
                payload.get("value"),
                payload.get("source"),
            ),
        )
        return cursor.rowcount > 0


def _scalar(conn: sqlite3.Connection, query: str) -> str | None:
    row = conn.execute(query).fetchone()
    if row is None:
        return None
    return row[0]


def _row_to_summary(row: sqlite3.Row | None) -> NetworkSummary | None:
    if row is None:
        return None
    return NetworkSummary(
        network_id=row["network_id"],
        first_seen=row["first_seen"],
        last_seen=row["last_seen"],
        seen_count=row["seen_count"],
        confidence=row["confidence"],
        display_name=row["display_name"],
        notes=row["notes"],
    )


def _observation_display_name(network_id: str | None, facts: object) -> str:
    if isinstance(facts, dict):
        primary_ip = facts.get("primary_ip")
        if isinstance(primary_ip, str) and primary_ip:
            return primary_ip
        hostname = facts.get("hostname")
        if isinstance(hostname, str) and hostname:
            return hostname
    return network_id or "unknown"


def _observation_confidence(kind: str) -> float:
    if kind == "local_probe":
        return 0.20
    return 0.0


def _json_dumps(value: object) -> str:
    return json.dumps(value, sort_keys=True)


def _json_loads(value: str) -> object:
    return json.loads(value)


def _ensure_column(conn: sqlite3.Connection, table_name: str, column_name: str, column_type: str) -> None:
    rows = conn.execute(f"PRAGMA table_info({table_name})").fetchall()
    existing = {row[1] for row in rows}
    if column_name in existing:
        return
    conn.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_type}")
