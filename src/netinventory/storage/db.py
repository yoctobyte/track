from __future__ import annotations

import sqlite3
import uuid
from contextlib import contextmanager

from netinventory.collect.collector import CollectedObservation
from netinventory.config import AppPaths
from netinventory.core.models import NetworkSummary, StatusSnapshot

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
                    summary TEXT,
                    evidence_path TEXT,
                    FOREIGN KEY(network_id) REFERENCES network_summaries(network_id)
                );

                CREATE TABLE IF NOT EXISTS app_state (
                    key TEXT PRIMARY KEY,
                    value TEXT
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

    def export_bundle_data(self) -> dict[str, object]:
        self.initialize()
        with self.connect() as conn:
            app_meta = {
                row["key"]: row["value"]
                for row in conn.execute("SELECT key, value FROM app_meta ORDER BY key ASC").fetchall()
            }
            app_state = {
                row["key"]: row["value"]
                for row in conn.execute("SELECT key, value FROM app_state ORDER BY key ASC").fetchall()
            }
            network_summaries = [
                dict(row)
                for row in conn.execute(
                    """
                    SELECT network_id, first_seen, last_seen, seen_count, confidence, display_name, notes
                    FROM network_summaries
                    ORDER BY last_seen DESC, seen_count DESC, network_id ASC
                    """
                ).fetchall()
            ]
            observations = [
                dict(row)
                for row in conn.execute(
                    """
                    SELECT observation_id, observed_at, device_id, network_id, kind, summary, evidence_path
                    FROM observations
                    ORDER BY observed_at DESC, observation_id DESC
                    """
                ).fetchall()
            ]

        return {
            "format": "netinventory-export",
            "schema_version": SCHEMA_VERSION,
            "app_meta": app_meta,
            "app_state": app_state,
            "network_summaries": network_summaries,
            "observations": observations,
        }

    def record_observation(self, observation: CollectedObservation) -> None:
        self.initialize()
        with self.connect() as conn:
            device_id = _scalar(conn, "SELECT value FROM app_meta WHERE key = 'device_id'") or "unknown"
            conn.execute(
                """
                INSERT INTO observations(
                    observation_id,
                    observed_at,
                    device_id,
                    network_id,
                    kind,
                    summary,
                    evidence_path
                ) VALUES(?, ?, ?, ?, ?, ?, NULL)
                """,
                (
                    observation.observation_id,
                    observation.observed_at,
                    device_id,
                    observation.network_id,
                    observation.kind,
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
