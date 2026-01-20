"""
CitationValidator node - validates that all claims have proper citations.

FAIL CLOSED: If citations are missing or invalid, block the pipeline.
"""

from __future__ import annotations

import logging
from uuid import UUID

from sqlalchemy.orm import Session

from researchops_core.observability import instrument_node
from researchops_core.orchestrator.state import (
    OrchestratorState,
    ValidationError,
    ValidationErrorType,
)

logger = logging.getLogger(__name__)

@instrument_node("citation_validation")
def citation_validator_node(
    state: OrchestratorState, session: Session
) -> OrchestratorState:
    """
    Validate that all claims requiring evidence have valid citations.

    FAIL CLOSED strategy:
    - Every claim requiring evidence must have at least one citation
    - Every citation must reference a valid snippet ID
    - Missing or invalid citations are ERROR-level validation errors

    Args:
        state: Current orchestrator state
        session: Database session

    Returns:
        Updated state with citation_errors
    """
    claims = state.extracted_claims
    evidence_snippets = state.evidence_snippets

    # Build set of valid snippet IDs
    valid_snippet_ids = {str(snippet.snippet_id) for snippet in evidence_snippets}

    # Validate each claim
    errors = []

    for claim in claims:
        # Skip claims that don't require evidence
        if not claim.requires_evidence:
            continue

        # Check if claim has citations
        if not claim.citation_ids:
            errors.append(
                ValidationError(
                    error_type=ValidationErrorType.MISSING_CITATION,
                    claim_id=claim.claim_id,
                    section_id=claim.section_id,
                    description=f"Claim '{claim.text[:50]}...' requires evidence but has no citations",
                    severity="error",
                )
            )
            continue

        # Validate each citation
        for citation_id in claim.citation_ids:
            # Check if citation references a valid snippet
            if citation_id not in valid_snippet_ids:
                errors.append(
                    ValidationError(
                        error_type=ValidationErrorType.INVALID_CITATION,
                        claim_id=claim.claim_id,
                        section_id=claim.section_id,
                        citation_id=citation_id,
                        description=f"Citation [CITE:{citation_id}] references invalid snippet ID",
                        severity="error",
                    )
                )

    # Update state
    state.citation_errors = errors
    logger.info(
        "citation_validation_complete",
        extra={"run_id": str(state.run_id), "errors": len(errors)},
    )

    return state
