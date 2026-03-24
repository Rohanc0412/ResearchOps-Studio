from __future__ import annotations

from uuid import UUID

from app_services.evidence import get_snippet_payload, get_source_out
from core.auth.identity import Identity
from core.tenancy import tenant_uuid
from db.session import session_scope
from fastapi import APIRouter, Request
from middlewares.auth import IdentityDep
from schemas.truth import SourceOut

router = APIRouter(tags=["evidence"])



def _tenant_uuid(identity: Identity) -> UUID:
    return tenant_uuid(identity.tenant_id)


@router.get("/sources/{source_id}", response_model=SourceOut)
def get_source(
    request: Request,
    source_id: UUID,
    identity: Identity = IdentityDep,
) -> SourceOut:
    SessionLocal = request.app.state.SessionLocal
    with session_scope(SessionLocal) as session:
        return get_source_out(
            session=session,
            tenant_id=_tenant_uuid(identity),
            source_id=source_id,
        )


@router.get("/snippets/{snippet_id}")
def get_snippet(
    request: Request,
    snippet_id: UUID,
    identity: Identity = IdentityDep,
    context_snippets: int = 2,
) -> dict:
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


