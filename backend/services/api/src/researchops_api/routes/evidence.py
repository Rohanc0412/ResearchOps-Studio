from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, HTTPException, Request
from sqlalchemy import select

from researchops_api.middlewares.auth import IdentityDep
from researchops_api.schemas.truth import SourceOut
from researchops_core.auth.identity import Identity
from researchops_core.tenancy import tenant_uuid
from researchops_retrieval import get_snippet_with_context

from db.models import SnippetRow, SnapshotRow, SourceRow
from db.session import session_scope

router = APIRouter(tags=["evidence"])



def _tenant_uuid(identity: Identity) -> UUID:
    return tenant_uuid(identity.tenant_id)


@router.get("/sources/{source_id}", response_model=SourceOut)
def get_source(request: Request, source_id: UUID, identity: Identity = IdentityDep) -> SourceOut:
    SessionLocal = request.app.state.SessionLocal
    with session_scope(SessionLocal) as session:
        row = session.execute(
            select(SourceRow).where(SourceRow.tenant_id == _tenant_uuid(identity), SourceRow.id == source_id)
        ).scalar_one_or_none()
        if row is None:
            raise HTTPException(status_code=404, detail="source not found")
        return SourceOut.model_validate(row)


@router.get("/snippets/{snippet_id}")
def get_snippet(request: Request, snippet_id: UUID, identity: Identity = IdentityDep, context_snippets: int = 2) -> dict:
    """
    Get snippet with surrounding context.

    Query params:
        context_snippets: Number of snippets before/after to include (default 2)
    """
    SessionLocal = request.app.state.SessionLocal
    with session_scope(SessionLocal) as session:
        try:
            result = get_snippet_with_context(
                session=session,
                tenant_id=_tenant_uuid(identity),
                snippet_id=snippet_id,
                context_snippets=context_snippets,
            )
            return result
        except ValueError:
            # Fallback to old implementation for compatibility
            snippet = session.execute(
                select(SnippetRow).where(SnippetRow.tenant_id == _tenant_uuid(identity), SnippetRow.id == snippet_id)
            ).scalar_one_or_none()
            if snippet is None:
                raise HTTPException(status_code=404, detail="snippet not found")

            snapshot = session.execute(
                select(SnapshotRow).where(
                    SnapshotRow.tenant_id == _tenant_uuid(identity), SnapshotRow.id == snippet.snapshot_id
                )
            ).scalar_one()
            source = session.execute(
                select(SourceRow).where(
                    SourceRow.tenant_id == _tenant_uuid(identity), SourceRow.id == snapshot.source_id
                )
            ).scalar_one()

            return {
                "snippet_id": str(snippet.id),
                "id": str(snippet.id),
                "source_id": str(source.id),
                "text": snippet.text,
                "title": source.title,
                "url": source.url,
                "risk_flags": [],
            }


