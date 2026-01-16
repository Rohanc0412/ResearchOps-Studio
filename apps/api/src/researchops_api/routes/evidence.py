from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, HTTPException, Request
from sqlalchemy import select

from researchops_api.middlewares.auth import IdentityDep
from researchops_api.schemas.truth import (
    SnapshotCreate,
    SnapshotOut,
    SnippetCreate,
    SnippetOut,
    SourceOut,
    SourceUpsert,
)
from researchops_core.auth.identity import Identity
from researchops_core.auth.rbac import require_roles
from researchops_core.tenancy import tenant_uuid

from db.models import SnippetRow, SnapshotRow, SourceRow
from db.services.truth import create_snapshot, create_snippets, list_snippets, upsert_source
from db.session import session_scope

router = APIRouter(tags=["evidence"])


def _tenant_uuid(identity: Identity) -> UUID:
    return tenant_uuid(identity.tenant_id)


@router.post("/sources:upsert", response_model=SourceOut)
def post_sources_upsert(
    request: Request, body: SourceUpsert, identity: Identity = IdentityDep
) -> SourceOut:
    try:
        require_roles("researcher", "admin", "owner")(identity)
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e)) from e

    SessionLocal = request.app.state.SessionLocal
    with session_scope(SessionLocal) as session:
        s = upsert_source(
            session=session,
            tenant_id=_tenant_uuid(identity),
            canonical_id=body.canonical_id,
            source_type=body.source_type,
            title=body.title,
            authors_json=body.authors_json,
            year=body.year,
            url=body.url,
            metadata_json=body.metadata_json,
        )
        return SourceOut.model_validate(s)


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


@router.post("/sources/{source_id}/snapshots", response_model=SnapshotOut)
def post_snapshot(
    request: Request,
    source_id: UUID,
    body: SnapshotCreate,
    identity: Identity = IdentityDep,
) -> SnapshotOut:
    try:
        require_roles("researcher", "admin", "owner")(identity)
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e)) from e

    SessionLocal = request.app.state.SessionLocal
    with session_scope(SessionLocal) as session:
        try:
            snap = create_snapshot(
                session=session,
                tenant_id=_tenant_uuid(identity),
                source_id=source_id,
                content_type=body.content_type,
                blob_ref=body.blob_ref,
                sha256=body.sha256,
                size_bytes=body.size_bytes,
                metadata_json=body.metadata_json,
            )
        except ValueError as e:
            raise HTTPException(status_code=404, detail=str(e)) from e
        return SnapshotOut.model_validate(snap)


@router.post("/snapshots/{snapshot_id}/snippets", response_model=list[SnippetOut])
def post_snippets(
    request: Request,
    snapshot_id: UUID,
    body: list[SnippetCreate],
    identity: Identity = IdentityDep,
) -> list[SnippetOut]:
    try:
        require_roles("researcher", "admin", "owner")(identity)
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e)) from e

    SessionLocal = request.app.state.SessionLocal
    with session_scope(SessionLocal) as session:
        try:
            rows = create_snippets(
                session=session,
                tenant_id=_tenant_uuid(identity),
                snapshot_id=snapshot_id,
                snippets=[s.model_dump() for s in body],
            )
        except ValueError as e:
            raise HTTPException(status_code=404, detail=str(e)) from e
        return [SnippetOut.model_validate(r) for r in rows]


@router.get("/snapshots/{snapshot_id}/snippets", response_model=list[SnippetOut])
def get_snippets(
    request: Request, snapshot_id: UUID, identity: Identity = IdentityDep
) -> list[SnippetOut]:
    SessionLocal = request.app.state.SessionLocal
    with session_scope(SessionLocal) as session:
        rows = list_snippets(
            session=session, tenant_id=_tenant_uuid(identity), snapshot_id=snapshot_id
        )
        return [SnippetOut.model_validate(r) for r in rows]


@router.get("/snippets/{snippet_id}")
def get_snippet(request: Request, snippet_id: UUID, identity: Identity = IdentityDep) -> dict:
    SessionLocal = request.app.state.SessionLocal
    with session_scope(SessionLocal) as session:
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
