from __future__ import annotations

import os
from uuid import UUID

from core.audit.logger import write_audit_log
from core.auth.identity import Identity
from core.runs import RunNotFoundError, RunTransitionError, request_cancel, retry_run
from core.runs.lifecycle import emit_run_event, transition_run_status
from db.models.run_events import RunEventLevelDb
from db.models.runs import RunRow, RunStatusDb
from db.models.section_evidence import SectionEvidenceRow
from db.models.snippets import SnippetRow
from db.models.snapshots import SnapshotRow
from db.models.sources import SourceRow
from db.repositories.artifacts import list_artifacts
from db.repositories.corpus import get_source
from db.repositories.project_runs import (
    create_project,
    create_run,
    get_project_for_user,
    get_run_budget_limits,
    get_run_by_client_request_id,
    get_run_for_user,
    get_run_usage_metrics,
    list_projects_for_user,
    patch_run_usage_metrics,
)
from fastapi import HTTPException, Request
from job_queue import enqueue_run_job
from research import RESEARCH_JOB_TYPE
from schemas.truth import ArtifactOut, ProjectOut
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

ACTIVE_RESEARCH_RUN_MESSAGE = "Another research run is already in progress. Retry after it finishes."
ACTIVE_RESEARCH_RUN_ERROR_CODE = "research_run_active"


def project_to_out(project) -> ProjectOut:
    return ProjectOut.model_validate(project)


def list_user_projects(*, session: Session, tenant_id: UUID, user_id: str) -> list[ProjectOut]:
    return [
        ProjectOut.model_validate(row)
        for row in list_projects_for_user(session=session, tenant_id=tenant_id, created_by=user_id)
    ]


def get_user_project(*, session: Session, tenant_id: UUID, project_id: UUID, user_id: str):
    return get_project_for_user(
        session=session, tenant_id=tenant_id, project_id=project_id, created_by=user_id
    )


def patch_user_project(
    *,
    session: Session,
    tenant_id: UUID,
    project_id: UUID,
    user_id: str,
    name: str | None,
    description: str | None,
) -> ProjectOut:
    project = get_user_project(
        session=session, tenant_id=tenant_id, project_id=project_id, user_id=user_id
    )
    if project is None:
        raise HTTPException(status_code=404, detail="project not found")
    if name is not None:
        project.name = name
    if description is not None:
        project.description = description
    session.flush()
    return project_to_out(project)


def create_user_project(
    *,
    session: Session,
    tenant_id: UUID,
    user_id: str,
    name: str,
    description: str | None,
) -> ProjectOut:
    row = create_project(
        session=session,
        tenant_id=tenant_id,
        name=name,
        description=description,
        created_by=user_id,
    )
    return project_to_out(row)


def has_active_research_run(
    *, session: Session, exclude_run_id: UUID | None = None
) -> bool:
    stmt = select(RunRow.id).where(RunRow.status == RunStatusDb.running)
    if exclude_run_id is not None:
        stmt = stmt.where(RunRow.id != exclude_run_id)
    return session.execute(stmt.limit(1)).scalar_one_or_none() is not None


def _mark_run_blocked(run: RunRow) -> None:
    run.failure_reason = ACTIVE_RESEARCH_RUN_MESSAGE
    run.error_code = ACTIVE_RESEARCH_RUN_ERROR_CODE
    run.current_stage = None


def create_research_run(
    *,
    session: Session,
    tenant_id: UUID,
    project_id: UUID,
    question: str,
    client_request_id: str | None,
    budgets: dict,
    llm_provider: str,
    llm_model: str | None,
    stage_models: str | None = None,
) -> RunRow:
    is_blocked = has_active_research_run(session=session)
    run = create_run(
        session=session,
        tenant_id=tenant_id,
        project_id=project_id,
        status=RunStatusDb.blocked if is_blocked else RunStatusDb.queued,
        current_stage=None if is_blocked else "retrieve",
        question=question,
        output_type="report",
        client_request_id=client_request_id,
        budgets=budgets,
        usage={
            "job_type": RESEARCH_JOB_TYPE,
            "user_query": question,
            "output_type": "report",
            "research_goal": "report",
            "llm_provider": llm_provider,
            "llm_model": llm_model,
            "stage_models": stage_models,
        },
    )
    if is_blocked:
        _mark_run_blocked(run)

    emit_run_event(
        session=session,
        tenant_id=tenant_id,
        run_id=run.id,
        event_type="run.created",
        level=RunEventLevelDb.info,
        message="Run created",
        stage="retrieve",
        payload={"run_id": str(run.id)},
    )

    if is_blocked:
        emit_run_event(
            session=session,
            tenant_id=tenant_id,
            run_id=run.id,
            event_type="run.blocked",
            level=RunEventLevelDb.warn,
            message=ACTIVE_RESEARCH_RUN_MESSAGE,
            stage="retrieve",
            payload={"run_id": str(run.id), "reason": ACTIVE_RESEARCH_RUN_ERROR_CODE},
        )
        session.flush()
        return run

    emit_run_event(
        session=session,
        tenant_id=tenant_id,
        run_id=run.id,
        event_type="run.queued",
        level=RunEventLevelDb.info,
        message="Run queued",
        stage="retrieve",
        payload={"run_id": str(run.id)},
    )
    enqueue_run_job(
        session=session,
        tenant_id=tenant_id,
        run_id=run.id,
        job_type=RESEARCH_JOB_TYPE,
    )
    session.flush()
    return run


