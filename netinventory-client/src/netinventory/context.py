from __future__ import annotations

import uuid
from datetime import UTC, datetime

from netinventory.core.context import UserContextRecord
from netinventory.core.tasks import TaskRunRecord, TaskState, TaskTrigger
from netinventory.storage.db import Database


def add_user_context(
    db: Database,
    entity_kind: str,
    entity_id: str,
    field: str,
    value: str,
) -> TaskRunRecord:
    now = datetime.now(UTC).isoformat()
    run_id = str(uuid.uuid4())
    detail = f"{entity_kind}:{entity_id}:{field}"

    db.record_task_run(
        TaskRunRecord(
            run_id=run_id,
            task_id="user_context",
            trigger=TaskTrigger.USER_INPUT,
            state=TaskState.RUNNING,
            started_at=now,
            detail=detail,
        )
    )

    record = UserContextRecord(
        context_id=str(uuid.uuid4()),
        created_at=now,
        entity_kind=entity_kind,
        entity_id=entity_id,
        field=field,
        value=value,
    )
    db.add_user_context(record)

    finished = datetime.now(UTC).isoformat()
    result = TaskRunRecord(
        run_id=run_id,
        task_id="user_context",
        trigger=TaskTrigger.USER_INPUT,
        state=TaskState.SUCCEEDED,
        started_at=now,
        finished_at=finished,
        detail=detail,
    )
    db.record_task_run(result)
    return result
