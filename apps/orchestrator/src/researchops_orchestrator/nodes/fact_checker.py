"""
FactChecker node - verifies that claims are supported by cited evidence.

Checks if the evidence actually supports the claims being made.
"""

from __future__ import annotations

import logging

from sqlalchemy.orm import Session

from researchops_core.observability import emit_run_event, instrument_node
from researchops_core.orchestrator.state import (
    FactCheckResult,
    FactCheckStatus,
    OrchestratorState,
    ValidationError,
    ValidationErrorType,
)

logger = logging.getLogger(__name__)

@instrument_node("fact_checking")
def fact_checker_node(state: OrchestratorState, session: Session) -> OrchestratorState:
    """
    Verify that claims are supported by their citations.

    Strategy:
    1. For each claim requiring evidence
    2. Retrieve cited snippets
    3. Check if snippet text supports the claim
    4. Flag contradictions or insufficient evidence

    Args:
        state: Current orchestrator state
        session: Database session

    Returns:
        Updated state with fact_check_results
    """
    claims = state.extracted_claims
    evidence_snippets = state.evidence_snippets

    # Build snippet lookup
    snippet_map = {str(snippet.snippet_id): snippet for snippet in evidence_snippets}

    # Fact-check each claim
    results = []
    additional_errors = []

    for i, claim in enumerate(claims):
        # Emit progress
        if i % 10 == 0:
            emit_run_event(
                session=session,
                tenant_id=state.tenant_id,
                run_id=state.run_id,
                event_type="progress",
                stage="fact_checking",
                data={
                    "claims_checked": i,
                    "total_claims": len(claims),
                },
            )

        # Skip claims that don't require evidence
        if not claim.requires_evidence:
            results.append(
                FactCheckResult(
                    claim_id=claim.claim_id,
                    status=FactCheckStatus.NOT_CHECKED,
                    confidence=1.0,
                    explanation="Claim does not require evidence",
                )
            )
            continue

        # Skip claims without citations (already caught by citation validator)
        if not claim.citation_ids:
            results.append(
                FactCheckResult(
                    claim_id=claim.claim_id,
                    status=FactCheckStatus.INSUFFICIENT,
                    confidence=0.0,
                    explanation="No citations provided",
                )
            )
            continue

        # Get cited snippets
        cited_snippets = []
        for citation_id in claim.citation_ids:
            snippet = snippet_map.get(citation_id)
            if snippet:
                cited_snippets.append(snippet)

        if not cited_snippets:
            results.append(
                FactCheckResult(
                    claim_id=claim.claim_id,
                    status=FactCheckStatus.INSUFFICIENT,
                    confidence=0.0,
                    explanation="Citations do not reference valid snippets",
                )
            )
            continue

        # Check if claim is supported
        support_score, contradiction_score = _evaluate_support(claim.text, cited_snippets)

        # Determine status
        if contradiction_score > 0.5:
            status = FactCheckStatus.CONTRADICTED
            confidence = contradiction_score
            explanation = "Evidence contradicts the claim"

            # Add validation error
            additional_errors.append(
                ValidationError(
                    error_type=ValidationErrorType.CONTRADICTED_CLAIM,
                    claim_id=claim.claim_id,
                    section_id=claim.section_id,
                    description=f"Claim contradicted by evidence: {claim.text[:50]}...",
                    severity="error",
                )
            )

        elif support_score > 0.5:
            status = FactCheckStatus.SUPPORTED
            confidence = support_score
            explanation = "Evidence supports the claim"

        else:
            status = FactCheckStatus.INSUFFICIENT
            confidence = support_score
            explanation = "Evidence is insufficient to verify claim"

            # Add validation error
            additional_errors.append(
                ValidationError(
                    error_type=ValidationErrorType.UNSUPPORTED_CLAIM,
                    claim_id=claim.claim_id,
                    section_id=claim.section_id,
                    description=f"Claim lacks sufficient support: {claim.text[:50]}...",
                    severity="warning",
                )
            )

        results.append(
            FactCheckResult(
                claim_id=claim.claim_id,
                status=status,
                supporting_snippets=[
                    s.snippet_id for s in cited_snippets if support_score > 0.5
                ],
                contradicting_snippets=[
                    s.snippet_id for s in cited_snippets if contradiction_score > 0.5
                ],
                confidence=confidence,
                explanation=explanation,
            )
        )

    # Update state
    state.fact_check_results = results

    # Append fact-checking errors to citation errors
    state.citation_errors.extend(additional_errors)
    logger.info(
        "fact_check_complete",
        extra={
            "run_id": str(state.run_id),
            "results": len(results),
            "new_errors": len(additional_errors),
        },
    )

    return state


def _evaluate_support(claim_text: str, snippets: list) -> tuple[float, float]:
    """
    Evaluate if snippets support or contradict a claim.

    Simple keyword-based approach (can be enhanced with NLI models).

    Args:
        claim_text: The claim to verify
        snippets: List of EvidenceSnippetRef objects

    Returns:
        Tuple of (support_score, contradiction_score) between 0.0 and 1.0
    """
    # Extract keywords from claim
    claim_lower = claim_text.lower()
    claim_keywords = set(claim_lower.split())

    # Remove common words
    stop_words = {"the", "a", "an", "and", "or", "but", "in", "on", "at", "to", "for"}
    claim_keywords = claim_keywords - stop_words

    if not claim_keywords:
        return (0.5, 0.0)  # Neutral

    # Check snippet overlap
    support_votes = 0
    contradiction_votes = 0

    for snippet in snippets:
        snippet_lower = snippet.text.lower()

        # Count keyword matches
        matches = sum(1 for kw in claim_keywords if kw in snippet_lower and len(kw) > 3)
        match_ratio = matches / len(claim_keywords) if claim_keywords else 0

        # High overlap -> support
        if match_ratio > 0.4:
            support_votes += 1

        # Check for contradiction indicators
        contradiction_words = ["not", "never", "no", "false", "incorrect", "contrary"]
        if any(word in snippet_lower for word in contradiction_words):
            # Only count as contradiction if there's also keyword overlap
            if match_ratio > 0.3:
                contradiction_votes += 1

    # Calculate scores
    total_votes = len(snippets)
    support_score = support_votes / total_votes if total_votes > 0 else 0.0
    contradiction_score = contradiction_votes / total_votes if total_votes > 0 else 0.0

    return (support_score, contradiction_score)
