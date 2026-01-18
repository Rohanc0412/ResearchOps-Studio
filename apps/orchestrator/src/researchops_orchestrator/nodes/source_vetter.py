"""
SourceVetter node - filters low-quality sources and ranks remaining.

Assigns quality scores based on:
- Recency (newer is better)
- Citation count (if available)
- Venue prestige (if available)
- Content length (longer abstracts suggest more substance)
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from researchops_core.observability import instrument_node
from researchops_core.orchestrator.state import OrchestratorState, SourceRef


@instrument_node("source_vetting")
def source_vetter_node(
    state: OrchestratorState, session: Session, top_k: int = 15
) -> OrchestratorState:
    """
    Filter and rank sources by quality.

    Strategy:
    1. Assign quality scores based on metadata
    2. Filter out very low-quality sources
    3. Keep top K sources

    Args:
        state: Current orchestrator state
        session: Database session
        top_k: Number of top sources to keep

    Returns:
        Updated state with vetted_sources
    """
    sources = state.retrieved_sources

    # Assign quality scores
    scored_sources = []
    for source in sources:
        score = _calculate_quality_score(source)
        source.quality_score = score
        scored_sources.append(source)

    # Sort by score (descending)
    scored_sources.sort(key=lambda s: s.quality_score, reverse=True)

    # Filter: keep sources with score > 0.3
    filtered_sources = [s for s in scored_sources if s.quality_score > 0.3]

    # Take top K
    vetted_sources = filtered_sources[:top_k]

    # Update state
    state.vetted_sources = vetted_sources

    return state


def _calculate_quality_score(source: SourceRef) -> float:
    """
    Calculate quality score for a source.

    Scoring factors:
    - Recency: 0-0.4 (based on year)
    - Has PDF: +0.2
    - Has authors: +0.1
    - From specific connector: arXiv +0.1, OpenAlex +0.2
    - Content available: +0.2

    Args:
        source: Source to score

    Returns:
        Quality score between 0.0 and 1.0
    """
    score = 0.0

    # Recency (0-0.4)
    if source.year:
        current_year = 2026
        years_old = current_year - source.year
        if years_old <= 2:
            score += 0.4
        elif years_old <= 5:
            score += 0.3
        elif years_old <= 10:
            score += 0.2
        else:
            score += 0.1

    # Has PDF
    if source.pdf_url:
        score += 0.2

    # Has authors
    if source.authors and len(source.authors) > 0:
        score += 0.1

    # Connector quality
    if source.connector == "openalex":
        score += 0.2  # OpenAlex has good metadata
    elif source.connector == "arxiv":
        score += 0.1  # arXiv is reliable but preprints

    # Has URL (basic quality indicator)
    if source.url:
        score += 0.1

    # Cap at 1.0
    return min(score, 1.0)
