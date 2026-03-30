from __future__ import annotations

from collections import defaultdict
from datetime import datetime, UTC
from typing import Any
from uuid import UUID

from db.models.evaluation_pass_sections import EvaluationPassSectionRow
from db.models.evaluation_passes import EvaluationPassRow
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload


def _utcnow() -> datetime:
    return datetime.now(UTC)


def create_evaluation_pass(
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


def record_evaluation_section_result(
    *,
    session: Session,
    tenant_id: UUID,
    evaluation_pass_id: UUID,
    section_id: str,
    section_title: str | None,
    section_order: int | None,
    verdict: str,
    grounding_score: int | None,
    issues: list[dict[str, Any]],
) -> EvaluationPassSectionRow:
    row = (
        session.query(EvaluationPassSectionRow)
        .filter(
            EvaluationPassSectionRow.tenant_id == tenant_id,
            EvaluationPassSectionRow.evaluation_pass_id == evaluation_pass_id,
            EvaluationPassSectionRow.section_id == section_id,
        )
        .one_or_none()
    )
    if row is None:
        row = EvaluationPassSectionRow(
            tenant_id=tenant_id,
            evaluation_pass_id=evaluation_pass_id,
            section_id=section_id,
        )
        session.add(row)

    row.section_title = section_title
    row.section_order = section_order
    row.verdict = verdict
    row.grounding_score = grounding_score
    row.issues_json = list(issues or [])
    session.flush()
    return row


def finalize_evaluation_pass(
    *,
    session: Session,
    tenant_id: UUID,
    evaluation_pass_id: UUID,
    grounding_pct: int | None = None,
    faithfulness_pct: int | None = None,
    sections_passed: int | None = None,
    sections_total: int | None = None,
    issues_by_type: dict[str, int] | None = None,
    status: str = "complete",
) -> EvaluationPassRow:
    row = (
        session.query(EvaluationPassRow)
        .filter(
            EvaluationPassRow.tenant_id == tenant_id,
            EvaluationPassRow.id == evaluation_pass_id,
        )
        .one()
    )
    row.status = status
    row.grounding_pct = grounding_pct
    row.faithfulness_pct = faithfulness_pct
    row.sections_passed = sections_passed
    row.sections_total = sections_total
    row.issues_by_type_json = dict(issues_by_type or {})
    row.completed_at = _utcnow()
    row.updated_at = _utcnow()
    session.flush()
    return row


def list_evaluation_pass_history(
    *,
    session: Session,
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

    passes = session.execute(stmt).scalars().all()
    history: list[dict[str, Any]] = []
    for evaluation_pass in passes:
        sections = sorted(
            evaluation_pass.sections,
            key=lambda row: (row.section_order if row.section_order is not None else 10**9, row.section_id),
        )
        issues_by_type = dict(evaluation_pass.issues_by_type_json or {})
        if not issues_by_type:
            tallies: dict[str, int] = defaultdict(int)
            for section in sections:
                for issue in section.issues_json or []:
                    problem = str(issue.get("problem") or "unknown")
                    tallies[problem] += 1
            issues_by_type = dict(tallies)

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
                "grounding_pct": evaluation_pass.grounding_pct,
                "faithfulness_pct": evaluation_pass.faithfulness_pct,
                "sections_passed": evaluation_pass.sections_passed,
                "sections_total": evaluation_pass.sections_total,
                "issues_by_type": issues_by_type,
                "sections": [
                    {
                        "section_id": section.section_id,
                        "title": section.section_title or section.section_id,
                        "grounding_score": section.grounding_score,
                        "verdict": section.verdict,
                        "issues": list(section.issues_json or []),
                    }
                    for section in sections
                ],
            }
        )
    return history
