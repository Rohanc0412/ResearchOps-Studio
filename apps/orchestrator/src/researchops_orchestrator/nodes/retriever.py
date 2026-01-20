"""
Retriever node - retrieves sources and evidence using connectors.

Uses the Part 7 connectors (OpenAlex, arXiv) to retrieve sources.
Ingests sources into the database and extracts evidence snippets.
"""

from __future__ import annotations

import logging
import os
import time
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy.orm import Session

from db.models.snapshots import SnapshotRow
from db.models.snippet_embeddings import SnippetEmbeddingRow
from db.models.snippets import SnippetRow
from db.models.sources import SourceRow
from researchops_connectors import ArXivConnector, OpenAlexConnector, hybrid_retrieve
from researchops_core.observability import emit_run_event, instrument_node
from researchops_core.orchestrator.state import (
    EvidenceSnippetRef,
    OrchestratorState,
    SourceRef,
)
from researchops_ingestion import get_embedding_provider, ingest_source

logger = logging.getLogger(__name__)


@instrument_node("retrieve")
def retriever_node(
    state: OrchestratorState, session: Session, max_sources: int = 20
) -> OrchestratorState:
    """
    Retrieve sources and evidence snippets.

    Strategy:
    1. Use generated queries with connectors
    2. Hybrid retrieval (keyword + dedup)
    3. Ingest top sources into database
    4. Extract evidence snippets with embeddings

    Args:
        state: Current orchestrator state
        session: Database session
        max_sources: Maximum sources to retrieve

    Returns:
        Updated state with retrieved_sources and evidence_snippets
    """
    logger.info(
        "retriever_start",
        extra={
            "run_id": str(state.run_id),
            "query_count": len(state.generated_queries),
            "max_sources": max_sources,
        },
    )
    # Initialize connectors (OpenAlex + arXiv only)
    openalex = OpenAlexConnector(email=os.getenv("OPENALEX_EMAIL"))
    arxiv = ArXivConnector()
    connectors = [openalex, arxiv]
    embedding_provider = get_embedding_provider()
    total_queries = min(len(state.generated_queries), 10)
    logger.info(
        "retriever_init",
        extra={
            "run_id": str(state.run_id),
            "connectors": [c.name for c in connectors],
            "embedding_model": embedding_provider.model_name,
            "embedding_dims": embedding_provider.dimensions,
            "total_queries": total_queries,
        },
    )

    # Retrieve sources for each query
    all_sources = []
    total_keyword = 0
    total_vector = 0
    total_candidates = 0
    connectors_used = set()
    for i, query in enumerate(state.generated_queries[:total_queries]):  # Limit to top 10 queries
        query_start = time.monotonic()
        logger.info(
            "retriever_query_start",
            extra={
                "run_id": str(state.run_id),
                "query_index": i + 1,
                "total_queries": total_queries,
                "query": query,
            },
        )
        # Progress event
        emit_run_event(
            session=session,
            tenant_id=state.tenant_id,
            run_id=state.run_id,
            event_type="progress",
            stage="retrieve",
            data={
                "query": query,
                "query_index": i + 1,
                "total_queries": total_queries,
            },
        )

        # Hybrid retrieval
        result = hybrid_retrieve(
            connectors=connectors,
            query=query,
            session=session,
            tenant_id=state.tenant_id,
            embedding_provider=embedding_provider,
            max_final_results=max_sources // 2,  # Get fewer per query to diversify
        )

        query_duration_ms = int((time.monotonic() - query_start) * 1000)
        logger.info(
            "retriever_query_complete",
            extra={
                "run_id": str(state.run_id),
                "query_index": i + 1,
                "total_queries": total_queries,
                "query": query,
                "duration_ms": query_duration_ms,
                "keyword_count": result.keyword_count,
                "vector_count": result.vector_count,
                "total_candidates": result.total_candidates,
                "final_count": result.final_count,
                "connectors_used": result.connectors_used,
            },
        )

        all_sources.extend(result.sources)
        total_keyword += result.keyword_count
        total_vector += result.vector_count
        total_candidates += result.total_candidates
        connectors_used.update(result.connectors_used)

    # Deduplicate across all queries
    from researchops_connectors import deduplicate_sources

    deduped_sources, dedup_stats = deduplicate_sources(all_sources)

    # Limit to max_sources
    deduped_sources = deduped_sources[:max_sources]
    logger.info(
        "retriever_dedup_complete",
        extra={
            "run_id": str(state.run_id),
            "total_sources_retrieved": len(all_sources),
            "deduped_sources": len(deduped_sources),
            "duplicates_removed": dedup_stats.duplicates_removed,
            "by_identifier": dedup_stats.by_identifier,
        },
    )

    # Emit progress
    top_sources = [
        {
            "title": source.title,
            "connector": source.connector,
            "year": source.year,
            "url": source.url,
            "canonical_id": source.to_canonical_string(),
        }
        for source in deduped_sources[:5]
    ]
    emit_run_event(
        session=session,
        tenant_id=state.tenant_id,
        run_id=state.run_id,
        event_type="progress",
        stage="retrieve",
        data={
            "total_sources_retrieved": len(all_sources),
            "total_candidates": total_candidates,
            "keyword_candidates": total_keyword,
            "vector_candidates": total_vector,
            "duplicates_removed": dedup_stats.duplicates_removed,
            "final_source_count": len(deduped_sources),
            "connectors_used": sorted(connectors_used),
            "top_sources": top_sources,
        },
    )
    logger.info(
        "retriever_summary",
        extra={
            "run_id": str(state.run_id),
            "total_sources_retrieved": len(all_sources),
            "duplicates_removed": dedup_stats.duplicates_removed,
            "final_source_count": len(deduped_sources),
        },
    )

    # Ingest sources into database
    source_refs = []
    evidence_snippets = []

    for i, source in enumerate(deduped_sources):
        # Ingest source
        canonical_id_str = source.to_canonical_string()
        logger.info(
            "retriever_source_start",
            extra={
                "run_id": str(state.run_id),
                "source_index": i + 1,
                "total_sources": len(deduped_sources),
                "canonical_id": canonical_id_str,
                "connector": source.connector,
                "title": (source.title or "")[:120],
            },
        )

        # Check if source already exists
        existing_source = (
            session.query(SourceRow)
            .filter(
                SourceRow.tenant_id == state.tenant_id,
                SourceRow.canonical_id == canonical_id_str,
            )
            .first()
        )

        if existing_source:
            source_id = existing_source.id
            logger.info(
                "retriever_source_exists",
                extra={
                    "run_id": str(state.run_id),
                    "canonical_id": canonical_id_str,
                    "source_id": str(source_id),
                },
            )
        else:
            # Ingest new source
            content = source.abstract or source.full_text or ""
            if not content:
                logger.info(
                    "retriever_source_skipped",
                    extra={
                        "run_id": str(state.run_id),
                        "canonical_id": canonical_id_str,
                        "reason": "no_content",
                    },
                )
                continue  # Skip sources with no content

            ingest_result = ingest_source(
                session=session,
                tenant_id=state.tenant_id,
                canonical_id=canonical_id_str,
                source_type=str(source.source_type.value),
                raw_content=content,
                embedding_provider=embedding_provider,
                title=source.title,
                authors=source.authors,
                year=source.year,
                url=source.url,
                pdf_url=source.pdf_url,
            )

            source_id = ingest_result.source_id
            logger.info(
                "retriever_source_ingested",
                extra={
                    "run_id": str(state.run_id),
                    "canonical_id": canonical_id_str,
                    "source_id": str(ingest_result.source_id),
                    "snapshot_id": str(ingest_result.snapshot_id),
                    "snippet_count": ingest_result.snippet_count,
                },
            )

        # Get source record
        source_record = session.query(SourceRow).get(source_id)
        if not source_record:
            logger.warning(
                "retriever_source_missing",
                extra={"run_id": str(state.run_id), "source_id": str(source_id)},
            )
            continue

        # Create SourceRef
        source_ref = SourceRef(
            source_id=source_id,
            canonical_id=canonical_id_str,
            title=source.title,
            authors=source.authors,
            year=source.year,
            url=source.url,
            pdf_url=source.pdf_url,
            connector=source.connector,
            quality_score=0.0,  # Will be set by SourceVetter
        )
        source_refs.append(source_ref)

        # Get evidence snippets for this source
        snippets = (
            session.query(SnippetRow)
            .join(SnapshotRow)
            .filter(
                SnapshotRow.tenant_id == state.tenant_id,
                SnapshotRow.source_id == source_id,
            )
            .all()
        )
        logger.info(
            "retriever_snippets_loaded",
            extra={
                "run_id": str(state.run_id),
                "source_id": str(source_id),
                "snippet_count": len(snippets),
            },
        )

        missing_embeddings = 0
        for snippet in snippets:
            # Get embedding
            embedding_record = (
                session.query(SnippetEmbeddingRow)
                .filter(SnippetEmbeddingRow.snippet_id == snippet.id)
                .first()
            )

            embedding_vector = None
            if embedding_record:
                embedding_vector = embedding_record.embedding
            else:
                missing_embeddings += 1

            evidence_ref = EvidenceSnippetRef(
                snippet_id=snippet.id,
                source_id=source_id,
                text=snippet.text,
                char_start=snippet.char_start,
                char_end=snippet.char_end,
                embedding_vector=embedding_vector,
            )
            evidence_snippets.append(evidence_ref)
        if missing_embeddings:
            logger.warning(
                "retriever_missing_embeddings",
                extra={
                    "run_id": str(state.run_id),
                    "source_id": str(source_id),
                    "missing_embeddings": missing_embeddings,
                },
            )

        # Progress event
        if (i + 1) % 5 == 0:
            emit_run_event(
                session=session,
                tenant_id=state.tenant_id,
                run_id=state.run_id,
                event_type="progress",
                stage="retrieve",
                data={
                    "sources_ingested": i + 1,
                    "total_sources": len(deduped_sources),
                },
            )

    # Update state
    state.retrieved_sources = source_refs
    state.evidence_snippets = evidence_snippets

    logger.info(
        "retriever_complete",
        extra={
            "run_id": str(state.run_id),
            "sources": len(source_refs),
            "snippets": len(evidence_snippets),
        },
    )

    return state
