"""
Deduplication logic for retrieved sources.

Implements canonical ID priority:
DOI > PubMed > arXiv > OpenAlex > URL

This prevents:
- Duplicate papers from different connectors
- Repeated ingestion
- Wasted embedding budgets
"""

from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import dataclass

from researchops_connectors.base import RetrievedSource

logger = logging.getLogger(__name__)

@dataclass
class DeduplicationStats:
    """Statistics from deduplication process."""

    total_input: int
    """Total sources before deduplication."""

    total_output: int
    """Total sources after deduplication."""

    duplicates_removed: int
    """Number of duplicates removed."""

    by_identifier: dict[str, int]
    """Count of duplicates found by each identifier type."""

    connectors_merged: dict[str, int]
    """Count of sources from each connector after merge."""


def deduplicate_sources(
    sources: list[RetrievedSource],
    prefer_connector: str | None = None,
) -> tuple[list[RetrievedSource], DeduplicationStats]:
    """
    Deduplicate sources using canonical ID priority.

    Priority: DOI > PubMed > arXiv > OpenAlex > URL > Title hash

    When duplicates are found:
    1. Use highest priority identifier
    2. Merge metadata from all sources
    3. Prefer specific connector if specified

    Args:
        sources: List of sources to deduplicate
        prefer_connector: Prefer this connector's metadata when merging

    Returns:
        (deduplicated_sources, stats)

    Example:
        >>> sources = [source1, source2, source3]  # Some duplicates
        >>> deduped, stats = deduplicate_sources(sources)
        >>> print(f"Removed {stats.duplicates_removed} duplicates")
    """
    if not sources:
        logger.info("dedup_empty_input")
        return [], DeduplicationStats(
            total_input=0,
            total_output=0,
            duplicates_removed=0,
            by_identifier={},
            connectors_merged={},
        )

    # Group by canonical ID
    groups: dict[str, list[RetrievedSource]] = defaultdict(list)
    for source in sources:
        canonical_str = source.to_canonical_string()
        groups[canonical_str].append(source)

    # Merge each group
    deduplicated: list[RetrievedSource] = []
    duplicates_by_id: dict[str, int] = defaultdict(int)

    for canonical_id, group_sources in groups.items():
        if len(group_sources) == 1:
            # No duplicates
            deduplicated.append(group_sources[0])
        else:
            # Duplicates found - merge
            merged = _merge_sources(group_sources, prefer_connector)
            deduplicated.append(merged)

            # Track which ID type found the duplicate
            id_type = canonical_id.split(":")[0]
            duplicates_by_id[id_type] += len(group_sources) - 1

    # Collect stats
    connector_counts = defaultdict(int)
    for source in deduplicated:
        connector_counts[source.connector] += 1

    stats = DeduplicationStats(
        total_input=len(sources),
        total_output=len(deduplicated),
        duplicates_removed=len(sources) - len(deduplicated),
        by_identifier=dict(duplicates_by_id),
        connectors_merged=dict(connector_counts),
    )

    logger.info(
        "dedup_complete",
        extra={
            "total_input": stats.total_input,
            "total_output": stats.total_output,
            "duplicates_removed": stats.duplicates_removed,
            "by_identifier": stats.by_identifier,
        },
    )
    return deduplicated, stats


def _merge_sources(
    sources: list[RetrievedSource],
    prefer_connector: str | None = None,
) -> RetrievedSource:
    """
    Merge duplicate sources into one.

    Strategy:
    - Use most complete identifiers
    - Prefer specified connector's metadata
    - Merge keywords and metadata
    - Keep most recent retrieval time
    """
    # Sort by connector preference and completeness
    def sort_key(s: RetrievedSource) -> tuple[int, int]:
        # Prefer specified connector
        connector_priority = 0 if s.connector == prefer_connector else 1

        # Prefer sources with more complete data
        completeness = sum([
            bool(s.canonical_id.doi),
            bool(s.canonical_id.pubmed_id),
            bool(s.canonical_id.arxiv_id),
            bool(s.abstract),
            bool(s.full_text),
            bool(s.pdf_url),
            len(s.authors),
            len(s.keywords) if s.keywords else 0,
        ])

        return (connector_priority, -completeness)

    sources_sorted = sorted(sources, key=sort_key)
    primary = sources_sorted[0]

    # Merge identifiers (keep all non-None)
    merged_id = primary.canonical_id
    for source in sources_sorted[1:]:
        if not merged_id.doi and source.canonical_id.doi:
            merged_id.doi = source.canonical_id.doi
        if not merged_id.pubmed_id and source.canonical_id.pubmed_id:
            merged_id.pubmed_id = source.canonical_id.pubmed_id
        if not merged_id.arxiv_id and source.canonical_id.arxiv_id:
            merged_id.arxiv_id = source.canonical_id.arxiv_id
        if not merged_id.openalex_id and source.canonical_id.openalex_id:
            merged_id.openalex_id = source.canonical_id.openalex_id
        if not merged_id.url and source.canonical_id.url:
            merged_id.url = source.canonical_id.url

    # Merge keywords (union)
    all_keywords = set()
    for source in sources_sorted:
        if source.keywords:
            all_keywords.update(source.keywords)
    merged_keywords = list(all_keywords)[:10]  # Keep top 10

    # Use primary source metadata but fill in gaps
    merged_abstract = primary.abstract
    if not merged_abstract:
        for source in sources_sorted[1:]:
            if source.abstract:
                merged_abstract = source.abstract
                break

    merged_full_text = primary.full_text
    if not merged_full_text:
        for source in sources_sorted[1:]:
            if source.full_text:
                merged_full_text = source.full_text
                break

    merged_pdf_url = primary.pdf_url
    if not merged_pdf_url:
        for source in sources_sorted[1:]:
            if source.pdf_url:
                merged_pdf_url = source.pdf_url
                break

    # Merge extra metadata
    merged_extra = {}
    for source in sources_sorted:
        if source.extra_metadata:
            merged_extra[f"{source.connector}_metadata"] = source.extra_metadata

    # Create merged source
    return RetrievedSource(
        canonical_id=merged_id,
        title=primary.title,
        authors=primary.authors,
        year=primary.year,
        source_type=primary.source_type,
        abstract=merged_abstract,
        full_text=merged_full_text,
        url=primary.url,
        pdf_url=merged_pdf_url,
        connector=primary.connector,
        retrieved_at=max(s.retrieved_at for s in sources_sorted),
        venue=primary.venue,
        citations_count=primary.citations_count,
        keywords=merged_keywords if merged_keywords else None,
        extra_metadata=merged_extra if merged_extra else None,
    )


def filter_by_existing_ids(
    sources: list[RetrievedSource],
    existing_canonical_ids: set[str],
) -> tuple[list[RetrievedSource], list[RetrievedSource]]:
    """
    Filter sources that already exist in the database.

    Args:
        sources: Sources to filter
        existing_canonical_ids: Set of canonical ID strings already in DB

    Returns:
        (new_sources, existing_sources)

    Example:
        >>> existing_ids = {"doi:10.1234/abc", "arxiv:2401.12345"}
        >>> new, existing = filter_by_existing_ids(sources, existing_ids)
        >>> print(f"Found {len(new)} new sources, {len(existing)} already exist")
    """
    new_sources = []
    existing_sources = []

    for source in sources:
        canonical_str = source.to_canonical_string()
        if canonical_str in existing_canonical_ids:
            existing_sources.append(source)
        else:
            new_sources.append(source)

    return new_sources, existing_sources