def create_project_run(
    *,
    request: Request,
    session: Session,
    tenant_id: UUID,
    project_id: UUID,
    identity: Identity,
    question: str,
    client_request_id: str | None,
    budget_override: dict | None,
    llm_provider: str | None,
    llm_model: str | None,
) -> tuple[str, str]:
    project = get_user_project(
        session=session, tenant_id=tenant_id, project_id=project_id, user_id=identity.user_id
    )
    if project is None:
        raise HTTPException(status_code=404, detail="project not found")

    question = (question or "").strip()
    if not question:
        raise HTTPException(status_code=400, detail="question is required")

    if client_request_id:
        existing = get_run_by_client_request_id(
            session=session,
            tenant_id=tenant_id,
            project_id=project_id,
            client_request_id=client_request_id,
        )
        if existing is not None:
            return str(existing.id), existing.status.value

    try:
        budgets = budget_override or {}
        resolved_provider = llm_provider or "hosted"
        if resolved_provider != "hosted":
            raise HTTPException(status_code=400, detail="Only hosted LLM provider is supported.")
        resolved_model = llm_model or os.getenv("HOSTED_LLM_MODEL")
        run = create_research_run(
            session=session,
            tenant_id=tenant_id,
            project_id=project_id,
            question=question,
            client_request_id=client_request_id,
            budgets=budgets,
            llm_provider=resolved_provider,
            llm_model=resolved_model,
        )
        return str(run.id), run.status.value
    except IntegrityError as exc:
        session.rollback()
        if client_request_id:
            existing = get_run_by_client_request_id(
                session=session,
                tenant_id=tenant_id,
                project_id=project_id,
                client_request_id=client_request_id,
            )
            if existing is not None:
                return str(existing.id), existing.status.value
        raise HTTPException(status_code=409, detail="run already exists") from exc
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


def run_to_web(run):
    return {
        "id": run.id,
        "tenant_id": run.tenant_id,
        "project_id": run.project_id,
        "question": run.question,
        "status": run.status.value,
        "current_stage": run.current_stage,
        "created_at": run.created_at,
        "updated_at": run.updated_at,
        "started_at": run.started_at,
        "finished_at": run.finished_at,
        "cancel_requested_at": run.cancel_requested_at,
        "retry_count": run.retry_count,
        "error_message": run.failure_reason,
        "error_code": run.error_code,
        "budgets": get_run_budget_limits(run),
        "usage": get_run_usage_metrics(run),
    }


def get_user_run_or_404(*, session: Session, tenant_id: UUID, run_id: UUID, user_id: str):
    run = get_run_for_user(session=session, tenant_id=tenant_id, run_id=run_id, created_by=user_id)
    if run is None:
        raise HTTPException(status_code=404, detail="run not found")
    return run


def cancel_user_run(
    *,
    request: Request,
    session: Session,
    tenant_id: UUID,
    run_id: UUID,
    identity: Identity,
) -> None:
    get_user_run_or_404(
        session=session,
        tenant_id=tenant_id,
        run_id=run_id,
        user_id=identity.user_id,
    )
    try:
        run = request_cancel(
            session=session,
            tenant_id=tenant_id,
            run_id=run_id,
            force_immediate=False,
        )
        write_audit_log(
            db=session,
            identity=identity,
            action="run.cancel",
            target_type="run",
            target_id=str(run_id),
            metadata={"status": run.status.value},
            request=request,
        )
    except RunNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


