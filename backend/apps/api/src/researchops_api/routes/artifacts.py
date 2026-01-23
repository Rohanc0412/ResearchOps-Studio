from __future__ import annotations

import json
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response
from sqlalchemy import select

from db.models import ArtifactRow
from db.session import session_scope
from researchops_api.middlewares.auth import IdentityDep
from researchops_core.auth.identity import Identity
from researchops_core.tenancy import tenant_uuid

router = APIRouter(prefix="/artifacts", tags=["artifacts"])


@router.get("/{artifact_id}/download")
def download_artifact(request: Request, artifact_id: UUID, identity: Identity = IdentityDep) -> Response:
    SessionLocal = request.app.state.SessionLocal
    with session_scope(SessionLocal) as session:
        artifact = session.execute(
            select(ArtifactRow).where(
                ArtifactRow.id == artifact_id,
                ArtifactRow.tenant_id == tenant_uuid(identity.tenant_id),
            )
        ).scalar_one_or_none()
        if artifact is None:
            raise HTTPException(status_code=404, detail="artifact not found")

        # Minimal dev-friendly behavior: for `inline://` blob refs we return metadata as JSON.
        if artifact.blob_ref.startswith("inline://"):
            body = json.dumps(artifact.metadata_json or {}, indent=2).encode("utf-8")
            return Response(
                content=body,
                media_type="application/json",
                headers={
                    "content-disposition": f'attachment; filename="artifact-{artifact.id}.json"'
                },
            )

        raise HTTPException(status_code=501, detail="artifact download not implemented for this blob_ref")

