from __future__ import annotations

from uuid import UUID

from app_services.evidence import download_user_artifact
from core.auth.identity import Identity
from core.tenancy import tenant_uuid
from db.session import session_scope
from fastapi import APIRouter, Request
from fastapi.responses import Response
from middlewares.auth import IdentityDep

router = APIRouter(prefix="/artifacts", tags=["artifacts"])


@router.get("/{artifact_id}/download")
def download_artifact(
    request: Request,
    artifact_id: UUID,
    identity: Identity = IdentityDep,
) -> Response:
    SessionLocal = request.app.state.SessionLocal
    tenant_id = tenant_uuid(identity.tenant_id)
    with session_scope(SessionLocal) as session:
        return download_user_artifact(
            session=session, tenant_id=tenant_id, artifact_id=artifact_id, user_id=identity.user_id
        )

