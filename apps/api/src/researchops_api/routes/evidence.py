from __future__ import annotations

import logging
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field
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
from researchops_ingestion import get_embedding_provider, ingest_source
from researchops_retrieval import get_snippet_with_context, search_snippets

from db.models import SnippetRow, SnapshotRow, SourceRow
from db.services.truth import create_snapshot, create_snippets, list_snippets, upsert_source
from db.session import session_scope

router = APIRouter(tags=["evidence"])

logger = logging.getLogger(__name__)

# --- New Pydantic Schemas for Part 6 ---


class IngestSourceRequest(BaseModel):
    """Request to ingest a new source with full pipeline."""

    canonical_id: str = Field(..., description="Unique source identifier")
    source_type: str = Field(..., description="Type: paper, webpage, book, etc.")
    raw_content: str = Field(..., description="Raw text content (may contain HTML)")
    title: str | None = Field(None, description="Source title")
    authors: list[str] | None = Field(None, description="Author names")
    year: int | None = Field(None, description="Publication year")
    url: str | None = Field(None, description="Source URL")
    content_type: str | None = Field(None, description="MIME type")
    metadata: dict | None = Field(None, description="Additional metadata")
    max_chunk_chars: int = Field(1000, description="Max characters per chunk")
    overlap_chars: int = Field(100, description="Overlap between chunks")


class IngestSourceResponse(BaseModel):
    """Response from ingesting a source."""

    source_id: UUID
    snapshot_id: UUID
    snippet_count: int
    has_risk_flags: bool


class SearchRequest(BaseModel):
    """Semantic search request."""

    query: str = Field(..., description="Search query text")
    limit: int = Field(10, ge=1, le=100, description="Max results")
    min_similarity: float = Field(0.0, ge=0.0, le=1.0, description="Min similarity threshold")


class SearchResultOut(BaseModel):
    """Search result with snippet and source metadata."""

    snippet_id: UUID
    snippet_text: str
    snippet_index: int
    char_start: int | None
    char_end: int | None
    similarity: float
    source_id: UUID
    source_title: str | None
    source_type: str
    source_url: str | None
    snapshot_id: UUID
    snapshot_version: int


class SearchResponse(BaseModel):
    """Search results."""

    results: list[SearchResultOut]
    query: str
    count: int


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
        logger.info(
            "source_upserted",
            extra={"tenant_id": str(_tenant_uuid(identity)), "source_id": str(s.id)},
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
        logger.info(
            "snapshot_created",
            extra={
                "tenant_id": str(_tenant_uuid(identity)),
                "source_id": str(source_id),
                "snapshot_id": str(snap.id),
            },
        )
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
        logger.info(
            "snippets_created",
            extra={
                "tenant_id": str(_tenant_uuid(identity)),
                "snapshot_id": str(snapshot_id),
                "count": len(rows),
            },
        )
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
            logger.info(
                "snippet_context_loaded",
                extra={
                    "tenant_id": str(_tenant_uuid(identity)),
                    "snippet_id": str(snippet_id),
                    "context_snippets": context_snippets,
                },
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


# --- Part 6 New Endpoints ---


@router.post("/ingest", response_model=IngestSourceResponse)
def ingest_evidence(
    request: Request,
    body: IngestSourceRequest,
    identity: Identity = IdentityDep,
) -> IngestSourceResponse:
    """
    Ingest a new source with full pipeline (Part 6).

    This endpoint:
    1. Creates or retrieves source by canonical_id
    2. Creates an immutable snapshot
    3. Sanitizes content (removes HTML, detects prompt injection)
    4. Chunks into snippets with stable offsets
    5. Generates embeddings for semantic search
    6. Stores everything in database

    Requires: researcher, admin, or owner role
    """
    try:
        require_roles("researcher", "admin", "owner")(identity)
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e)) from e

    SessionLocal = request.app.state.SessionLocal

    with session_scope(SessionLocal) as session:
        # Use configured embedding provider (local or API-backed).
        embedding_provider = get_embedding_provider()

        logger.info(
            "ingest_request",
            extra={
                "tenant_id": str(_tenant_uuid(identity)),
                "canonical_id": body.canonical_id,
                "source_type": body.source_type,
            },
        )
        result = ingest_source(
            session=session,
            tenant_id=_tenant_uuid(identity),
            canonical_id=body.canonical_id,
            source_type=body.source_type,
            raw_content=body.raw_content,
            embedding_provider=embedding_provider,
            title=body.title,
            authors=body.authors,
            year=body.year,
            url=body.url,
            content_type=body.content_type,
            metadata=body.metadata,
            max_chunk_chars=body.max_chunk_chars,
            overlap_chars=body.overlap_chars,
        )

        logger.info(
            "ingest_complete",
            extra={
                "tenant_id": str(_tenant_uuid(identity)),
                "source_id": str(result.source_id),
                "snapshot_id": str(result.snapshot_id),
                "snippet_count": result.snippet_count,
            },
        )
        return IngestSourceResponse(
            source_id=result.source_id,
            snapshot_id=result.snapshot_id,
            snippet_count=result.snippet_count,
            has_risk_flags=result.has_risk_flags,
        )


@router.post("/search", response_model=SearchResponse)
def search_evidence(
    request: Request,
    body: SearchRequest,
    identity: Identity = IdentityDep,
) -> SearchResponse:
    """
    Semantic search for snippets using pgvector cosine similarity (Part 6).

    This endpoint:
    1. Embeds the query text
    2. Performs cosine similarity search in pgvector
    3. Returns ranked snippets with source metadata
    """
    SessionLocal = request.app.state.SessionLocal

    with session_scope(SessionLocal) as session:
        # Embed query using configured provider.
        embedding_provider = get_embedding_provider()
        query_embedding = embedding_provider.embed_texts([body.query])[0]

        # Search
        results = search_snippets(
            session=session,
            tenant_id=_tenant_uuid(identity),
            query_embedding=query_embedding,
            embedding_model=embedding_provider.model_name,
            limit=body.limit,
            min_similarity=body.min_similarity,
        )

        logger.info(
            "search_complete",
            extra={
                "tenant_id": str(_tenant_uuid(identity)),
                "query": body.query,
                "count": len(results),
            },
        )
        return SearchResponse(
            results=[
                SearchResultOut(
                    snippet_id=r["snippet_id"],
                    snippet_text=r["snippet_text"],
                    snippet_index=r["snippet_index"],
                    char_start=r["char_start"],
                    char_end=r["char_end"],
                    similarity=r["similarity"],
                    source_id=r["source_id"],
                    source_title=r["source_title"],
                    source_type=r["source_type"],
                    source_url=r["source_url"],
                    snapshot_id=r["snapshot_id"],
                    snapshot_version=r["snapshot_version"],
                )
                for r in results
            ],
            query=body.query,
            count=len(results),
        )
