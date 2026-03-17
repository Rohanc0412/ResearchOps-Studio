"""
pgvector-based semantic search for snippets.

This module provides:
- Cosine similarity search using pgvector
- Multi-tenant safe queries
- Result ranking and filtering
- Source/snapshot metadata joining
"""

from __future__ import annotations

import math
from typing import TypedDict
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from db.models import SnippetEmbeddingRow, SnippetRow, SnapshotRow, SourceRow



class SearchResult(TypedDict):
    """A search result with snippet, source, and similarity score."""

    snippet_id: UUID
    """Snippet ID."""

    snippet_text: str
    """Snippet text content."""

    snippet_index: int
    """Index within snapshot."""

    char_start: int | None
    """Character offset in original content."""

    char_end: int | None
    """Character offset in original content."""

    similarity: float
    """Cosine similarity score (0-1, higher is better)."""

    source_id: UUID
    """Parent source ID."""

    source_title: str | None
    """Source title."""

    source_type: str
    """Source type (paper, webpage, etc.)."""

    source_canonical_id: str
    """Canonical identifier string for the source."""

    source_year: int | None
    """Source publication year."""

    source_authors: list
    """Source authors list."""

    source_url: str | None
    """Source URL."""

    snapshot_id: UUID
    """Parent snapshot ID."""

    snapshot_version: int
    """Snapshot version number."""


