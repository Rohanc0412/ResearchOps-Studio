"""
Async checkpoint helpers for orchestrator resume.

The async runtime writes checkpoints to `run_checkpoints`. Resume should only
hydrate from rows that contain a full orchestrator state payload.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any
from uuid import UUID

from db.models.run_checkpoints import RunCheckpointRow
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

RUNTIME_CHECKPOINT_NODE_NAMES = frozenset(
    {
        "retriever",
        "outliner",
        "evidence_pack",
        "writer",
        "evaluator",
        "repair_agent",
        "exporter",
    }
)


def _coerce_uuid(value: object) -> UUID | None:
    if value is None:
        return None
    try:
        return UUID(str(value))
    except (TypeError, ValueError):
        return None


def _has_state_identity(payload: dict[str, Any], *, tenant_id: UUID, run_id: UUID) -> bool:
    payload_tenant_id = _coerce_uuid(payload.get("tenant_id"))
    payload_run_id = _coerce_uuid(payload.get("run_id"))
    if payload_tenant_id is None or payload_run_id is None:
        return False
    return payload_tenant_id == tenant_id and payload_run_id == run_id


def _looks_like_resume_state_payload(payload: object, *, tenant_id: UUID, run_id: UUID) -> bool:
    if not isinstance(payload, dict):
        return False
    user_query = payload.get("user_query")
    if not isinstance(user_query, str) or not user_query.strip():
        return False
    return _has_state_identity(payload, tenant_id=tenant_id, run_id=run_id)


def _is_runtime_checkpoint_row(row: object) -> bool:
    node_name = getattr(row, "node_name", None)
    return isinstance(node_name, str) and node_name in RUNTIME_CHECKPOINT_NODE_NAMES


def select_resume_state_payload(
    rows: Sequence[object],
    *,
    tenant_id: UUID,
    run_id: UUID,
) -> dict[str, Any] | None:
    """
    Select the best checkpoint payload for resume.

    Resume only accepts runtime-managed checkpoint rows (`node_name` is a
    concrete orchestrator node). Legacy non-runtime rows are intentionally
    ignored.
    """

    for row in rows:
        if not _is_runtime_checkpoint_row(row):
            continue
        payload = getattr(row, "payload_json", None)
        if _looks_like_resume_state_payload(payload, tenant_id=tenant_id, run_id=run_id):
            return payload
    return None


async def load_resume_state_payload(
    *,
    session: AsyncSession,
    tenant_id: UUID,
    run_id: UUID,
    limit: int = 50,
) -> dict[str, Any] | None:
    """
    Load the latest resume-ready checkpoint payload for a run.

    `created_at` alone is not a reliable selector because multiple checkpoints can
    share the same transaction timestamp. We fetch a bounded recent window, then
    select the first runtime-compatible state payload.
    """

    rows = (
        (
            await session.execute(
                select(RunCheckpointRow)
                .where(RunCheckpointRow.tenant_id == tenant_id, RunCheckpointRow.run_id == run_id)
                .order_by(
                    RunCheckpointRow.created_at.desc(),
                    RunCheckpointRow.iteration_count.desc(),
                )
                .limit(limit)
            )
        )
        .scalars()
        .all()
    )
    return select_resume_state_payload(rows, tenant_id=tenant_id, run_id=run_id)


class PostgresCheckpointSaver:
    """Legacy sync saver removed in async runtime refactor."""

    def __init__(self, *_args, **_kwargs) -> None:
        raise RuntimeError(
            "PostgresCheckpointSaver is obsolete. Use checkpoint_store.write_checkpoint "
            "and checkpoints.load_resume_state_payload instead."
        )


def init_checkpoint_table(_engine) -> None:
    raise RuntimeError(
        "init_checkpoint_table is obsolete. Checkpoint schema is managed by "
        "run_checkpoints migrations."
    )


__all__ = [
    "PostgresCheckpointSaver",
    "init_checkpoint_table",
    "load_resume_state_payload",
    "select_resume_state_payload",
]
