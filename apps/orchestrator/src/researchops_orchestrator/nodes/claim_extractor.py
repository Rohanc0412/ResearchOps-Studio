"""
ClaimExtractor node - extracts atomic claims from the draft.

Parses the draft and identifies factual claims that need evidence.
Extracts citations associated with each claim.
"""

from __future__ import annotations

import re

from sqlalchemy.orm import Session

from researchops_core.observability import instrument_node
from researchops_core.orchestrator.state import Claim, OrchestratorState


@instrument_node("claim_extraction")
def claim_extractor_node(state: OrchestratorState, session: Session) -> OrchestratorState:
    """
    Extract atomic claims from the draft.

    Strategy:
    1. Split draft into sentences
    2. Identify factual claims (sentences with citations)
    3. Extract citation references [CITE:snippet_id]
    4. Create Claim objects

    Args:
        state: Current orchestrator state
        session: Database session

    Returns:
        Updated state with extracted_claims
    """
    draft_text = state.draft_text
    if not draft_text:
        raise ValueError("Draft text not found in state")

    # Extract claims
    claims = []
    claim_counter = 0

    # Split into sections
    sections = draft_text.split("\n## ")

    for section_text in sections:
        if not section_text.strip():
            continue

        # Extract section ID if present
        section_id_match = re.match(r"^(\d+(?:\.\d+)*)\s+", section_text)
        section_id = section_id_match.group(1) if section_id_match else None

        # Split into sentences
        sentences = _split_into_sentences(section_text)

        for sentence in sentences:
            # Check if sentence contains citations
            citations = _extract_citations(sentence)

            # Skip if no content (e.g., headers)
            if len(sentence.strip()) < 20:
                continue

            # Determine if requires evidence
            requires_evidence = _requires_evidence(sentence)

            # Create claim
            claim_counter += 1
            claim = Claim(
                claim_id=f"claim_{claim_counter}",
                text=sentence.strip(),
                section_id=section_id,
                citation_ids=citations,
                requires_evidence=requires_evidence,
            )
            claims.append(claim)

    # Update state
    state.extracted_claims = claims

    return state


def _split_into_sentences(text: str) -> list[str]:
    """
    Split text into sentences.

    Simple regex-based approach.

    Args:
        text: Input text

    Returns:
        List of sentences
    """
    # Split on periods followed by whitespace
    # Simple approach: temporarily replace citations with placeholders
    citations = re.findall(r"\[CITE:[a-f0-9-]+\]", text)
    temp_text = text
    for i, citation in enumerate(citations):
        temp_text = temp_text.replace(citation, f"__CITE_{i}__")

    # Now split on ". "
    sentences = re.split(r"\.\s+", temp_text)

    # Restore citations
    restored_sentences = []
    for sentence in sentences:
        for i, citation in enumerate(citations):
            sentence = sentence.replace(f"__CITE_{i}__", citation)
        restored_sentences.append(sentence.strip())

    return [s for s in restored_sentences if s]


def _extract_citations(text: str) -> list[str]:
    """
    Extract citation markers from text.

    Pattern: [CITE:snippet_id]

    Args:
        text: Input text

    Returns:
        List of snippet IDs (UUIDs as strings)
    """
    # Pattern: [CITE:uuid]
    pattern = r"\[CITE:([a-f0-9-]+)\]"
    matches = re.findall(pattern, text)

    return matches


def _requires_evidence(sentence: str) -> bool:
    """
    Determine if a sentence makes a factual claim requiring evidence.

    Heuristic:
    - Contains citation -> requires evidence
    - Contains factual indicators -> requires evidence
    - Is a header or meta-statement -> does not require evidence

    Args:
        sentence: Input sentence

    Returns:
        True if requires evidence
    """
    # Already has citations
    if "[CITE:" in sentence:
        return True

    # Factual indicators
    factual_patterns = [
        r"\bresearch\b",
        r"\bstud(y|ies)\b",
        r"\bevidence\b",
        r"\bresults?\b",
        r"\bfinding(s)?\b",
        r"\bshow(s|ed|n)?\b",
        r"\bdemonstrate[ds]?\b",
        r"\bprove[ds]?\b",
        r"\bindicate[ds]?\b",
        r"\bsuggest[s]?\b",
        r"\breport[s|ed]?\b",
    ]

    sentence_lower = sentence.lower()
    for pattern in factual_patterns:
        if re.search(pattern, sentence_lower):
            return True

    # Headers (start with #)
    if sentence.strip().startswith("#"):
        return False

    # Short meta-statements
    if len(sentence) < 40:
        return False

    # Default: does not require evidence
    return False