def search_snippets(
    *,
    session: Session,
    tenant_id: UUID,
    query_embedding: list[float],
    embedding_model: str,
    limit: int = 10,
    min_similarity: float = 0.0,
    source_ids: list[UUID] | None = None,
) -> list[SearchResult]:
    """
    Search for semantically similar snippets using pgvector cosine similarity.

    Args:
        session: Database session
        tenant_id: Tenant ID for multi-tenant isolation
        query_embedding: Query embedding vector
        embedding_model: Embedding model name to filter by
        limit: Maximum number of results to return
        min_similarity: Minimum similarity threshold (0-1)
        source_ids: Optional list of source IDs to filter the search space

    Returns:
        List of search results sorted by similarity (descending)

    Example:
        >>> from researchops_ingestion.embeddings import StubEmbeddingProvider
        >>> provider = StubEmbeddingProvider()
        >>> query_vec = provider.embed_texts(["machine learning"])[0]
        >>> results = search_snippets(
        ...     session=session,
        ...     tenant_id=tenant_id,
        ...     query_embedding=query_vec,
        ...     embedding_model=provider.model_name,
        ...     limit=5,
        ... )
        >>> len(results) <= 5
        True
    """
    # pgvector cosine similarity: 1 - (embedding <=> query_embedding)
    # This returns a value in [0, 2], where:
    # - 0 = identical vectors
    # - 1 = orthogonal
    # - 2 = opposite
    # We want: similarity = 1 - distance/2, so:
    # - identical → 1.0
    # - orthogonal → 0.5
    # - opposite → 0.0

    bind = session.get_bind()
    dialect = bind.dialect.name if bind else None

    def _cosine_sim(a: list[float], b: list[float]) -> float:
        if not a or not b:
            return 0.0
        if len(a) != len(b):
            return 0.0
        dot = sum(x * y for x, y in zip(a, b))
        norm_a = math.sqrt(sum(x * x for x in a))
        norm_b = math.sqrt(sum(y * y for y in b))
        if norm_a == 0.0 or norm_b == 0.0:
            return 0.0
        return max(0.0, min(1.0, dot / (norm_a * norm_b)))

    # Prefer pgvector cosine distance when available.
    if hasattr(SnippetEmbeddingRow.embedding, "cosine_distance"):
        distance_expr = SnippetEmbeddingRow.embedding.cosine_distance(query_embedding)
        similarity_expr = (1 - distance_expr / 2).label("similarity")
        order_expr = (1 - distance_expr / 2).desc()
    elif dialect == "postgresql":
        distance_expr = SnippetEmbeddingRow.embedding.op("<=>")(query_embedding)
        similarity_expr = (1 - distance_expr / 2).label("similarity")
        order_expr = (1 - distance_expr / 2).desc()
    else:
        query = (
            select(
                SnippetRow.id.label("snippet_id"),
                SnippetRow.text.label("snippet_text"),
                SnippetRow.snippet_index,
                SnippetRow.char_start,
                SnippetRow.char_end,
                SnippetEmbeddingRow.embedding.label("embedding"),
                SourceRow.id.label("source_id"),
                SourceRow.title.label("source_title"),
                SourceRow.source_type,
                SourceRow.canonical_id.label("source_canonical_id"),
                SourceRow.year.label("source_year"),
                SourceRow.authors_json.label("source_authors"),
                SourceRow.url.label("source_url"),
                SnapshotRow.id.label("snapshot_id"),
                SnapshotRow.snapshot_version,
            )
            .select_from(SnippetEmbeddingRow)
            .join(SnippetRow, SnippetRow.id == SnippetEmbeddingRow.snippet_id)
            .join(SnapshotRow, SnapshotRow.id == SnippetRow.snapshot_id)
            .join(SourceRow, SourceRow.id == SnapshotRow.source_id)
            .where(
                SnippetEmbeddingRow.tenant_id == tenant_id,
                SnippetEmbeddingRow.embedding_model == embedding_model,
            )
        )
        if source_ids:
            query = query.where(SourceRow.id.in_(source_ids))

        rows = session.execute(query).all()
        scored = []
        for row in rows:
            similarity = _cosine_sim(row.embedding or [], query_embedding)
            if similarity < min_similarity:
                continue
            scored.append((similarity, row))
        scored.sort(key=lambda item: item[0], reverse=True)
        results: list[SearchResult] = []
        for similarity, row in scored[:limit]:
            results.append(
                SearchResult(
                    snippet_id=row.snippet_id,
                    snippet_text=row.snippet_text,
                    snippet_index=row.snippet_index,
                    char_start=row.char_start,
                    char_end=row.char_end,
                    similarity=float(similarity),
                    source_id=row.source_id,
                    source_title=row.source_title,
                    source_type=row.source_type,
                    source_canonical_id=row.source_canonical_id,
                    source_year=row.source_year,
                    source_authors=row.source_authors,
                    source_url=row.source_url,
                    snapshot_id=row.snapshot_id,
                    snapshot_version=row.snapshot_version,
                )
            )
        return results

    # Build query with joins (pgvector path)
    query = (
        select(
            SnippetRow.id.label("snippet_id"),
            SnippetRow.text.label("snippet_text"),
            SnippetRow.snippet_index,
            SnippetRow.char_start,
            SnippetRow.char_end,
            similarity_expr,
            SourceRow.id.label("source_id"),
            SourceRow.title.label("source_title"),
            SourceRow.source_type,
            SourceRow.canonical_id.label("source_canonical_id"),
            SourceRow.year.label("source_year"),
            SourceRow.authors_json.label("source_authors"),
            SourceRow.url.label("source_url"),
            SnapshotRow.id.label("snapshot_id"),
            SnapshotRow.snapshot_version,
        )
        .select_from(SnippetEmbeddingRow)
        .join(SnippetRow, SnippetRow.id == SnippetEmbeddingRow.snippet_id)
        .join(SnapshotRow, SnapshotRow.id == SnippetRow.snapshot_id)
        .join(SourceRow, SourceRow.id == SnapshotRow.source_id)
        .where(
            SnippetEmbeddingRow.tenant_id == tenant_id,
            SnippetEmbeddingRow.embedding_model == embedding_model,
        )
        .order_by(order_expr)
        .limit(limit)
    )
    if source_ids:
        query = query.where(SourceRow.id.in_(source_ids))

    # Execute query
    rows = session.execute(query).all()

    # Convert to SearchResult dicts
    results: list[SearchResult] = []
    for row in rows:
        similarity = float(row.similarity)
        if similarity < min_similarity:
            continue

        results.append(
            SearchResult(
                snippet_id=row.snippet_id,
                snippet_text=row.snippet_text,
                snippet_index=row.snippet_index,
                char_start=row.char_start,
                char_end=row.char_end,
                similarity=similarity,
                source_id=row.source_id,
                source_title=row.source_title,
                source_type=row.source_type,
                source_canonical_id=row.source_canonical_id,
                source_year=row.source_year,
                source_authors=row.source_authors,
                source_url=row.source_url,
                snapshot_id=row.snapshot_id,
                snapshot_version=row.snapshot_version,
            )
        )

    return results


