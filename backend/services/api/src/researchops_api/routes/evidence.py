from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, HTTPException, Request

from researchops_api.middlewares.auth import IdentityDep
from researchops_api.schemas.truth import SourceOut
from researchops_api.services.evidence import get_snippet_payload, get_source_out
from researchops_core.auth.identity import Identity
from researchops_core.tenancy import tenant_uuid
from db.session import session_scope

router = APIRouter(tags=["evidence"])



def _tenant_uuid(identity: Identity) -> UUID:
    return tenant_uuid(identity.tenant_id)


@router.get("/sources/{source_id}", response_model=SourceOut)
def get_source(request: Request, source_id: UUID, identity: Identity = IdentityDep) -> SourceOut:
    SessionLocal = request.app.state.SessionLocal
    with session_scope(SessionLocal) as session:
        return get_source_out(session=session, tenant_id=_tenant_uuid(identity), source_id=source_id)


@router.get("/snippets/{snippet_id}")
def get_snippet(request: Request, snippet_id: UUID, identity: Identity = IdentityDep, context_snippets: int = 2) -> dict:
    """
    Get snippet with surrounding context.

    Query params:
        context_snippets: Number of snippets before/after to include (default 2)
    """
    SessionLocal = request.app.state.SessionLocal
    with session_scope(SessionLocal) as session:
        return get_snippet_payload(
            session=session,
            tenant_id=_tenant_uuid(identity),
            snippet_id=snippet_id,
            context_snippets=context_snippets,
        )


