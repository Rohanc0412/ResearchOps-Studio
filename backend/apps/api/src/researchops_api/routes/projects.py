from __future__ import annotations

from typing import Literal

import os
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.exc import IntegrityError
from researchops_api.middlewares.auth import IdentityDep
from researchops_api.schemas.truth import ProjectCreate, ProjectOut
from researchops_core.auth.identity import Identity
from researchops_core.auth.rbac import require_roles
from researchops_core.runs.lifecycle import emit_run_event
from researchops_core.tenancy import tenant_uuid
from researchops_orchestrator import RESEARCH_JOB_TYPE, enqueue_run_job

from db.models.run_events import RunEventLevelDb
from db.models.runs import RunStatusDb
from db.services.truth import create_project, create_run, list_projects
from db.services.truth import (
    get_project as get_project_row,
    get_run_by_client_request_id,
)
from db.session import session_scope

router = APIRouter(prefix="/projects", tags=["projects"])



def _tenant_uuid(identity: Identity) -> UUID:
    return tenant_uuid(identity.tenant_id)


class ProjectPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = None


class WebRunCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question: str | None = Field(default=None, min_length=1)
    prompt: str | None = Field(default=None, min_length=1)
    client_request_id: str | None = Field(default=None, min_length=1, max_length=200)
    output_type: Literal["report"] = "report"
    budget_override: dict | None = None
    llm_provider: str | None = Field(default=None, pattern="^(hosted)$")
    llm_model: str | None = Field(default=None, min_length=1)


class RunSetupResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    run_id: str
    status: str


@router.patch("/{project_id}", response_model=ProjectOut, response_model_exclude_none=True)
def patch_project(
    request: Request, project_id: UUID, body: ProjectPatch, identity: Identity = IdentityDep
) -> ProjectOut:
    try:
        require_roles("researcher", "admin", "owner")(identity)
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e)) from e

    SessionLocal = request.app.state.SessionLocal
    with session_scope(SessionLocal) as session:
        p = get_project_row(session=session, tenant_id=_tenant_uuid(identity), project_id=project_id)
        if p is None:
            raise HTTPException(status_code=404, detail="project not found")
        if body.name is not None:
            p.name = body.name
        if body.description is not None:
            p.description = body.description
        session.flush()
        return ProjectOut.model_validate(p)


@router.post("", response_model=ProjectOut, response_model_exclude_none=True)
def post_project(
    request: Request, body: ProjectCreate, identity: Identity = IdentityDep
) -> ProjectOut:
    try:
        require_roles("researcher", "admin", "owner")(identity)
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e)) from e

    SessionLocal = request.app.state.SessionLocal
    with session_scope(SessionLocal) as session:
        row = create_project(
            session=session,
            tenant_id=_tenant_uuid(identity),
            name=body.name,
            description=body.description,
            created_by=identity.user_id,
        )
        return ProjectOut.model_validate(row)


@router.get("", response_model=list[ProjectOut], response_model_exclude_none=True)
def get_projects(request: Request, identity: Identity = IdentityDep) -> list[ProjectOut]:
    SessionLocal = request.app.state.SessionLocal
    with session_scope(SessionLocal) as session:
        rows = list_projects(session=session, tenant_id=_tenant_uuid(identity))
        return [ProjectOut.model_validate(p) for p in rows]


@router.get("/{project_id}", response_model=ProjectOut, response_model_exclude_none=True)
def get_project_by_id(
    request: Request, project_id: UUID, identity: Identity = IdentityDep
) -> ProjectOut:
    SessionLocal = request.app.state.SessionLocal
    with session_scope(SessionLocal) as session:
        p = get_project_row(
            session=session, tenant_id=_tenant_uuid(identity), project_id=project_id
        )
        if p is None:
            raise HTTPException(status_code=404, detail="project not found")
        return ProjectOut.model_validate(p)


@router.post("/{project_id}/runs", response_model=RunSetupResponse)
def post_run_for_project(
    request: Request, project_id: UUID, body: WebRunCreate, identity: Identity = IdentityDep
):
    try:
        require_roles("researcher", "admin", "owner")(identity)
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e)) from e

    SessionLocal = request.app.state.SessionLocal
    with session_scope(SessionLocal) as session:
        question = (body.question or body.prompt or "").strip()
        if not question:
            raise HTTPException(status_code=400, detail="question is required")

        if body.client_request_id:
            existing = get_run_by_client_request_id(
                session=session,
                tenant_id=_tenant_uuid(identity),
                project_id=project_id,
                client_request_id=body.client_request_id,
            )
            if existing is not None:
                return RunSetupResponse(
                    run_id=str(existing.id),
                    status=existing.status.value,
                )

        try:
            budgets = body.budget_override or {}
            llm_provider = body.llm_provider or os.getenv("LLM_PROVIDER", "hosted")
            if llm_provider != "hosted":
                raise HTTPException(status_code=400, detail="Only hosted LLM provider is supported.")
            llm_model = body.llm_model or os.getenv("HOSTED_LLM_MODEL")
            run = create_run(
                session=session,
                tenant_id=_tenant_uuid(identity),
                project_id=project_id,
                status=RunStatusDb.queued,
                current_stage="retrieve",
                question=question,
                output_type="report",
                client_request_id=body.client_request_id,
                budgets_json=budgets,
            )
            run.usage_json = {
                "job_type": RESEARCH_JOB_TYPE,
                "user_query": question,
                "output_type": "report",
                "research_goal": "report",
                "llm_provider": llm_provider,
                "llm_model": llm_model,
            }
            emit_run_event(
                session=session,
                tenant_id=_tenant_uuid(identity),
                run_id=run.id,
                event_type="run.created",
                level=RunEventLevelDb.info,
                message="Run created",
                stage="retrieve",
                payload={"run_id": str(run.id)},
            )
            emit_run_event(
                session=session,
                tenant_id=_tenant_uuid(identity),
                run_id=run.id,
                event_type="run.queued",
                level=RunEventLevelDb.info,
                message="Run queued",
                stage="retrieve",
                payload={"run_id": str(run.id)},
            )
            enqueue_run_job(
                session=session,
                tenant_id=_tenant_uuid(identity),
                run_id=run.id,
                job_type=RESEARCH_JOB_TYPE,
            )
        except IntegrityError:
            session.rollback()
            if body.client_request_id:
                existing = get_run_by_client_request_id(
                    session=session,
                    tenant_id=_tenant_uuid(identity),
                    project_id=project_id,
                    client_request_id=body.client_request_id,
                )
                if existing is not None:
                    return RunSetupResponse(
                        run_id=str(existing.id),
                        status=existing.status.value,
                    )
            raise HTTPException(status_code=409, detail="run already exists")
        except ValueError as e:
            raise HTTPException(status_code=404, detail=str(e)) from e
        return RunSetupResponse(
            run_id=str(run.id),
            status=run.status.value,
        )