def get_snippet_with_context(
    *,
    session: Session,
    tenant_id: UUID,
    snippet_id: UUID,
    context_snippets: int = 2,
) -> dict:
    """
    Get a snippet along with surrounding context snippets.

    Args:
        session: Database session
        tenant_id: Tenant ID
        snippet_id: Target snippet ID
        context_snippets: Number of snippets before/after to include

    Returns:
        Dict with snippet, source, snapshot, and surrounding context

    Example:
        >>> result = get_snippet_with_context(
        ...     session=session,
        ...     tenant_id=tenant_id,
        ...     snippet_id=snippet_id,
        ...     context_snippets=1,
        ... )
        >>> "snippet" in result
        True
        >>> "context_before" in result
        True
    """
    # Get target snippet
    snippet = (
        session.query(SnippetRow)
        .filter(
            SnippetRow.tenant_id == tenant_id,
            SnippetRow.id == snippet_id,
        )
        .first()
    )

    if not snippet:
        raise ValueError(f"Snippet {snippet_id} not found for tenant {tenant_id}")

    # Get snapshot and source
    snapshot = session.query(SnapshotRow).filter(SnapshotRow.id == snippet.snapshot_id).one()
    source = session.query(SourceRow).filter(SourceRow.id == snapshot.source_id).one()

    # Get context snippets (before and after)
    all_snippets = (
        session.query(SnippetRow)
        .filter(
            SnippetRow.tenant_id == tenant_id,
            SnippetRow.snapshot_id == snippet.snapshot_id,
        )
        .order_by(SnippetRow.snippet_index)
        .all()
    )

    # Find position of target snippet
    target_idx = None
    for idx, s in enumerate(all_snippets):
        if s.id == snippet_id:
            target_idx = idx
            break

    if target_idx is None:
        context_before = []
        context_after = []
    else:
        start_idx = max(0, target_idx - context_snippets)
        end_idx = min(len(all_snippets), target_idx + context_snippets + 1)

        context_before = all_snippets[start_idx:target_idx]
        context_after = all_snippets[target_idx + 1 : end_idx]

    return {
        "snippet": {
            "id": snippet.id,
            "text": snippet.text,
            "snippet_index": snippet.snippet_index,
            "char_start": snippet.char_start,
            "char_end": snippet.char_end,
            "token_count": snippet.token_count,
            "risk_flags": snippet.risk_flags_json,
        },
        "source": {
            "id": source.id,
            "canonical_id": source.canonical_id,
            "type": source.source_type,
            "title": source.title,
            "authors": source.authors_json,
            "year": source.year,
            "url": source.url,
        },
        "snapshot": {
            "id": snapshot.id,
            "version": snapshot.snapshot_version,
            "retrieved_at": snapshot.retrieved_at.isoformat(),
            "sha256": snapshot.sha256,
        },
        "context_before": [
            {
                "id": s.id,
                "text": s.text,
                "snippet_index": s.snippet_index,
            }
            for s in context_before
        ],
        "context_after": [
            {
                "id": s.id,
                "text": s.text,
                "snippet_index": s.snippet_index,
            }
            for s in context_after
        ],
    }
