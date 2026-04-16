from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class TaskClass(str, Enum):
    INSTANT = "instant"
    BURST = "burst"
    MONITOR = "monitor"
    USER_CONTEXT = "user_context"


class TaskTrigger(str, Enum):
    STARTUP = "startup"
    NETWORK_CHANGE = "network_change"
    TIMER = "timer"
    MANUAL = "manual"
    USER_INPUT = "user_input"


class TaskState(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass(frozen=True)
class TaskDefinition:
    task_id: str
    task_class: TaskClass
    description: str
    triggers: tuple[TaskTrigger, ...]
    expected_cost: str
    long_running: bool = False

    def to_dict(self) -> dict[str, object]:
        return {
            "task_id": self.task_id,
            "task_class": self.task_class.value,
            "description": self.description,
            "triggers": [trigger.value for trigger in self.triggers],
            "expected_cost": self.expected_cost,
            "long_running": self.long_running,
        }


@dataclass(frozen=True)
class TaskRunRecord:
    run_id: str
    task_id: str
    trigger: TaskTrigger
    state: TaskState
    started_at: str
    finished_at: str | None = None
    detail: str | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "run_id": self.run_id,
            "task_id": self.task_id,
            "trigger": self.trigger.value,
            "state": self.state.value,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "detail": self.detail,
        }
