from __future__ import annotations

from typing import Literal

import os
import logging
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field
from researchops_api.middlewares.auth import IdentityDep
from researchops_api.schemas.truth import ProjectCreate, ProjectOut
from researchops_api.services.project_runs import (
    create_project_run,
    create_user_project,
    get_user_project,
    list_user_projects,
    patch_user_project,
)
from core.auth.identity import Identity
from core.auth.rbac import require_roles
from core.tenancy import tenant_uuid

from db.session import session_scope

router = APIRouter(prefix="/projects", tags=["projects"])

logger = logging.getLogger(__name__)



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
        return patch_user_project(
            session=session,
            tenant_id=_tenant_uuid(identity),
            project_id=project_id,
            user_id=identity.user_id,
            name=body.name,
            description=body.description,
        )


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
        return create_user_project(
            session=session,
            tenant_id=_tenant_uuid(identity),
            user_id=identity.user_id,
            name=body.name,
            description=body.description,
        )


@router.get("", response_model=list[ProjectOut], response_model_exclude_none=True)
def get_projects(request: Request, identity: Identity = IdentityDep) -> list[ProjectOut]:
    SessionLocal = request.app.state.SessionLocal
    with session_scope(SessionLocal) as session:
        return list_user_projects(
            session=session,
            tenant_id=_tenant_uuid(identity),
            user_id=identity.user_id,
        )


@router.get("/{project_id}", response_model=ProjectOut, response_model_exclude_none=True)
def get_project_by_id(
    request: Request, project_id: UUID, identity: Identity = IdentityDep
) -> ProjectOut:
    SessionLocal = request.app.state.SessionLocal
    with session_scope(SessionLocal) as session:
        p = get_user_project(
            session=session,
            tenant_id=_tenant_uuid(identity),
            project_id=project_id,
            user_id=identity.user_id,
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
        logger.info(
            "Research pipeline request received",
            extra={
                "event": "pipeline.request",
                "project_id": str(project_id),
                "question": question,
                "client_request_id": body.client_request_id,
                "budget_override": body.budget_override,
                "llm_provider": body.llm_provider,
                "llm_model": body.llm_model,
            },
        )
        run_id, status = create_project_run(
            request=request,
            session=session,
            tenant_id=_tenant_uuid(identity),
            project_id=project_id,
            identity=identity,
            question=question,
            client_request_id=body.client_request_id,
            budget_override=body.budget_override,
            llm_provider=body.llm_provider,
            llm_model=body.llm_model,
        )
        logger.info(
            "Research pipeline response sent",
            extra={
                "event": "pipeline.response",
                "project_id": str(project_id),
                "run_id": run_id,
                "status": status,
            },
        )
        return RunSetupResponse(run_id=run_id, status=status)


