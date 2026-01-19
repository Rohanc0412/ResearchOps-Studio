from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field
from researchops_api.middlewares.auth import IdentityDep
from researchops_api.schemas.truth import (
    ArtifactCreate,
    ArtifactOut,
    ProjectCreate,
    ProjectOut,
    RunOut,
)
from researchops_core.auth.identity import Identity
from researchops_core.auth.rbac import require_roles
from researchops_core.tenancy import tenant_uuid
from researchops_orchestrator import HELLO_JOB_TYPE, enqueue_run_job

from db.models.runs import RunStatusDb
from db.services.truth import (
    create_artifact,
    create_project,
    create_run,
    list_artifacts,
    list_projects,
    list_runs_for_project,
)
from db.services.truth import (
    get_project as get_project_row,
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

    prompt: str = Field(min_length=1)
    output_type: str = Field(min_length=1)
    budget_override: dict | None = None


class WebRunOut(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: str
    run_id: str
    status: str
    project_id: str
    tenant_id: str
    created_at: str | None = None
    updated_at: str | None = None
    error_message: str | None = None
    budgets: dict = Field(default_factory=dict)


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


@router.post("/{project_id}/runs", response_model=WebRunOut)
def post_run_for_project(
    request: Request, project_id: UUID, body: WebRunCreate, identity: Identity = IdentityDep
):
    try:
        require_roles("researcher", "admin", "owner")(identity)
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e)) from e

    SessionLocal = request.app.state.SessionLocal
    with session_scope(SessionLocal) as session:
        try:
            budgets = body.budget_override or {}
            run = create_run(
                session=session,
                tenant_id=_tenant_uuid(identity),
                project_id=project_id,
                status=RunStatusDb.queued,
                budgets_json=budgets,
            )
            enqueue_run_job(
                session=session,
                tenant_id=_tenant_uuid(identity),
                run_id=run.id,
                job_type=HELLO_JOB_TYPE,
            )
        except ValueError as e:
            raise HTTPException(status_code=404, detail=str(e)) from e
        return WebRunOut(
            id=str(run.id),
            run_id=str(run.id),
            status=run.status.value,
            project_id=str(run.project_id),
            tenant_id=str(run.tenant_id),
            created_at=run.created_at.isoformat() if run.created_at else None,
            updated_at=run.updated_at.isoformat() if run.updated_at else None,
            error_message=run.failure_reason,
            budgets=budgets,
        )


@router.get("/{project_id}/runs", response_model=list[RunOut])
def get_runs_for_project(
    request: Request, project_id: UUID, identity: Identity = IdentityDep
) -> list[RunOut]:
    SessionLocal = request.app.state.SessionLocal
    with session_scope(SessionLocal) as session:
        if (
            get_project_row(
                session=session, tenant_id=_tenant_uuid(identity), project_id=project_id
            )
            is None
        ):
            raise HTTPException(status_code=404, detail="project not found")
        rows = list_runs_for_project(
            session=session, tenant_id=_tenant_uuid(identity), project_id=project_id
        )
        return [RunOut.model_validate(r) for r in rows]


@router.post("/{project_id}/artifacts", response_model=ArtifactOut)
def post_artifact_for_project(
    request: Request,
    project_id: UUID,
    body: ArtifactCreate,
    identity: Identity = IdentityDep,
) -> ArtifactOut:
    try:
        require_roles("researcher", "admin", "owner")(identity)
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e)) from e

    SessionLocal = request.app.state.SessionLocal
    with session_scope(SessionLocal) as session:
        try:
            a = create_artifact(
                session=session,
                tenant_id=_tenant_uuid(identity),
                project_id=project_id,
                run_id=body.run_id,
                artifact_type=body.type,
                blob_ref=body.blob_ref,
                mime_type=body.mime_type,
                size_bytes=body.size_bytes,
                metadata_json=body.metadata_json,
            )
        except ValueError as e:
            raise HTTPException(status_code=404, detail=str(e)) from e

        return ArtifactOut(
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


@router.get("/{project_id}/artifacts", response_model=list[ArtifactOut])
def get_artifacts_for_project(
    request: Request, project_id: UUID, identity: Identity = IdentityDep
) -> list[ArtifactOut]:
    SessionLocal = request.app.state.SessionLocal
    with session_scope(SessionLocal) as session:
        if (
            get_project_row(
                session=session, tenant_id=_tenant_uuid(identity), project_id=project_id
            )
            is None
        ):
            raise HTTPException(status_code=404, detail="project not found")
        rows = list_artifacts(
            session=session, tenant_id=_tenant_uuid(identity), project_id=project_id
        )
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
