import sqlite3
import uuid
from pathlib import Path
from contextlib import contextmanager
from typing import Any, Dict, List, Optional
from datetime import datetime, timezone

SCHEMA_VERSION = 1

class SchemaVersionError(Exception):
    pass

class LocationDB:
    def __init__(self, db_path: Path | str):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.initialize()

    @contextmanager
    def connect(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def initialize(self) -> None:
        with self.connect() as conn:
            conn.executescript(
                """
                PRAGMA journal_mode=WAL;
                PRAGMA foreign_keys=ON;

                CREATE TABLE IF NOT EXISTS meta (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS buildings (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    description TEXT,
                    latitude REAL,
                    longitude REAL,
                    extra_data TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS locations (
                    id TEXT PRIMARY KEY,
                    building_id TEXT NOT NULL,
                    parent_id TEXT,
                    name TEXT NOT NULL,
                    type TEXT NOT NULL,
                    notes TEXT,
                    extra_data TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY(building_id) REFERENCES buildings(id) ON DELETE CASCADE,
                    FOREIGN KEY(parent_id) REFERENCES locations(id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS cabinets (
                    id TEXT PRIMARY KEY,
                    location_id TEXT NOT NULL,
                    name TEXT NOT NULL,
                    u_size INTEGER,
                    notes TEXT,
                    extra_data TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY(location_id) REFERENCES locations(id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS devices (
                    id TEXT PRIMARY KEY,
                    cabinet_id TEXT,
                    location_id TEXT,
                    name TEXT NOT NULL,
                    kind TEXT,
                    brand TEXT,
                    model TEXT,
                    port_count INTEGER,
                    unit_size INTEGER,
                    u_position INTEGER,
                    notes TEXT,
                    extra_data TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY(cabinet_id) REFERENCES cabinets(id) ON DELETE SET NULL,
                    FOREIGN KEY(location_id) REFERENCES locations(id) ON DELETE SET NULL
                );

                CREATE TABLE IF NOT EXISTS device_ports (
                    id TEXT PRIMARY KEY,
                    device_id TEXT NOT NULL,
                    name TEXT NOT NULL,
                    status TEXT,
                    notes TEXT,
                    FOREIGN KEY(device_id) REFERENCES devices(id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS media_records (
                    id TEXT PRIMARY KEY,
                    target_type TEXT NOT NULL, -- 'building', 'location', 'cabinet', 'device'
                    target_id TEXT NOT NULL,
                    source_app TEXT NOT NULL,
                    uri TEXT NOT NULL,
                    mime_type TEXT,
                    timestamp TEXT NOT NULL
                );
                """
            )
            
            # Check schema version
            cursor = conn.execute("SELECT value FROM meta WHERE key='schema_version'")
            row = cursor.fetchone()
            if row is None:
                conn.execute("INSERT INTO meta (key, value) VALUES ('schema_version', ?)", (str(SCHEMA_VERSION),))
            else:
                version = int(row['value'])
                if version > SCHEMA_VERSION:
                    raise SchemaVersionError(f"Database schema version {version} is newer than application version {SCHEMA_VERSION}")

    def _now(self) -> str:
        return datetime.now(timezone.utc).isoformat()

    def _uuid(self) -> str:
        return uuid.uuid4().hex

    def create_building(self, name: str, description: str = "", latitude: float = None, longitude: float = None, extra_data: dict = None, id: str = None) -> dict:
        b_id = id or self._uuid()
        now = self._now()
        extra_str = json.dumps(extra_data) if extra_data else None
        with self.connect() as conn:
            conn.execute(
                "INSERT INTO buildings (id, name, description, latitude, longitude, extra_data, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (b_id, name, description, latitude, longitude, extra_str, now, now)
            )
        return self.get_building(b_id)
        
    def get_building(self, b_id: str) -> Optional[dict]:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM buildings WHERE id = ?", (b_id,)).fetchone()
            return dict(row) if row else None
            
    def list_buildings(self) -> List[dict]:
        with self.connect() as conn:
            return [dict(row) for row in conn.execute("SELECT * FROM buildings ORDER BY name").fetchall()]
            
    def update_building(self, b_id: str, **kwargs) -> dict:
        now = self._now()
        kwargs['updated_at'] = now
        sets = ", ".join(f"{k} = ?" for k in kwargs.keys())
        values = list(kwargs.values()) + [b_id]
        with self.connect() as conn:
            conn.execute(f"UPDATE buildings SET {sets} WHERE id = ?", values)
        return self.get_building(b_id)

    def create_location(self, building_id: str, name: str, type: str = "room", parent_id: str = None, notes: str = "", extra_data: dict = None, id: str = None) -> dict:
        l_id = id or self._uuid()
        now = self._now()
        extra_str = json.dumps(extra_data) if extra_data else None
        with self.connect() as conn:
            conn.execute(
                "INSERT INTO locations (id, building_id, parent_id, name, type, notes, extra_data, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (l_id, building_id, parent_id, name, type, notes, extra_str, now, now)
            )
        return self.get_location(l_id)
        
    def get_location(self, l_id: str) -> Optional[dict]:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM locations WHERE id = ?", (l_id,)).fetchone()
            return dict(row) if row else None
            
    def list_locations(self, building_id: str = None) -> List[dict]:
        with self.connect() as conn:
            if building_id:
                rows = conn.execute("SELECT * FROM locations WHERE building_id = ? ORDER BY name", (building_id,)).fetchall()
            else:
                rows = conn.execute("SELECT * FROM locations ORDER BY name").fetchall()
            return [dict(row) for row in rows]

    def update_location(self, l_id: str, **kwargs) -> dict:
        now = self._now()
        kwargs['updated_at'] = now
        sets = ", ".join(f"{k} = ?" for k in kwargs.keys())
        values = list(kwargs.values()) + [l_id]
        with self.connect() as conn:
            conn.execute(f"UPDATE locations SET {sets} WHERE id = ?", values)
        return self.get_location(l_id)

    def create_cabinet(self, location_id: str, name: str, u_size: int = None, notes: str = "", extra_data: dict = None, id: str = None) -> dict:
        c_id = id or self._uuid()
        now = self._now()
        extra_str = json.dumps(extra_data) if extra_data else None
        with self.connect() as conn:
            conn.execute(
                "INSERT INTO cabinets (id, location_id, name, u_size, notes, extra_data, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (c_id, location_id, name, u_size, notes, extra_str, now, now)
            )
        return self.get_cabinet(c_id)
        
    def get_cabinet(self, c_id: str) -> Optional[dict]:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM cabinets WHERE id = ?", (c_id,)).fetchone()
            return dict(row) if row else None
            
    def list_cabinets(self, location_id: str = None) -> List[dict]:
        with self.connect() as conn:
            if location_id:
                rows = conn.execute("SELECT * FROM cabinets WHERE location_id = ? ORDER BY name", (location_id,)).fetchall()
            else:
                rows = conn.execute("SELECT * FROM cabinets ORDER BY name").fetchall()
            return [dict(row) for row in rows]
            
    def update_cabinet(self, c_id: str, **kwargs) -> dict:
        now = self._now()
        kwargs['updated_at'] = now
        sets = ", ".join(f"{k} = ?" for k in kwargs.keys())
        values = list(kwargs.values()) + [c_id]
        with self.connect() as conn:
            conn.execute(f"UPDATE cabinets SET {sets} WHERE id = ?", values)
        return self.get_cabinet(c_id)

    def create_device(self, name: str, cabinet_id: str = None, location_id: str = None, kind: str = "", brand: str = "", model: str = "", port_count: int = 0, unit_size: int = 1, u_position: int = None, notes: str = "", extra_data: dict = None, id: str = None) -> dict:
        d_id = id or self._uuid()
        now = self._now()
        extra_str = json.dumps(extra_data) if extra_data else None
        with self.connect() as conn:
            conn.execute(
                """INSERT INTO devices (id, cabinet_id, location_id, name, kind, brand, model, port_count, unit_size, u_position, notes, extra_data, created_at, updated_at) 
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (d_id, cabinet_id, location_id, name, kind, brand, model, port_count, unit_size, u_position, notes, extra_str, now, now)
            )
        return self.get_device(d_id)
        
    def get_device(self, d_id: str) -> Optional[dict]:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM devices WHERE id = ?", (d_id,)).fetchone()
            return dict(row) if row else None
            
    def list_devices(self, cabinet_id: str = None, location_id: str = None) -> List[dict]:
        with self.connect() as conn:
            if cabinet_id:
                rows = conn.execute("SELECT * FROM devices WHERE cabinet_id = ? ORDER BY name", (cabinet_id,)).fetchall()
            elif location_id:
                rows = conn.execute("SELECT * FROM devices WHERE location_id = ? ORDER BY name", (location_id,)).fetchall()
            else:
                rows = conn.execute("SELECT * FROM devices ORDER BY name").fetchall()
            return [dict(row) for row in rows]
            
    def update_device(self, d_id: str, **kwargs) -> dict:
        now = self._now()
        kwargs['updated_at'] = now
        sets = ", ".join(f"{k} = ?" for k in kwargs.keys())
        values = list(kwargs.values()) + [d_id]
        with self.connect() as conn:
            conn.execute(f"UPDATE devices SET {sets} WHERE id = ?", values)
        return self.get_device(d_id)

    def create_media_record(self, target_type: str, target_id: str, source_app: str, uri: str, mime_type: str = None, id: str = None) -> dict:
        m_id = id or self._uuid()
        now = self._now()
        with self.connect() as conn:
            conn.execute(
                "INSERT INTO media_records (id, target_type, target_id, source_app, uri, mime_type, timestamp) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (m_id, target_type, target_id, source_app, uri, mime_type, now)
            )
        return self.get_media_record(m_id)
        
    def get_media_record(self, m_id: str) -> Optional[dict]:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM media_records WHERE id = ?", (m_id,)).fetchone()
            return dict(row) if row else None
            
    def list_media_records(self, target_type: str = None, target_id: str = None) -> List[dict]:
        with self.connect() as conn:
            if target_type and target_id:
                rows = conn.execute("SELECT * FROM media_records WHERE target_type = ? AND target_id = ? ORDER BY timestamp DESC", (target_type, target_id)).fetchall()
            else:
                rows = conn.execute("SELECT * FROM media_records ORDER BY timestamp DESC").fetchall()
            return [dict(row) for row in rows]
            
    def delete_building(self, b_id: str):
        with self.connect() as conn:
            conn.execute("DELETE FROM buildings WHERE id = ?", (b_id,))

    def delete_location(self, l_id: str):
        with self.connect() as conn:
            conn.execute("DELETE FROM locations WHERE id = ?", (l_id,))
            
    def delete_cabinet(self, c_id: str):
        with self.connect() as conn:
            conn.execute("DELETE FROM cabinets WHERE id = ?", (c_id,))
            
    def delete_device(self, d_id: str):
        with self.connect() as conn:
            conn.execute("DELETE FROM devices WHERE id = ?", (d_id,))
