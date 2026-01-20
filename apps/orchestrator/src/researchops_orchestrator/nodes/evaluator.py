"""
Evaluator node - decides whether to continue or stop the workflow.

Makes routing decisions based on validation errors and iteration count.
"""

from __future__ import annotations

import json
import logging
import os

from sqlalchemy.orm import Session

from researchops_core.observability import instrument_node
from researchops_core.orchestrator.state import (
    EvaluatorDecision,
    OrchestratorState,
    ValidationErrorType,
)
from researchops_llm import LLMError, get_llm_client

logger = logging.getLogger(__name__)

def _print_decision(decision: str, reason: str) -> None:
    print(f"[evaluator decision] {decision}: {reason}", flush=True)


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
    print("[evaluator start]", flush=True)
    errors = state.citation_errors
    iteration_count = state.iteration_count
    repair_attempts = state.repair_attempts

    # Check iteration limit
    if iteration_count >= state.max_iterations:
        state.evaluator_decision = EvaluatorDecision.STOP_SUCCESS
        state.evaluation_reason = "Maximum iterations reached, proceeding with best effort"
        _print_decision(state.evaluator_decision.value, state.evaluation_reason)
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
        _print_decision(state.evaluator_decision.value, state.evaluation_reason)
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
        _print_decision(state.evaluator_decision.value, state.evaluation_reason)
        logger.info(
            "evaluation_decision",
            extra={
                "run_id": str(state.run_id),
                "decision": state.evaluator_decision.value,
                "reason": state.evaluation_reason,
            },
        )
        return state

    llm_client = None
    require_llm = os.getenv("LLM_EVALUATOR_REQUIRED", "true").strip().lower() in {
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
            raise ValueError("LLM evaluator is required but unavailable.") from exc

    if llm_client:
        decision = _evaluate_with_llm(state, errors, llm_client)
        if decision:
            state.evaluator_decision = decision["decision"]
            state.evaluation_reason = decision["reason"]
            _print_decision(state.evaluator_decision.value, state.evaluation_reason)
            logger.info(
                "evaluation_decision_llm",
                extra={
                    "run_id": str(state.run_id),
                    "decision": state.evaluator_decision.value,
                    "reason": state.evaluation_reason,
                },
            )
            return state
        if require_llm:
            raise ValueError("LLM evaluator failed to return a valid decision.")

    if require_llm and not llm_client:
        raise ValueError("LLM evaluator is required but no LLM client is configured.")

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
        _print_decision(state.evaluator_decision.value, state.evaluation_reason)
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
        _print_decision(state.evaluator_decision.value, state.evaluation_reason)
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
    _print_decision(state.evaluator_decision.value, state.evaluation_reason)
    logger.info(
        "evaluation_decision",
        extra={
            "run_id": str(state.run_id),
            "decision": state.evaluator_decision.value,
            "reason": state.evaluation_reason,
        },
    )

    return state


def _extract_json_object(text: str) -> dict | None:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`").strip()
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return None
    try:
        data = json.loads(cleaned[start : end + 1])
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict):
        return None
    return data


def _evaluate_with_llm(
    state: OrchestratorState, errors, llm_client
) -> dict[str, object] | None:
    error_counts = _count_error_types(errors)
    sample_errors = [e.description for e in errors[:8]]
    prompt = (
        "You are deciding the next action for a research pipeline.\n"
        "Return ONLY JSON with keys:\n"
        '- "decision": one of ["stop_success","continue_repair","continue_retrieve","continue_rewrite"]\n'
        '- "reason": short explanation\n\n'
        f"Topic: {state.user_query}\n"
        f"Iteration: {state.iteration_count}/{state.max_iterations}\n"
        f"Repair attempts: {state.repair_attempts}/{state.max_repair_attempts}\n"
        f"Vetted sources: {len(state.vetted_sources)}\n"
        f"Evidence snippets: {len(state.evidence_snippets)}\n"
        f"Error counts: {error_counts}\n"
        f"Sample errors: {sample_errors}\n\n"
        "Guidance:\n"
        "- If sources are too few (<10) and errors are about missing evidence, choose continue_retrieve.\n"
        "- If there are citation/contradiction errors, choose continue_repair.\n"
        "- If only minor issues remain, choose stop_success.\n"
        "- If the writing quality is weak but evidence is sufficient, choose continue_rewrite.\n"
    )
    system = "You decide pipeline routing and respond with strict JSON."
    try:
        response = llm_client.generate(
            prompt,
            system=system,
            max_tokens=5000,
            temperature=0.2,
            response_format="json",
        )
    except LLMError as exc:
        logger.warning("llm_evaluator_failed", extra={"error": str(exc)})
        return None

    data = _extract_json_object(response)
    if not data:
        logger.warning(
            "llm_evaluator_parse_failed",
            extra={"reason": "no_json", "response_preview": response[:1200]},
        )
        return None

    decision_raw = data.get("decision")
    if not isinstance(decision_raw, str):
        return None
    decision_map = {
        "stop_success": EvaluatorDecision.STOP_SUCCESS,
        "continue_repair": EvaluatorDecision.CONTINUE_REPAIR,
        "continue_retrieve": EvaluatorDecision.CONTINUE_RETRIEVE,
        "continue_rewrite": EvaluatorDecision.CONTINUE_REWRITE,
    }
    decision = decision_map.get(decision_raw.strip().lower())
    if not decision:
        return None
    reason = data.get("reason")
    if not isinstance(reason, str) or not reason.strip():
        reason = "LLM decision"

    return {"decision": decision, "reason": reason.strip()}


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
