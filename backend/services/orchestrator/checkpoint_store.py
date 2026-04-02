from __future__ import annotations

from uuid import UUID

from db.models.run_checkpoints import RunCheckpointRow
from db.repositories.project_runs import write_run_checkpoint
from sqlalchemy.ext.asyncio import AsyncSession


async def write_checkpoint(
    *,
    session: AsyncSession,
    tenant_id: UUID,
    run_id: UUID,
    node_name: str,
    iteration_count: int,
    state_payload: dict | None = None,
    summary_payload: dict | None = None,
    checkpoint_version: int = 1,
) -> RunCheckpointRow:
    return await write_run_checkpoint(
        session=session,
        tenant_id=tenant_id,
        run_id=run_id,
        node_name=node_name,
        iteration_count=iteration_count,
        state_payload=state_payload or {},
        summary_payload=summary_payload or {},
        checkpoint_version=checkpoint_version,
    )


__all__ = ["write_checkpoint"]
