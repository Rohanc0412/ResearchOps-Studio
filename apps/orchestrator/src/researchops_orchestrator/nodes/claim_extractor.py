"""
ClaimExtractor node - extracts atomic claims from the draft.

Parses the draft and identifies factual claims that need evidence.
Extracts citations associated with each claim.
"""

from __future__ import annotations

import json
import logging
import os
import re

from sqlalchemy.orm import Session

from researchops_core.observability import instrument_node
from researchops_core.orchestrator.state import Claim, OrchestratorState
from researchops_llm import LLMError, get_llm_client

logger = logging.getLogger(__name__)


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

    llm_client = None
    require_llm = os.getenv("LLM_CLAIM_REQUIRED", "true").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
    try:
        llm_client = get_llm_client(state.llm_provider, state.llm_model)
    except LLMError as exc:
        logger.warning("llm_unavailable", extra={"error": str(exc)})
        if require_llm:
            raise ValueError("LLM claim extraction is required but unavailable.") from exc

    if llm_client:
        claims = _extract_claims_with_llm(draft_text, llm_client)
        if claims:
            state.extracted_claims = claims
            logger.info(
                "claim_extraction_llm_complete",
                extra={"run_id": str(state.run_id), "claims": len(claims)},
            )
            return state
        if require_llm:
            raise ValueError("LLM claim extraction failed.")

    if require_llm and not llm_client:
        raise ValueError("LLM claim extraction is required but no LLM client is configured.")

    claims = _extract_claims_rule_based(draft_text)

    state.extracted_claims = claims
    logger.info(
        "claim_extraction_complete",
        extra={"run_id": str(state.run_id), "claims": len(claims)},
    )

    return state


def _extract_claims_rule_based(draft_text: str) -> list[Claim]:
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
            citations = _extract_citations(sentence)
            if len(sentence.strip()) < 20:
                continue

            requires_evidence = _requires_evidence(sentence)
            claim_counter += 1
            claims.append(
                Claim(
                    claim_id=f"claim_{claim_counter}",
                    text=sentence.strip(),
                    section_id=section_id,
                    citation_ids=citations,
                    requires_evidence=requires_evidence,
                )
            )

    return claims


def _extract_json_list(text: str) -> list[dict] | None:
    text = text.strip()
    if text.startswith("```"):
        text = text.strip("`").strip()
    start = text.find("[")
    end = text.rfind("]")
    if start == -1 or end == -1 or end <= start:
        return None
    json_text = text[start : end + 1]
    try:
        data = json.loads(json_text)
    except json.JSONDecodeError:
        return None
    if not isinstance(data, list):
        return None
    return [item for item in data if isinstance(item, dict)]


def _extract_claims_with_llm(draft_text: str, llm_client) -> list[Claim] | None:
    prompt = (
        "Extract atomic factual claims from the draft below.\n"
        "Return ONLY a JSON array. Each item must contain:\n"
        '- "text": the full claim sentence (keep any [CITE:...] tokens)\n'
        '- "section_id": section number like "2.1" or null\n'
        '- "requires_evidence": true/false\n\n'
        "Draft:\n"
        + draft_text
    )
    system = "You extract claims from research drafts and return strict JSON."
    try:
        response = llm_client.generate(
            prompt,
            system=system,
            max_tokens=5000,
            temperature=0.2,
            response_format="json",
        )
    except LLMError as exc:
        logger.warning("llm_claim_extraction_failed", extra={"error": str(exc)})
        return None

    items = _extract_json_list(response)
    if not items:
        logger.warning(
            "llm_claim_extraction_parse_failed",
            extra={"reason": "no_json", "response_preview": response[:1200]},
        )
        return None

    claims: list[Claim] = []
    for item in items:
        text = str(item.get("text", "")).strip()
        if len(text) < 20:
            continue
        section_id = item.get("section_id")
        if not isinstance(section_id, str) or not section_id.strip():
            section_id = None
        citation_ids = _extract_citations(text)
        requires_evidence = bool(item.get("requires_evidence", False)) or bool(citation_ids)
        claims.append(
            Claim(
                claim_id=f"claim_{len(claims) + 1}",
                text=text,
                section_id=section_id,
                citation_ids=citation_ids,
                requires_evidence=requires_evidence,
            )
        )

    return claims or None


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
