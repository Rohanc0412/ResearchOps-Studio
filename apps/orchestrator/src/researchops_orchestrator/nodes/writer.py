"""
Writer node - drafts the report with inline citations.

Generates markdown text with [CITE:snippet_id] citations.
Uses a simple template-based approach (can be enhanced with LLM later).
"""

from __future__ import annotations

import logging
import os
import random

from sqlalchemy.orm import Session

from researchops_core.observability import emit_run_event, instrument_node
from researchops_core.orchestrator.state import OrchestratorState
from researchops_llm import LLMError, get_llm_client

logger = logging.getLogger(__name__)


def _print_llm_exchange(label: str, section_id: str, content: str) -> None:
    if not content:
        return
    print(f"\n[draft llm {label} | section {section_id}]\n{content}\n", flush=True)


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
    print(f"\n[draft node start] run_id={state.run_id}\n", flush=True)
    outline = state.outline
    if not outline:
        raise ValueError("Outline not found in state")

    evidence_snippets = state.evidence_snippets
    vetted_sources = state.vetted_sources
    llm_client = None
    require_llm = os.getenv("LLM_DRAFT_REQUIRED", "true").strip().lower() in {"1", "true", "yes", "on"}
    try:
        llm_client = get_llm_client(state.llm_provider, state.llm_model)
    except LLMError as exc:
        logger.warning("llm_unavailable", extra={"error": str(exc)})
        if require_llm:
            raise ValueError("LLM drafting is required but the LLM client is unavailable.") from exc
    if llm_client:
        logger.info(
            "writer_llm_enabled",
            extra={
                "run_id": str(state.run_id),
                "llm_provider": state.llm_provider,
                "llm_model": state.llm_model,
            },
        )

    # Build draft
    draft_lines = []

    # Title
    draft_lines.append(f"# Research Report: {state.user_query}")
    draft_lines.append("")

    if require_llm and not llm_client:
        raise ValueError("LLM drafting is required but no LLM client is configured.")

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
            if llm_client:
                llm_text = _generate_section_with_llm(
                    llm_client,
                    section,
                    relevant_snippets,
                    vetted_sources,
                )
                if llm_text:
                    draft_lines.append(llm_text)
                    draft_lines.append("")
                    draft_lines.append("")
                    continue
                if require_llm:
                    raise ValueError(
                        f"LLM drafting failed for section {section.section_id}: {section.title}"
                    )

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
    logger.info(
        "writer_complete",
        extra={
            "run_id": str(state.run_id),
            "draft_version": state.draft_version,
            "draft_length": len(draft_text),
        },
    )

    return state


def _generate_section_with_llm(
    llm_client,
    section,
    snippets,
    sources,
    max_snippets: int = 3,
) -> str | None:
    selected = snippets[:max_snippets]
    if not selected:
        return None

    context_lines = []
    for snippet_ref in selected:
        source = next((s for s in sources if s.source_id == snippet_ref.source_id), None)
        source_label = source.title if source and source.title else "Unknown source"
        authors = _format_authors(source.authors) if source else "unknown authors"
        year = source.year if source and source.year else "n.d."
        snippet_text = snippet_ref.text.strip().replace("\n", " ")
        if len(snippet_text) > 300:
            snippet_text = snippet_text[:300].strip() + "..."
        context_lines.append(
            f"- [CITE:{snippet_ref.snippet_id}] {snippet_text} (Source: {source_label}, {authors}, {year})"
        )

    prompt = (
        f"Write 1-2 concise paragraphs for the section titled '{section.title}'.\n"
        f"Section description: {section.description}\n\n"
        "IMPORTANT RULES:\n"
        "1. Use ONLY the evidence snippets provided below\n"
        "2. Cite sources inline using the exact [CITE:...] tokens shown\n"
        "3. Paraphrase and synthesize; do NOT copy or quote the snippets verbatim\n"
        "4. Do NOT repeat phrases or use filler text\n"
        "5. Do NOT invent facts or add information not in the evidence\n"
        "6. Write clear, direct sentences without repetition\n\n"
        "Evidence:\n"
        + "\n".join(context_lines)
        + "\n\nWrite the section now using this evidence:"
    )
    system = (
        "You are a technical writer who creates clear, concise research prose from evidence snippets. "
        "You paraphrase and synthesize and never copy the snippets verbatim."
    )
    _print_llm_exchange("request", section.section_id, prompt)
    try:
        response = llm_client.generate(prompt, system=system, max_tokens=5000, temperature=0.7)
    except LLMError as exc:
        logger.warning("llm_section_generation_failed", extra={"error": str(exc)})
        return None

    text = response.strip()
    _print_llm_exchange("response", section.section_id, text)
    return text or None


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
    # Extract a complete sentence or up to 300 chars
    snippet_text = snippet_ref.text.strip()

    # Try to find a complete sentence
    sentences = snippet_text.split('. ')
    if len(sentences) > 0:
        # Take first complete sentence
        first_sentence = sentences[0].strip()
        if len(first_sentence) > 300:
            # Too long, truncate at word boundary
            truncated = first_sentence[:300].rsplit(' ', 1)[0]
            snippet_text = truncated + "..."
        else:
            snippet_text = first_sentence
            if not snippet_text.endswith('.'):
                snippet_text += "..."
    else:
        # No sentence breaks, just truncate
        if len(snippet_text) > 300:
            snippet_text = snippet_text[:300].rsplit(' ', 1)[0] + "..."

    # Citation marker
    citation = f"[CITE:{snippet_ref.snippet_id}]"

    # Template patterns with proper punctuation
    templates = [
        f"{snippet_text} {citation}",
        f"According to {_format_authors(source.authors)}, {snippet_text.lower()} {citation}",
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
