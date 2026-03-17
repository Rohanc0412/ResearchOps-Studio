from __future__ import annotations

import os
from datetime import datetime
from uuid import UUID

from fastapi import HTTPException, Request
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from researchops_api.schemas.truth import ArtifactOut, ProjectOut
from core.audit.logger import write_audit_log
from core.auth.identity import Identity
from core.runs import RunNotFoundError, RunTransitionError, request_cancel, retry_run
from core.runs.lifecycle import emit_run_event
from researchops_orchestrator import RESEARCH_JOB_TYPE, enqueue_run_job

from db.models.run_events import RunEventLevelDb
from db.models.runs import RunStatusDb
from db.repositories.artifacts import list_artifacts
from db.repositories.project_runs import (
    create_project,
    create_run,
    get_project_for_user,
    get_run_budget_limits,
    get_run_by_client_request_id,
    get_run_for_user,
    get_run_usage_metrics,
    list_projects_for_user,
)


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
        run = create_run(
            session=session,
            tenant_id=tenant_id,
            project_id=project_id,
            status=RunStatusDb.queued,
            current_stage="retrieve",
            question=question,
            output_type="report",
            client_request_id=client_request_id,
            budgets=budgets,
            usage={
                "job_type": RESEARCH_JOB_TYPE,
                "user_query": question,
                "output_type": "report",
                "research_goal": "report",
                "llm_provider": resolved_provider,
                "llm_model": resolved_model,
            },
        )
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
        return str(run.id), run.status.value
    except IntegrityError:
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
        raise HTTPException(status_code=409, detail="run already exists")
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


def run_to_web(run):
    return {
        "id": run.id,
        "tenant_id": run.tenant_id,
        "project_id": run.project_id,
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
    get_user_run_or_404(session=session, tenant_id=tenant_id, run_id=run_id, user_id=identity.user_id)
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
):
    get_user_run_or_404(session=session, tenant_id=tenant_id, run_id=run_id, user_id=identity.user_id)
    try:
        run = retry_run(
            session=session,
            tenant_id=tenant_id,
            run_id=run_id,
        )
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
