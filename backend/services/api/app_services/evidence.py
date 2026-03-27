from __future__ import annotations

import base64
import json
from uuid import UUID

from db.models import SnapshotRow, SnippetRow, SourceRow
from db.repositories.artifacts import get_artifact_for_user
from db.repositories.corpus import get_source, source_to_api_payload
from fastapi import HTTPException
from fastapi.responses import Response
from retrieval import get_snippet_with_context
from schemas.truth import SourceOut
from sqlalchemy.orm import Session


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
        meta = artifact.metadata_json or {}
        filename = meta.get("filename") or f"artifact-{artifact.id}"

        if isinstance(meta.get("markdown"), str):
            return Response(
                content=meta["markdown"].encode("utf-8"),
                media_type="text/markdown; charset=utf-8",
                headers={"content-disposition": f'attachment; filename="{filename}"'},
            )

        if isinstance(meta.get("content_base64"), str):
            try:
                raw = base64.b64decode(meta["content_base64"])
                return Response(
                    content=raw,
                    media_type=artifact.mime_type or "application/octet-stream",
                    headers={"content-disposition": f'attachment; filename="{filename}"'},
                )
            except Exception:
                pass

        body = json.dumps(meta, indent=2).encode("utf-8")
        return Response(
            content=body,
            media_type="application/json",
            headers={"content-disposition": f'attachment; filename="{filename}.json"'},
        )
    raise HTTPException(
        status_code=501,
        detail="artifact download not implemented for this blob_ref",
    )


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
    except ValueError as exc:
        snippet = session.get(SnippetRow, snippet_id)
        if snippet is None or snippet.tenant_id != tenant_id:
            raise HTTPException(status_code=404, detail="snippet not found") from exc
        snapshot = session.get(SnapshotRow, snippet.snapshot_id)
        source = session.get(SourceRow, snapshot.source_id) if snapshot is not None else None
        if (
            snapshot is None
            or source is None
            or snapshot.tenant_id != tenant_id
            or source.tenant_id != tenant_id
        ):
            raise HTTPException(status_code=404, detail="snippet not found") from exc
        return {
            "snippet_id": str(snippet.id),
            "id": str(snippet.id),
            "source_id": str(source.id),
            "text": snippet.text,
            "title": source.title,
            "url": source.url,
            "risk_flags": [],
        }
