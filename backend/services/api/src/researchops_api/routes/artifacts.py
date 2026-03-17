from __future__ import annotations

import json
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response

from db.session import session_scope
from researchops_api.middlewares.auth import IdentityDep
from researchops_api.services.evidence import download_user_artifact
from researchops_core.auth.identity import Identity
from researchops_core.tenancy import tenant_uuid

router = APIRouter(prefix="/artifacts", tags=["artifacts"])


@router.get("/{artifact_id}/download")
def download_artifact(request: Request, artifact_id: UUID, identity: Identity = IdentityDep) -> Response:
    SessionLocal = request.app.state.SessionLocal
    tenant_id = tenant_uuid(identity.tenant_id)
    with session_scope(SessionLocal) as session:
        return download_user_artifact(
            session=session, tenant_id=tenant_id, artifact_id=artifact_id, user_id=identity.user_id
        )

