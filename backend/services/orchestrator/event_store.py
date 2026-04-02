from __future__ import annotations

from uuid import UUID

from db.models.run_events import RunEventAudienceDb, RunEventLevelDb, RunEventRow
from db.repositories.project_runs import append_run_event
from sqlalchemy.ext.asyncio import AsyncSession


async def append_runtime_event(
    *,
    session: AsyncSession,
    tenant_id: UUID,
    run_id: UUID,
    audience: RunEventAudienceDb,
    event_type: str,
    level: RunEventLevelDb,
    stage: str | None,
    message: str,
    payload: dict | None = None,
    allow_finished: bool = False,
) -> RunEventRow:
    return await append_run_event(
        session=session,
        tenant_id=tenant_id,
        run_id=run_id,
        audience=audience,
        event_type=event_type,
        level=level,
        stage=stage,
        message=message,
        payload_json=payload or {},
        allow_finished=allow_finished,
    )


__all__ = ["append_runtime_event"]
