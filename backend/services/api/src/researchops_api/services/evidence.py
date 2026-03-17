from __future__ import annotations

import json
from uuid import UUID

from fastapi import HTTPException
from fastapi.responses import Response
from sqlalchemy.orm import Session

from db.models import SnapshotRow, SnippetRow, SourceRow
from db.repositories.artifacts import get_artifact_for_user
from db.repositories.corpus import get_source, source_to_api_payload
from researchops_api.schemas.truth import SourceOut
from researchops_retrieval import get_snippet_with_context


def download_user_artifact(
    *,
    session: Session,
    tenant_id: UUID,
    artifact_id: UUID,
    user_id: str,
) -> Response:
    artifact = get_artifact_for_user(
        session=session, tenant_id=tenant_id, artifact_id=artifact_id, created_by=user_id
    )
    if artifact is None:
        raise HTTPException(status_code=404, detail="artifact not found")
    if artifact.blob_ref.startswith("inline://"):
        body = json.dumps(artifact.metadata_json or {}, indent=2).encode("utf-8")
        return Response(
            content=body,
            media_type="application/json",
            headers={"content-disposition": f'attachment; filename="artifact-{artifact.id}.json"'},
        )
    raise HTTPException(status_code=501, detail="artifact download not implemented for this blob_ref")


def get_source_out(*, session: Session, tenant_id: UUID, source_id: UUID) -> SourceOut:
    row = get_source(session, tenant_id=tenant_id, source_id=source_id)
    if row is None:
        raise HTTPException(status_code=404, detail="source not found")
    return SourceOut.model_validate(source_to_api_payload(row))


def get_snippet_payload(
    *,
    session: Session,
    tenant_id: UUID,
    snippet_id: UUID,
    context_snippets: int,
) -> dict:
    try:
        return get_snippet_with_context(
            session=session,
            tenant_id=tenant_id,
            snippet_id=snippet_id,
            context_snippets=context_snippets,
        )
    except ValueError:
        snippet = session.get(SnippetRow, snippet_id)
        if snippet is None or snippet.tenant_id != tenant_id:
            raise HTTPException(status_code=404, detail="snippet not found")
        snapshot = session.get(SnapshotRow, snippet.snapshot_id)
        source = session.get(SourceRow, snapshot.source_id) if snapshot is not None else None
        if snapshot is None or source is None or snapshot.tenant_id != tenant_id or source.tenant_id != tenant_id:
            raise HTTPException(status_code=404, detail="snippet not found")
        return {
            "snippet_id": str(snippet.id),
            "id": str(snippet.id),
            "source_id": str(source.id),
            "text": snippet.text,
            "title": source.title,
            "url": source.url,
            "risk_flags": [],
        }
