"""
Retriever node - retrieves sources and evidence using connectors.

Uses the Part 7 connectors (OpenAlex, arXiv) to retrieve sources.
Ingests sources into the database and extracts evidence snippets.
"""

from __future__ import annotations

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
from researchops_ingestion import StubEmbeddingProvider, ingest_source


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
    # Initialize connectors
    openalex = OpenAlexConnector(email="researchops@example.com")
    arxiv = ArXivConnector()
    connectors = [openalex, arxiv]

    # Retrieve sources for each query
    all_sources = []
    for i, query in enumerate(state.generated_queries[:10]):  # Limit to top 10 queries
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
                "total_queries": min(len(state.generated_queries), 10),
            },
        )

        # Hybrid retrieval
        result = hybrid_retrieve(
            connectors=connectors,
            query=query,
            max_final_results=max_sources // 2,  # Get fewer per query to diversify
        )

        all_sources.extend(result.sources)

    # Deduplicate across all queries
    from researchops_connectors import deduplicate_sources

    deduped_sources, dedup_stats = deduplicate_sources(all_sources)

    # Limit to max_sources
    deduped_sources = deduped_sources[:max_sources]

    # Emit progress
    emit_run_event(
        session=session,
        tenant_id=state.tenant_id,
        run_id=state.run_id,
        event_type="progress",
        stage="retrieve",
        data={
            "total_sources_retrieved": len(all_sources),
            "duplicates_removed": dedup_stats.duplicates_removed,
            "final_source_count": len(deduped_sources),
        },
    )

    # Ingest sources into database
    embedding_provider = StubEmbeddingProvider()
    source_refs = []
    evidence_snippets = []

    for i, source in enumerate(deduped_sources):
        # Ingest source
        canonical_id_str = source.to_canonical_string()

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
            source_id = existing_source.source_id
        else:
            # Ingest new source
            content = source.abstract or source.full_text or ""
            if not content:
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

        # Get source record
        source_record = session.query(SourceRow).get(source_id)
        if not source_record:
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

        for snippet in snippets:
            # Get embedding
            embedding_record = (
                session.query(SnippetEmbeddingRow)
                .filter(SnippetEmbeddingRow.snippet_id == snippet.snippet_id)
                .first()
            )

            embedding_vector = None
            if embedding_record:
                embedding_vector = embedding_record.embedding

            evidence_ref = EvidenceSnippetRef(
                snippet_id=snippet.snippet_id,
                source_id=source_id,
                text=snippet.text,
                char_start=snippet.char_start,
                char_end=snippet.char_end,
                embedding_vector=embedding_vector,
            )
            evidence_snippets.append(evidence_ref)

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

    return state
