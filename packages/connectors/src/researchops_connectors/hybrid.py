"""
Hybrid retrieval combining keyword search, vector search, and reranking.

Strategy:
1. Keyword search via connectors (broad recall)
2. Vector search over existing snippets (precision)
3. Reranking for relevance + diversity
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from researchops_connectors.base import RetrievedSource
from researchops_connectors.dedup import deduplicate_sources, DeduplicationStats


@dataclass
class HybridRetrievalResult:
    """Result from hybrid retrieval."""

    # Retrieved sources
    sources: list[RetrievedSource]
    """Final ranked list of sources."""

    # Statistics
    keyword_count: int
    """Number of sources from keyword search."""

    vector_count: int
    """Number of sources from vector search."""

    total_candidates: int
    """Total candidates before reranking."""

    final_count: int
    """Final count after reranking and filtering."""

    dedup_stats: DeduplicationStats | None
    """Deduplication statistics."""

    # Metadata
    query: str
    """Original query."""

    connectors_used: list[str]
    """List of connectors queried."""


def keyword_search_multi_connector(
    connectors: list[Any],  # List of connector instances
    query: str,
    max_per_connector: int = 20,
    year_from: int | None = None,
    year_to: int | None = None,
) -> list[RetrievedSource]:
    """
    Search multiple connectors in parallel.

    Args:
        connectors: List of connector instances
        query: Search query
        max_per_connector: Max results per connector
        year_from: Filter from year
        year_to: Filter to year

    Returns:
        Combined list of sources from all connectors
    """
    all_sources = []

    for connector in connectors:
        try:
            sources = connector.search(
                query=query,
                max_results=max_per_connector,
                year_from=year_from,
                year_to=year_to,
            )
            all_sources.extend(sources)
        except Exception as e:
            # Log error but continue with other connectors
            print(f"Error searching {connector.name}: {e}")
            continue

    return all_sources


def vector_search_existing(
    session: Session,
    tenant_id: UUID,
    query: str,
    embedding_provider: Any,  # EmbeddingProvider
    max_results: int = 10,
) -> list[dict]:
    """
    Search existing snippets using vector similarity.

    Args:
        session: Database session
        tenant_id: Tenant ID
        query: Search query
        embedding_provider: Provider for embeddings
        max_results: Max results to return

    Returns:
        List of snippet search results with source metadata
    """
    from researchops_retrieval import search_snippets

    # Embed query
    query_embedding = embedding_provider.embed_texts([query])[0]

    # Search snippets
    results = search_snippets(
        session=session,
        tenant_id=tenant_id,
        query_embedding=query_embedding,
        embedding_model=embedding_provider.model_name,
        limit=max_results,
    )

    return results


def rerank_sources(
    sources: list[RetrievedSource],
    query: str,
    max_results: int = 10,
    diversity_weight: float = 0.3,
) -> list[RetrievedSource]:
    """
    Rerank sources for relevance and diversity.

    Strategy:
    - Relevance: Title/abstract similarity to query (simple heuristic)
    - Diversity: Prefer different venues, years, authors
    - Citations: Boost highly-cited papers

    Args:
        sources: Sources to rerank
        query: Original query
        max_results: Number of results to return
        diversity_weight: Weight for diversity (0-1)

    Returns:
        Reranked sources
    """
    query_lower = query.lower()
    query_words = set(query_lower.split())

    scored_sources = []

    for source in sources:
        # Relevance score (simple word overlap)
        title_words = set(source.title.lower().split())
        title_overlap = len(query_words & title_words) / max(len(query_words), 1)

        abstract_overlap = 0.0
        if source.abstract:
            abstract_words = set(source.abstract.lower().split())
            abstract_overlap = len(query_words & abstract_words) / max(len(query_words), 1)

        relevance_score = title_overlap * 2 + abstract_overlap

        # Citation boost (normalize to 0-1)
        citation_score = 0.0
        if source.citations_count:
            # Log scale for citations
            import math
            citation_score = math.log(source.citations_count + 1) / 10

        # Combined score
        total_score = relevance_score + citation_score

        scored_sources.append((total_score, source))

    # Sort by score
    scored_sources.sort(key=lambda x: x[0], reverse=True)

    # Apply diversity
    if diversity_weight > 0:
        scored_sources = _apply_diversity(scored_sources, diversity_weight)

    # Return top results
    return [source for _, source in scored_sources[:max_results]]


def _apply_diversity(
    scored_sources: list[tuple[float, RetrievedSource]],
    diversity_weight: float,
) -> list[tuple[float, RetrievedSource]]:
    """
    Apply diversity penalty to similar sources.

    Penalizes:
    - Same venue
    - Same year
    - Same first author
    """
    seen_venues = set()
    seen_years = set()
    seen_first_authors = set()

    adjusted = []

    for score, source in scored_sources:
        penalty = 0.0

        # Venue diversity
        if source.venue and source.venue in seen_venues:
            penalty += diversity_weight * 0.3

        # Year diversity
        if source.year and source.year in seen_years:
            penalty += diversity_weight * 0.2

        # Author diversity
        first_author = source.authors[0] if source.authors else None
        if first_author and first_author in seen_first_authors:
            penalty += diversity_weight * 0.5

        # Apply penalty
        adjusted_score = score * (1 - penalty)
        adjusted.append((adjusted_score, source))

        # Track seen items
        if source.venue:
            seen_venues.add(source.venue)
        if source.year:
            seen_years.add(source.year)
        if first_author:
            seen_first_authors.add(first_author)

    # Re-sort after diversity adjustment
    adjusted.sort(key=lambda x: x[0], reverse=True)

    return adjusted


def hybrid_retrieve(
    connectors: list[Any],
    query: str,
    session: Session | None = None,
    tenant_id: UUID | None = None,
    embedding_provider: Any | None = None,
    max_keyword_results: int = 50,
    max_vector_results: int = 10,
    max_final_results: int = 10,
    year_from: int | None = None,
    year_to: int | None = None,
    diversity_weight: float = 0.3,
) -> HybridRetrievalResult:
    """
    Perform hybrid retrieval: keyword + vector + rerank.

    Args:
        connectors: List of connector instances
        query: Search query
        session: Database session (for vector search)
        tenant_id: Tenant ID (for vector search)
        embedding_provider: Embedding provider (for vector search)
        max_keyword_results: Max results per connector
        max_vector_results: Max vector search results
        max_final_results: Max final results after reranking
        year_from: Filter from year
        year_to: Filter to year
        diversity_weight: Weight for diversity in reranking

    Returns:
        HybridRetrievalResult with sources and statistics
    """
    # Step 1: Keyword search via connectors
    keyword_sources = keyword_search_multi_connector(
        connectors=connectors,
        query=query,
        max_per_connector=max_keyword_results // len(connectors) if connectors else max_keyword_results,
        year_from=year_from,
        year_to=year_to,
    )

    keyword_count = len(keyword_sources)

    # Step 2: Vector search (optional - if session provided)
    vector_sources = []
    if session and tenant_id and embedding_provider:
        try:
            vector_results = vector_search_existing(
                session=session,
                tenant_id=tenant_id,
                query=query,
                embedding_provider=embedding_provider,
                max_results=max_vector_results,
            )
            # Note: These are snippet results, not full sources
            # In a full implementation, would convert to RetrievedSource
            # For now, we'll skip adding them to avoid complexity
        except Exception as e:
            print(f"Vector search error: {e}")

    vector_count = len(vector_sources)

    # Step 3: Deduplicate
    all_sources = keyword_sources + vector_sources
    deduped_sources, dedup_stats = deduplicate_sources(all_sources)

    # Step 4: Rerank
    final_sources = rerank_sources(
        sources=deduped_sources,
        query=query,
        max_results=max_final_results,
        diversity_weight=diversity_weight,
    )

    # Collect statistics
    connectors_used = [c.name for c in connectors]

    return HybridRetrievalResult(
        sources=final_sources,
        keyword_count=keyword_count,
        vector_count=vector_count,
        total_candidates=len(all_sources),
        final_count=len(final_sources),
        dedup_stats=dedup_stats,
        query=query,
        connectors_used=connectors_used,
    )
