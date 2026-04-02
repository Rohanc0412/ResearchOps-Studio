from __future__ import annotations

import logging
from typing import Literal
from uuid import UUID

from app_services.project_runs import (
    create_project_run,
    create_user_project,
    get_user_project,
    list_user_projects,
    patch_user_project,
)
from core.auth.identity import Identity
from core.auth.rbac import require_roles
from core.tenancy import get_tenant_id
from deps import DBDep
from fastapi import APIRouter, HTTPException, Request
from middlewares.auth import IdentityDep
from pydantic import BaseModel, ConfigDict, Field
from schemas.truth import ProjectCreate, ProjectOut

router = APIRouter(prefix="/projects", tags=["projects"])

logger = logging.getLogger(__name__)



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
    llm_provider: str | None = Field(default=None, pattern="^(hosted|bedrock)$")
    llm_model: str | None = Field(default=None, min_length=1)


class RunSetupResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    run_id: str
    status: str


@router.patch("/{project_id}", response_model=ProjectOut, response_model_exclude_none=True)
async def patch_project(
    request: Request, project_id: UUID, body: ProjectPatch, session: DBDep, identity: Identity = IdentityDep
) -> ProjectOut:
    try:
        require_roles("researcher", "admin", "owner")(identity)
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e)) from e

    return await patch_user_project(
        session=session,
        tenant_id=get_tenant_id(identity),
        project_id=project_id,
        user_id=identity.user_id,
        name=body.name,
        description=body.description,
    )


@router.post("", response_model=ProjectOut, response_model_exclude_none=True)
async def post_project(
    request: Request, body: ProjectCreate, session: DBDep, identity: Identity = IdentityDep
) -> ProjectOut:
    try:
        require_roles("researcher", "admin", "owner")(identity)
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e)) from e

    return await create_user_project(
        session=session,
        tenant_id=get_tenant_id(identity),
        user_id=identity.user_id,
        name=body.name,
        description=body.description,
    )


@router.get("", response_model=list[ProjectOut], response_model_exclude_none=True)
async def get_projects(request: Request, session: DBDep, identity: Identity = IdentityDep) -> list[ProjectOut]:
    return await list_user_projects(
        session=session,
        tenant_id=get_tenant_id(identity),
        user_id=identity.user_id,
    )


@router.get("/{project_id}", response_model=ProjectOut, response_model_exclude_none=True)
async def get_project_by_id(
    request: Request, project_id: UUID, session: DBDep, identity: Identity = IdentityDep
) -> ProjectOut:
    p = await get_user_project(
        session=session,
        tenant_id=get_tenant_id(identity),
        project_id=project_id,
        user_id=identity.user_id,
    )
    if p is None:
        raise HTTPException(status_code=404, detail="project not found")
    return ProjectOut.model_validate(p)


@router.post("/{project_id}/runs", response_model=RunSetupResponse)
async def post_run_for_project(
    request: Request, project_id: UUID, body: WebRunCreate, session: DBDep, identity: Identity = IdentityDep
):
    try:
        require_roles("researcher", "admin", "owner")(identity)
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e)) from e

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
    run_id, status = await create_project_run(
        request=request,
        session=session,
        tenant_id=get_tenant_id(identity),
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
