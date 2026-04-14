from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class StatusSnapshot:
    db_path: str
    device_id: str
    schema_version: int
    network_count: int
    observation_count: int
    active_network_id: str | None

    def to_dict(self) -> dict[str, str | int | None]:
        return {
            "db_path": self.db_path,
            "device_id": self.device_id,
            "schema_version": self.schema_version,
            "network_count": self.network_count,
            "observation_count": self.observation_count,
            "active_network_id": self.active_network_id,
        }


@dataclass(frozen=True)
class NetworkSummary:
    network_id: str
    first_seen: str | None
    last_seen: str | None
    seen_count: int
    confidence: float
    display_name: str | None
    notes: str | None

    def to_dict(self) -> dict[str, str | int | float | None]:
        return {
            "network_id": self.network_id,
            "first_seen": self.first_seen,
            "last_seen": self.last_seen,
            "seen_count": self.seen_count,
            "confidence": self.confidence,
            "display_name": self.display_name,
            "notes": self.notes,
        }


@dataclass(frozen=True)
class ObservationIngestResult:
    observation_id: str
    network_id: str
    stored: bool
    material_change: bool
    active_network_changed: bool
    reason: str

    def to_dict(self) -> dict[str, str | bool]:
        return {
            "observation_id": self.observation_id,
            "network_id": self.network_id,
            "stored": self.stored,
            "material_change": self.material_change,
            "active_network_changed": self.active_network_changed,
            "reason": self.reason,
        }
