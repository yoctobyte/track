from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class UserContextRecord:
    context_id: str
    created_at: str
    entity_kind: str
    entity_id: str
    field: str
    value: str
    source: str = "user"

    def to_dict(self) -> dict[str, str]:
        return {
            "context_id": self.context_id,
            "created_at": self.created_at,
            "entity_kind": self.entity_kind,
            "entity_id": self.entity_id,
            "field": self.field,
            "value": self.value,
            "source": self.source,
        }
