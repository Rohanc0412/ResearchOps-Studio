from __future__ import annotations

from uuid import UUID

from app_services.evidence import get_snippet_payload, get_source_out
from core.auth.identity import Identity
from core.tenancy import get_tenant_id
from deps import DBDep
from fastapi import APIRouter, Request
from middlewares.auth import IdentityDep
from schemas.truth import SourceOut

router = APIRouter(tags=["evidence"])


@router.get("/sources/{source_id}", response_model=SourceOut)
async def get_source(
    request: Request,
    source_id: UUID,
    session: DBDep,
    identity: Identity = IdentityDep,
) -> SourceOut:
    return await get_source_out(
        session=session,
        tenant_id=get_tenant_id(identity),
        source_id=source_id,
    )


@router.get("/snippets/{snippet_id}")
async def get_snippet(
    request: Request,
    snippet_id: UUID,
    session: DBDep,
    identity: Identity = IdentityDep,
    context_snippets: int = 2,
) -> dict:
    """
    Get snippet with surrounding context.

    Query params:
        context_snippets: Number of snippets before/after to include (default 2)
    """
    return await get_snippet_payload(
        session=session,
        tenant_id=get_tenant_id(identity),
        snippet_id=snippet_id,
        context_snippets=context_snippets,
    )