def retry_user_run(
    *,
    request: Request,
    session: Session,
    tenant_id: UUID,
    run_id: UUID,
    identity: Identity,
    llm_model: str | None = None,
):
    run = get_user_run_or_404(
        session=session,
        tenant_id=tenant_id,
        run_id=run_id,
        user_id=identity.user_id,
    )
    try:
        if has_active_research_run(session=session, exclude_run_id=run_id):
            if run.status not in {RunStatusDb.failed, RunStatusDb.blocked}:
                raise RunTransitionError(
                    f"Cannot retry run in status {run.status.value}. "
                    f"Retry is only allowed for failed or blocked runs."
                )
            _mark_run_blocked(run)
            if run.status != RunStatusDb.blocked:
                transition_run_status(
                    session=session,
                    tenant_id=tenant_id,
                    run_id=run_id,
                    to_status=RunStatusDb.blocked,
                    current_stage=None,
                    failure_reason=ACTIVE_RESEARCH_RUN_MESSAGE,
                    error_code=ACTIVE_RESEARCH_RUN_ERROR_CODE,
                    finished_at=None,
                    cancel_requested_at=None,
                    emit_event=False,
                )
            emit_run_event(
                session=session,
                tenant_id=tenant_id,
                run_id=run.id,
                event_type="run.blocked",
                level=RunEventLevelDb.warn,
                message=ACTIVE_RESEARCH_RUN_MESSAGE,
                stage="retrieve",
                payload={"run_id": str(run.id), "reason": ACTIVE_RESEARCH_RUN_ERROR_CODE},
            )
            if llm_model:
                patch_run_usage_metrics(run, {"llm_model": llm_model})
            session.flush()
            return run
        run = retry_run(
            session=session,
            tenant_id=tenant_id,
            run_id=run_id,
        )
        if llm_model:
            patch_run_usage_metrics(run, {"llm_model": llm_model})
        job_type = get_run_usage_metrics(run).get("job_type")
        if not isinstance(job_type, str) or not job_type:
            job_type = RESEARCH_JOB_TYPE
        enqueue_run_job(
            session=session,
            tenant_id=tenant_id,
            run_id=run.id,
            job_type=job_type,
        )
        write_audit_log(
            db=session,
            identity=identity,
            action="run.retry",
            target_type="run",
            target_id=str(run_id),
            metadata={"retry_count": run.retry_count},
            request=request,
        )
        return run
    except (RunNotFoundError, RunTransitionError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def list_user_run_snippets(
    *,
    session: Session,
    tenant_id: UUID,
    run_id: UUID,
    user_id: str,
) -> list[dict]:
    from sqlalchemy import select

    get_user_run_or_404(session=session, tenant_id=tenant_id, run_id=run_id, user_id=user_id)

    # Single query: join section_evidence → snippet → snapshot → source to avoid N+1.
    # All tenant_id guards are applied in the WHERE clause.
    rows = session.execute(
        select(
            SnippetRow.id,
            SnippetRow.text,
            SourceRow.id.label("source_id"),
            SourceRow.title.label("source_title"),
            SourceRow.url.label("source_url"),
        )
        .select_from(SectionEvidenceRow)
        .join(SnippetRow, SnippetRow.id == SectionEvidenceRow.snippet_id)
        .join(SnapshotRow, SnapshotRow.id == SnippetRow.snapshot_id)
        .join(SourceRow, SourceRow.id == SnapshotRow.source_id)
        .where(
            SectionEvidenceRow.tenant_id == tenant_id,
            SectionEvidenceRow.run_id == run_id,
            SnippetRow.tenant_id == tenant_id,
            SnapshotRow.tenant_id == tenant_id,
            SourceRow.tenant_id == tenant_id,
        )
        .distinct(SnippetRow.id)
    ).all()

    return [
        {
            "id": str(row.id),
            "text": row.text[:300] + ("…" if len(row.text) > 300 else ""),
            "source_id": str(row.source_id) if row.source_id else None,
            "source_title": row.source_title,
            "source_url": row.source_url,
        }
        for row in rows
    ]


def list_user_run_artifacts(
    *,
    session: Session,
    tenant_id: UUID,
    run_id: UUID,
    user_id: str,
) -> list[ArtifactOut]:
    get_user_run_or_404(session=session, tenant_id=tenant_id, run_id=run_id, user_id=user_id)
    rows = list_artifacts(session=session, tenant_id=tenant_id, run_id=run_id)
    return [
        ArtifactOut(
            id=a.id,
            tenant_id=a.tenant_id,
            project_id=a.project_id,
            run_id=a.run_id,
            type=a.artifact_type,
            blob_ref=a.blob_ref,
            mime_type=a.mime_type,
            size_bytes=a.size_bytes,
            metadata_json=a.metadata_json,
            created_at=a.created_at,
        )
        for a in rows
    ]
