"""
Writer node - drafts the report with inline citations.

Generates markdown text with [CITE:snippet_id] citations.
Uses a simple template-based approach (can be enhanced with LLM later).
"""

from __future__ import annotations

import random

from sqlalchemy.orm import Session

from researchops_core.observability import emit_run_event, instrument_node
from researchops_core.orchestrator.state import OrchestratorState


@instrument_node("draft")
def writer_node(state: OrchestratorState, session: Session) -> OrchestratorState:
    """
    Draft the report with inline citations.

    Strategy:
    1. Follow the outline structure
    2. For each section, find relevant evidence snippets
    3. Generate text with [CITE:snippet_id] markers
    4. Use simple templates (can be enhanced with LLM)

    Args:
        state: Current orchestrator state
        session: Database session

    Returns:
        Updated state with draft_text
    """
    outline = state.outline
    if not outline:
        raise ValueError("Outline not found in state")

    evidence_snippets = state.evidence_snippets
    vetted_sources = state.vetted_sources

    # Build draft
    draft_lines = []

    # Title
    draft_lines.append(f"# Research Report: {state.user_query}")
    draft_lines.append("")

    # Process each section
    for i, section in enumerate(outline.sections):
        # Emit progress
        if i % 3 == 0:
            emit_run_event(
                session=session,
                tenant_id=state.tenant_id,
                run_id=state.run_id,
                event_type="progress",
                stage="draft",
                data={
                    "section_index": i + 1,
                    "total_sections": len(outline.sections),
                    "section_id": section.section_id,
                },
            )

        # Section header
        level = section.section_id.count(".") + 1
        header_prefix = "#" * (level + 1)  # +1 because title is already #
        draft_lines.append(f"{header_prefix} {section.section_id} {section.title}")
        draft_lines.append("")

        # Find relevant snippets for this section
        relevant_snippets = _find_relevant_snippets(
            section.required_evidence, evidence_snippets, max_snippets=5
        )

        # Generate section content
        if relevant_snippets:
            # Introduction sentence
            draft_lines.append(section.description + ".")
            draft_lines.append("")

            # Add evidence-based content
            for snippet_ref in relevant_snippets:
                # Get source info
                source = next(
                    (s for s in vetted_sources if s.source_id == snippet_ref.source_id), None
                )

                if source:
                    # Template-based sentence generation
                    sentence = _generate_sentence_from_snippet(snippet_ref, source)
                    draft_lines.append(sentence)
                    draft_lines.append("")

        else:
            # No evidence found
            draft_lines.append(
                f"This section requires further investigation into {section.required_evidence[0] if section.required_evidence else 'relevant topics'}."
            )
            draft_lines.append("")

        draft_lines.append("")  # Extra spacing between sections

    # Combine into final draft
    draft_text = "\n".join(draft_lines)

    # Update state
    state.draft_text = draft_text
    state.draft_version += 1

    return state


def _find_relevant_snippets(
    required_evidence: list[str], all_snippets: list, max_snippets: int = 5
) -> list:
    """
    Find snippets relevant to required evidence queries.

    Simple keyword matching (can be enhanced with semantic search).

    Args:
        required_evidence: List of evidence queries
        all_snippets: All available evidence snippets
        max_snippets: Maximum number to return

    Returns:
        List of relevant EvidenceSnippetRef objects
    """
    if not required_evidence or not all_snippets:
        return []

    # Score each snippet
    scored_snippets = []
    for snippet in all_snippets:
        score = 0.0

        # Check if any required evidence keywords appear in snippet
        snippet_text_lower = snippet.text.lower()
        for query in required_evidence:
            query_lower = query.lower()
            # Count keyword matches
            keywords = query_lower.split()
            matches = sum(1 for kw in keywords if kw in snippet_text_lower and len(kw) > 3)
            score += matches

        if score > 0:
            scored_snippets.append((score, snippet))

    # Sort by score
    scored_snippets.sort(key=lambda x: x[0], reverse=True)

    # Return top snippets
    return [snippet for _, snippet in scored_snippets[:max_snippets]]


def _generate_sentence_from_snippet(snippet_ref, source) -> str:
    """
    Generate a sentence incorporating a snippet with citation.

    Args:
        snippet_ref: EvidenceSnippetRef
        source: SourceRef

    Returns:
        Generated sentence with citation
    """
    # Extract a phrase from the snippet (first 100 chars)
    snippet_text = snippet_ref.text[:100].strip()
    if len(snippet_ref.text) > 100:
        snippet_text += "..."

    # Citation marker
    citation = f"[CITE:{snippet_ref.snippet_id}]"

    # Template patterns
    templates = [
        f"Research indicates that {snippet_text} {citation}.",
        f"According to {_format_authors(source.authors)}, {snippet_text} {citation}.",
        f"Studies have shown that {snippet_text} {citation}.",
        f"Evidence suggests that {snippet_text} {citation}.",
        f"As noted in recent work, {snippet_text} {citation}.",
    ]

    # Pick a random template
    return random.choice(templates)


def _format_authors(authors: list[str]) -> str:
    """
    Format author list for citation.

    Args:
        authors: List of author names

    Returns:
        Formatted author string
    """
    if not authors:
        return "researchers"

    if len(authors) == 1:
        return authors[0]
    elif len(authors) == 2:
        return f"{authors[0]} and {authors[1]}"
    else:
        return f"{authors[0]} et al."
