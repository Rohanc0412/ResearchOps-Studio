"""
Evaluator node - decides whether to continue or stop the workflow.

Makes routing decisions based on validation errors and iteration count.
"""

from __future__ import annotations

import logging

from sqlalchemy.orm import Session

from researchops_core.observability import instrument_node
from researchops_core.orchestrator.state import (
    EvaluatorDecision,
    OrchestratorState,
    ValidationErrorType,
)

logger = logging.getLogger(__name__)

@instrument_node("evaluation")
def evaluator_node(state: OrchestratorState, session: Session) -> OrchestratorState:
    """
    Evaluate whether to stop or continue the workflow.

    Decision logic:
    1. If no errors -> STOP_SUCCESS (export)
    2. If errors and can repair -> CONTINUE_REPAIR
    3. If too many repair attempts -> STOP_SUCCESS (best effort)
    4. If need more evidence -> CONTINUE_RETRIEVE
    5. If max iterations reached -> STOP_SUCCESS (timeout)

    Args:
        state: Current orchestrator state
        session: Database session

    Returns:
        Updated state with evaluator_decision
    """
    errors = state.citation_errors
    iteration_count = state.iteration_count
    repair_attempts = state.repair_attempts

    # Check iteration limit
    if iteration_count >= state.max_iterations:
        state.evaluator_decision = EvaluatorDecision.STOP_SUCCESS
        state.evaluation_reason = "Maximum iterations reached, proceeding with best effort"
        logger.info(
            "evaluation_decision",
            extra={
                "run_id": str(state.run_id),
                "decision": state.evaluator_decision.value,
                "reason": state.evaluation_reason,
            },
        )
        return state

    # Check repair attempt limit
    if repair_attempts >= state.max_repair_attempts:
        state.evaluator_decision = EvaluatorDecision.STOP_SUCCESS
        state.evaluation_reason = "Maximum repair attempts reached, proceeding with current draft"
        logger.info(
            "evaluation_decision",
            extra={
                "run_id": str(state.run_id),
                "decision": state.evaluator_decision.value,
                "reason": state.evaluation_reason,
            },
        )
        return state

    # No errors -> success
    if not errors:
        state.evaluator_decision = EvaluatorDecision.STOP_SUCCESS
        state.evaluation_reason = "All validation checks passed"
        logger.info(
            "evaluation_decision",
            extra={
                "run_id": str(state.run_id),
                "decision": state.evaluator_decision.value,
                "reason": state.evaluation_reason,
            },
        )
        return state

    # Count error types
    error_counts = _count_error_types(errors)

    # Critical errors -> need repair
    critical_errors = (
        error_counts.get(ValidationErrorType.MISSING_CITATION, 0)
        + error_counts.get(ValidationErrorType.INVALID_CITATION, 0)
        + error_counts.get(ValidationErrorType.CONTRADICTED_CLAIM, 0)
    )

    if critical_errors > 0:
        # Check if we have enough sources
        if len(state.vetted_sources) < 10:
            state.evaluator_decision = EvaluatorDecision.CONTINUE_RETRIEVE
            state.evaluation_reason = (
                f"Insufficient sources ({len(state.vetted_sources)}), retrieving more evidence"
            )
        else:
            state.evaluator_decision = EvaluatorDecision.CONTINUE_REPAIR
            state.evaluation_reason = f"Found {critical_errors} critical errors, attempting repair"
        logger.info(
            "evaluation_decision",
            extra={
                "run_id": str(state.run_id),
                "decision": state.evaluator_decision.value,
                "reason": state.evaluation_reason,
            },
        )
        return state

    # Only warnings (unsupported claims)
    warning_count = error_counts.get(ValidationErrorType.UNSUPPORTED_CLAIM, 0)

    if warning_count > 0:
        # If many warnings, try to improve
        if warning_count > 5:
            state.evaluator_decision = EvaluatorDecision.CONTINUE_REPAIR
            state.evaluation_reason = f"Found {warning_count} warnings, attempting improvements"
        else:
            # Few warnings -> acceptable
            state.evaluator_decision = EvaluatorDecision.STOP_SUCCESS
            state.evaluation_reason = (
                f"Minor warnings ({warning_count}) present but within tolerance"
            )
        logger.info(
            "evaluation_decision",
            extra={
                "run_id": str(state.run_id),
                "decision": state.evaluator_decision.value,
                "reason": state.evaluation_reason,
            },
        )
        return state

    # Default: success
    state.evaluator_decision = EvaluatorDecision.STOP_SUCCESS
    state.evaluation_reason = "Evaluation complete, no major issues"
    logger.info(
        "evaluation_decision",
        extra={
            "run_id": str(state.run_id),
            "decision": state.evaluator_decision.value,
            "reason": state.evaluation_reason,
        },
    )

    return state


def _count_error_types(errors: list) -> dict:
    """
    Count errors by type.

    Args:
        errors: List of ValidationError objects

    Returns:
        Dictionary mapping error_type to count
    """
    counts = {}
    for error in errors:
        error_type = error.error_type
        counts[error_type] = counts.get(error_type, 0) + 1

    return counts
