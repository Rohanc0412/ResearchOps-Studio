from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session, selectinload

from db.models.evaluation_pass_sections import EvaluationPassSectionRow
from db.models.evaluation_passes import EvaluationPassRow


def _utcnow() -> datetime:
    return datetime.now(UTC)


async def create_evaluation_pass(
    *,
    session: AsyncSession,
    tenant_id: UUID,
    run_id: UUID,
    scope: str,
) -> EvaluationPassRow:
    max_index = (await session.execute(
        select(func.max(EvaluationPassRow.pass_index)).where(
            EvaluationPassRow.tenant_id == tenant_id,
            EvaluationPassRow.run_id == run_id,
            EvaluationPassRow.scope == scope,
        )
    )).scalar_one()
    row = EvaluationPassRow(
        tenant_id=tenant_id,
        run_id=run_id,
        scope=scope,
        pass_index=(int(max_index) if max_index is not None else 0) + 1,
        status="running",
    )
    session.add(row)
    await session.flush()
    return row


async def record_evaluation_section_result(
    *,
    session: AsyncSession,
    tenant_id: UUID,
    evaluation_pass_id: UUID,
    section_id: str,
    section_title: str | None,
    section_order: int | None,
    quality_score: int | None,
    claims: list[dict[str, Any]],
) -> EvaluationPassSectionRow:
    row = (await session.execute(
        select(EvaluationPassSectionRow).where(
            EvaluationPassSectionRow.tenant_id == tenant_id,
            EvaluationPassSectionRow.evaluation_pass_id == evaluation_pass_id,
            EvaluationPassSectionRow.section_id == section_id,
        )
    )).scalar_one_or_none()
    if row is None:
        row = EvaluationPassSectionRow(
            tenant_id=tenant_id,
            evaluation_pass_id=evaluation_pass_id,
            section_id=section_id,
        )
        session.add(row)

    row.section_title = section_title
    row.section_order = section_order
    row.quality_score = quality_score
    row.claims_json = list(claims or [])
    await session.flush()
    return row


async def finalize_evaluation_pass(
    *,
    session: AsyncSession,
    tenant_id: UUID,
    evaluation_pass_id: UUID,
    quality_pct: int | None = None,
    hallucination_rate: int | None = None,
    issues_by_type: dict[str, int] | None = None,
    status: str = "complete",
) -> EvaluationPassRow:
    row = (await session.execute(
        select(EvaluationPassRow).where(
            EvaluationPassRow.tenant_id == tenant_id,
            EvaluationPassRow.id == evaluation_pass_id,
        )
    )).scalar_one()
    row.status = status
    row.quality_pct = quality_pct
    row.hallucination_rate = hallucination_rate
    row.issues_by_type_json = dict(issues_by_type or {})
    row.completed_at = _utcnow()
    row.updated_at = _utcnow()
    await session.flush()
    return row


# ---------------------------------------------------------------------------
# Sync variants for orchestrator nodes (receive a sync sqlalchemy.orm.Session)
# ---------------------------------------------------------------------------

def create_evaluation_pass_sync(
    *,
    session: Session,
    tenant_id: UUID,
    run_id: UUID,
    scope: str,
) -> EvaluationPassRow:
    max_index = session.execute(
        select(func.max(EvaluationPassRow.pass_index)).where(
            EvaluationPassRow.tenant_id == tenant_id,
            EvaluationPassRow.run_id == run_id,
            EvaluationPassRow.scope == scope,
        )
    ).scalar_one()
    row = EvaluationPassRow(
        tenant_id=tenant_id,
        run_id=run_id,
        scope=scope,
        pass_index=(int(max_index) if max_index is not None else 0) + 1,
        status="running",
    )
    session.add(row)
    session.flush()
    return row


def record_evaluation_section_result_sync(
    *,
    session: Session,
    tenant_id: UUID,
    evaluation_pass_id: UUID,
    section_id: str,
    section_title: str | None,
    section_order: int | None,
    quality_score: int | None,
    claims: list[dict[str, Any]],
) -> EvaluationPassSectionRow:
    row = session.execute(
        select(EvaluationPassSectionRow).where(
            EvaluationPassSectionRow.tenant_id == tenant_id,
            EvaluationPassSectionRow.evaluation_pass_id == evaluation_pass_id,
            EvaluationPassSectionRow.section_id == section_id,
        )
    ).scalar_one_or_none()
    if row is None:
        row = EvaluationPassSectionRow(
            tenant_id=tenant_id,
            evaluation_pass_id=evaluation_pass_id,
            section_id=section_id,
        )
        session.add(row)

    row.section_title = section_title
    row.section_order = section_order
    row.quality_score = quality_score
    row.claims_json = list(claims or [])
    session.flush()
    return row


