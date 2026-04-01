from __future__ import annotations

from uuid import UUID

from deps import DBDep
from app_services.evidence import download_user_artifact
from core.auth.identity import Identity
from core.tenancy import tenant_uuid
from fastapi import APIRouter, Request
from fastapi.responses import Response
from middlewares.auth import IdentityDep

router = APIRouter(prefix="/artifacts", tags=["artifacts"])


@router.get("/{artifact_id}/download")
async def download_artifact(
    request: Request,
    artifact_id: UUID,
    session: DBDep,
    identity: Identity = IdentityDep,
) -> Response:
    tenant_id = tenant_uuid(identity.tenant_id)
    return await download_user_artifact(
        session=session, tenant_id=tenant_id, artifact_id=artifact_id, user_id=identity.user_id
    )
