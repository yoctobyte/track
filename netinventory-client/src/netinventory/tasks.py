from __future__ import annotations

import uuid
from datetime import UTC, datetime

from netinventory.collect.collector import collect_once
from netinventory.core.tasks import TaskClass, TaskDefinition, TaskRunRecord, TaskState, TaskTrigger
from netinventory.storage.db import Database


TASK_DEFINITIONS: tuple[TaskDefinition, ...] = (
    TaskDefinition(
        task_id="current_network_probe",
        task_class=TaskClass.INSTANT,
        description="Collect current local IP and host fingerprint",
        triggers=(TaskTrigger.STARTUP, TaskTrigger.NETWORK_CHANGE, TaskTrigger.MANUAL),
        expected_cost="low",
    ),
    TaskDefinition(
        task_id="arp_snapshot",
        task_class=TaskClass.BURST,
        description="Capture a bounded ARP/neighbor snapshot",
        triggers=(TaskTrigger.NETWORK_CHANGE, TaskTrigger.MANUAL, TaskTrigger.TIMER),
        expected_cost="medium",
    ),
    TaskDefinition(
        task_id="gps_watch",
        task_class=TaskClass.MONITOR,
        description="Continuously watch for GPS availability and fixes",
        triggers=(TaskTrigger.STARTUP,),
        expected_cost="low",
        long_running=True,
    ),
    TaskDefinition(
        task_id="user_context",
        task_class=TaskClass.USER_CONTEXT,
        description="Attach human-supplied context like room, port, or switch",
        triggers=(TaskTrigger.USER_INPUT,),
        expected_cost="low",
    ),
)


def list_task_definitions() -> list[TaskDefinition]:
    return list(TASK_DEFINITIONS)


def run_task_once(db: Database, task_id: str, trigger: TaskTrigger) -> TaskRunRecord:
    now = datetime.now(UTC).isoformat()
    run_id = str(uuid.uuid4())
    db.record_task_run(
        TaskRunRecord(
            run_id=run_id,
            task_id=task_id,
            trigger=trigger,
            state=TaskState.RUNNING,
            started_at=now,
        )
    )

    if task_id == "current_network_probe":
        observation = collect_once()
        ingest = db.record_observation(observation)
        finished = datetime.now(UTC).isoformat()
        detail = f"{ingest.reason}: {ingest.network_id}"
        result = TaskRunRecord(
            run_id=run_id,
            task_id=task_id,
            trigger=trigger,
            state=TaskState.SUCCEEDED,
            started_at=now,
            finished_at=finished,
            detail=detail,
        )
        db.record_task_run(result)
        return result

    finished = datetime.now(UTC).isoformat()
    result = TaskRunRecord(
        run_id=run_id,
        task_id=task_id,
        trigger=trigger,
        state=TaskState.SKIPPED,
        started_at=now,
        finished_at=finished,
        detail="task registered but not implemented yet",
    )
    db.record_task_run(result)
    return result