def finalize_evaluation_pass_sync(
    *,
    session: Session,
    tenant_id: UUID,
    evaluation_pass_id: UUID,
    quality_pct: int | None = None,
    hallucination_rate: int | None = None,
    issues_by_type: dict[str, int] | None = None,
    status: str = "complete",
) -> EvaluationPassRow:
    row = session.execute(
        select(EvaluationPassRow).where(
            EvaluationPassRow.tenant_id == tenant_id,
            EvaluationPassRow.id == evaluation_pass_id,
        )
    ).scalar_one()
    row.status = status
    row.quality_pct = quality_pct
    row.hallucination_rate = hallucination_rate
    row.issues_by_type_json = dict(issues_by_type or {})
    row.completed_at = _utcnow()
    row.updated_at = _utcnow()
    session.flush()
    return row


async def list_evaluation_pass_history(
    *,
    session: AsyncSession,
    tenant_id: UUID,
    run_id: UUID,
    include_running: bool = False,
) -> list[dict[str, Any]]:
    stmt = (
        select(EvaluationPassRow)
        .options(selectinload(EvaluationPassRow.sections))
        .where(
            EvaluationPassRow.tenant_id == tenant_id,
            EvaluationPassRow.run_id == run_id,
        )
        .order_by(EvaluationPassRow.pass_index.desc(), EvaluationPassRow.started_at.desc())
    )
    if not include_running:
        stmt = stmt.where(EvaluationPassRow.status == "complete")

    passes = (await session.execute(stmt)).scalars().all()
    history: list[dict[str, Any]] = []
    for evaluation_pass in passes:
        sections = sorted(
            evaluation_pass.sections,
            key=lambda row: (row.section_order if row.section_order is not None else 10**9, row.section_id),
        )
        history.append(
            {
                "id": str(evaluation_pass.id),
                "scope": evaluation_pass.scope,
                "pass_index": evaluation_pass.pass_index,
                "status": evaluation_pass.status,
                "evaluated_at": (
                    evaluation_pass.completed_at or evaluation_pass.started_at
                ).isoformat()
                if (evaluation_pass.completed_at or evaluation_pass.started_at)
                else None,
                "quality_pct": evaluation_pass.quality_pct,
                "hallucination_rate": evaluation_pass.hallucination_rate,
                "sections": [
                    {
                        "section_id": section.section_id,
                        "title": section.section_title or section.section_id,
                        "quality_score": section.quality_score,
                        "claims": list(section.claims_json or []),
                    }
                    for section in sections
                ],
            }
        )
    return history


def list_evaluation_pass_history_sync(
    *,
    session: Session,
    tenant_id: UUID,
    run_id: UUID,
    include_running: bool = False,
) -> list[dict[str, Any]]:
    """Synchronous counterpart of list_evaluation_pass_history for tests and sync callers."""
    stmt = (
        select(EvaluationPassRow)
        .options(selectinload(EvaluationPassRow.sections))
        .where(
            EvaluationPassRow.tenant_id == tenant_id,
            EvaluationPassRow.run_id == run_id,
        )
        .order_by(EvaluationPassRow.pass_index.desc(), EvaluationPassRow.started_at.desc())
    )
    if not include_running:
        stmt = stmt.where(EvaluationPassRow.status == "complete")

    passes = session.execute(stmt).scalars().all()
    history: list[dict[str, Any]] = []
    for evaluation_pass in passes:
        sections = sorted(
            evaluation_pass.sections,
            key=lambda row: (row.section_order if row.section_order is not None else 10**9, row.section_id),
        )
        history.append(
            {
                "id": str(evaluation_pass.id),
                "scope": evaluation_pass.scope,
                "pass_index": evaluation_pass.pass_index,
                "status": evaluation_pass.status,
                "evaluated_at": (
                    evaluation_pass.completed_at or evaluation_pass.started_at
                ).isoformat()
                if (evaluation_pass.completed_at or evaluation_pass.started_at)
                else None,
                "quality_pct": evaluation_pass.quality_pct,
                "hallucination_rate": evaluation_pass.hallucination_rate,
                "sections": [
                    {
                        "section_id": section.section_id,
                        "title": section.section_title or section.section_id,
                        "quality_score": section.quality_score,
                        "claims": list(section.claims_json or []),
                    }
                    for section in sections
                ],
            }
        )
    return history
