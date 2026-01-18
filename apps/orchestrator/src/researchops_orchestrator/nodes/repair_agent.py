"""
RepairAgent node - fixes validation errors in the draft.

TARGETED REPAIR: Only modifies failing sections, not full rewrites.
"""

from __future__ import annotations

import re

from sqlalchemy.orm import Session

from researchops_core.observability import emit_run_event, instrument_node
from researchops_core.orchestrator.state import (
    OrchestratorState,
    RepairPlan,
    ValidationErrorType,
)


@instrument_node("repair")
def repair_agent_node(state: OrchestratorState, session: Session) -> OrchestratorState:
    """
    Repair validation errors with targeted edits.

    Strategy:
    1. Analyze validation errors
    2. Identify failing claims and sections
    3. Apply targeted fixes (add citations, remove unsupported claims)
    4. Increment draft version

    Args:
        state: Current orchestrator state
        session: Database session

    Returns:
        Updated state with repaired draft
    """
    errors = state.citation_errors
    draft_text = state.draft_text
    claims = state.extracted_claims

    if not errors:
        # No errors to repair
        return state

    # Increment repair attempt counter
    state.repair_attempts += 1

    # Create repair plan
    target_claims = []
    target_sections = set()

    for error in errors:
        if error.claim_id:
            target_claims.append(error.claim_id)
        if error.section_id:
            target_sections.add(error.section_id)

    repair_plan = RepairPlan(
        target_claims=target_claims,
        target_sections=list(target_sections),
        strategy="Remove or modify unsupported claims, add missing citations",
        additional_evidence_needed=False,
    )

    state.repair_plan = repair_plan

    # Emit progress
    emit_run_event(
        session=session,
        tenant_id=state.tenant_id,
        run_id=state.run_id,
        event_type="progress",
        stage="repair",
        data={
            "error_count": len(errors),
            "target_claims": len(target_claims),
            "target_sections": len(target_sections),
            "repair_attempt": state.repair_attempts,
        },
    )

    # Apply repairs
    repaired_draft = draft_text

    for error in errors:
        if error.error_type == ValidationErrorType.MISSING_CITATION:
            # Find claim and try to add a citation
            claim = next((c for c in claims if c.claim_id == error.claim_id), None)
            if claim:
                repaired_draft = _add_citation_to_claim(
                    repaired_draft, claim, state.evidence_snippets
                )

        elif error.error_type == ValidationErrorType.INVALID_CITATION:
            # Remove invalid citation
            if error.citation_id:
                repaired_draft = _remove_invalid_citation(repaired_draft, error.citation_id)

        elif error.error_type in [
            ValidationErrorType.UNSUPPORTED_CLAIM,
            ValidationErrorType.CONTRADICTED_CLAIM,
        ]:
            # Remove or soften the claim
            claim = next((c for c in claims if c.claim_id == error.claim_id), None)
            if claim:
                repaired_draft = _soften_claim(repaired_draft, claim)

    # Update state
    state.draft_text = repaired_draft
    state.draft_version += 1

    return state


def _add_citation_to_claim(draft: str, claim, evidence_snippets: list) -> str:
    """
    Add a citation to a claim missing one.

    Find the best matching snippet and insert [CITE:snippet_id].

    Args:
        draft: Current draft text
        claim: Claim object
        evidence_snippets: Available evidence snippets

    Returns:
        Modified draft text
    """
    # Find best matching snippet (simple keyword matching)
    claim_lower = claim.text.lower()
    best_snippet = None
    best_score = 0.0

    for snippet in evidence_snippets:
        snippet_lower = snippet.text.lower()
        # Count keyword matches
        keywords = [w for w in claim_lower.split() if len(w) > 4]
        matches = sum(1 for kw in keywords if kw in snippet_lower)
        score = matches / len(keywords) if keywords else 0

        if score > best_score:
            best_score = score
            best_snippet = snippet

    if best_snippet and best_score > 0.2:
        # Insert citation at end of claim sentence
        citation = f" [CITE:{best_snippet.snippet_id}]"

        # Find claim in draft
        claim_text_escaped = re.escape(claim.text[:50])  # Use first 50 chars
        pattern = re.compile(rf"{claim_text_escaped}.*?\.", re.DOTALL)

        def replacer(match):
            sentence = match.group(0)
            # Add citation before the period
            if citation not in sentence:
                return sentence[:-1] + citation + "."
            return sentence

        draft = pattern.sub(replacer, draft, count=1)

    return draft


def _remove_invalid_citation(draft: str, citation_id: str) -> str:
    """
    Remove an invalid citation from the draft.

    Args:
        draft: Current draft text
        citation_id: Citation ID to remove

    Returns:
        Modified draft text
    """
    # Pattern: [CITE:citation_id]
    pattern = rf"\[CITE:{re.escape(citation_id)}\]\s*"
    draft = re.sub(pattern, "", draft)

    return draft


def _soften_claim(draft: str, claim) -> str:
    """
    Soften an unsupported or contradicted claim.

    Add hedging language or remove the claim.

    Args:
        draft: Current draft text
        claim: Claim object

    Returns:
        Modified draft text
    """
    # Find claim in draft
    claim_text_escaped = re.escape(claim.text[:50])
    pattern = re.compile(rf"{claim_text_escaped}.*?\.", re.DOTALL)

    # Hedging prefixes
    hedges = [
        "Some research suggests that ",
        "Preliminary evidence indicates that ",
        "Further investigation is needed, but ",
    ]

    def replacer(match):
        sentence = match.group(0)
        # Check if already hedged
        if any(hedge.lower() in sentence.lower() for hedge in hedges):
            return sentence
        # Add hedge
        import random

        hedge = random.choice(hedges)
        return hedge.lower() + sentence

    draft = pattern.sub(replacer, draft, count=1)

    return draft
