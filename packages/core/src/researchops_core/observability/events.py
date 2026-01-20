"""
Event emission for orchestrator nodes.

Provides utilities to emit SSE events during graph execution.
"""

from __future__ import annotations

import functools
import logging
import time
import traceback
from datetime import UTC, datetime
from typing import Any, Callable
from uuid import UUID

from sqlalchemy.orm import Session

from db.models.run_events import RunEventRow

logger = logging.getLogger(__name__)

def _state_summary(state: Any) -> dict[str, Any]:
    summary: dict[str, Any] = {}
    if state is None:
        return summary

    def get_value(key: str) -> Any:
        if isinstance(state, dict):
            return state.get(key)
        return getattr(state, key, None)

    def maybe_len(value: Any) -> int | None:
        try:
            return len(value)
        except Exception:
            return None

    summary_fields = [
        "generated_queries",
        "retrieved_sources",
        "evidence_snippets",
        "vetted_sources",
        "extracted_claims",
        "citation_errors",
        "fact_check_results",
        "artifacts",
    ]
    for field in summary_fields:
        value = get_value(field)
        count = maybe_len(value) if value is not None else None
        if count is not None:
            summary[field] = count

    outline = get_value("outline")
    if outline is not None:
        sections = outline.get("sections") if isinstance(outline, dict) else getattr(outline, "sections", None)
        count = maybe_len(sections) if sections is not None else None
        if count is not None:
            summary["outline_sections"] = count

    draft_text = get_value("draft_text")
    if isinstance(draft_text, str) and draft_text:
        summary["draft_length"] = len(draft_text)

    evaluator_decision = get_value("evaluator_decision")
    if evaluator_decision:
        summary["evaluator_decision"] = getattr(evaluator_decision, "value", str(evaluator_decision))

    iteration_count = get_value("iteration_count")
    if isinstance(iteration_count, int):
        summary["iteration_count"] = iteration_count

    repair_attempts = get_value("repair_attempts")
    if isinstance(repair_attempts, int):
        summary["repair_attempts"] = repair_attempts

    return summary


def emit_run_event(
    session: Session,
    tenant_id: UUID,
    run_id: UUID,
    event_type: str,
    stage: str | None = None,
    data: dict[str, Any] | None = None,
) -> RunEventRow:
    """
    Emit a run event to the run_events table.

    Args:
        session: Database session
        tenant_id: Tenant ID
        run_id: Run ID
        event_type: Type of event (stage_start, stage_finish, progress, error)
        stage: Current stage name (retrieve, ingest, outline, etc.)
        data: Additional event data (JSON)

    Returns:
        The created RunEventRow
    """
    from sqlalchemy import select

    # Get the next event number for this run
    result = session.execute(
        select(RunEventRow.event_number)
        .where(RunEventRow.tenant_id == tenant_id)
        .where(RunEventRow.run_id == run_id)
        .order_by(RunEventRow.event_number.desc())
        .limit(1)
    )
    last_event = result.scalar_one_or_none()
    next_event_number = (last_event or 0) + 1

    # Import the level enum
    from db.models.run_events import RunEventLevelDb

    # Create event
    event = RunEventRow(
        tenant_id=tenant_id,
        run_id=run_id,
        event_number=next_event_number,
        event_type=event_type,
        stage=stage or "unknown",
        level=RunEventLevelDb.info,  # Default to info
        message=f"{event_type}: {stage or 'unknown'}",
        payload_json=data or {},
        ts=datetime.now(UTC),
    )

    session.add(event)
    session.flush()  # Get the ID without committing

    return event


def instrument_node(stage_name: str) -> Callable:
    """
    Decorator to automatically emit stage_start, stage_finish, and error events.

    Usage:
        @instrument_node("retrieve")
        def retrieve_node(state: OrchestratorState, session: Session) -> OrchestratorState:
            # Your node logic here
            return state

    Args:
        stage_name: Name of the stage (e.g., "retrieve", "outline", "draft")

    Returns:
        Decorator function
    """

    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(state: Any, session: Session, **kwargs: Any) -> Any:
            """Wrapped function with event emission."""
            start_time = time.monotonic()
            state_summary = _state_summary(state)
            logger.info(
                "node_start",
                extra={
                    "stage": stage_name,
                    "run_id": str(state.run_id),
                    "tenant_id": str(state.tenant_id),
                    "iteration": state.iteration_count,
                    "state_summary": state_summary,
                },
            )
            # Emit stage_start
            emit_run_event(
                session=session,
                tenant_id=state.tenant_id,
                run_id=state.run_id,
                event_type="stage_start",
                stage=stage_name,
                data={
                    "iteration": state.iteration_count,
                    "state_summary": state_summary,
                },
            )

            try:
                # Execute the node
                result = func(state, session, **kwargs)

                duration_ms = int((time.monotonic() - start_time) * 1000)
                result_summary = _state_summary(result)

                # Emit stage_finish
                emit_run_event(
                    session=session,
                    tenant_id=state.tenant_id,
                    run_id=state.run_id,
                    event_type="stage_finish",
                    stage=stage_name,
                    data={
                        "iteration": state.iteration_count,
                        "success": True,
                        "duration_ms": duration_ms,
                        "state_summary": result_summary,
                    },
                )

                logger.info(
                    "node_finish",
                    extra={
                        "stage": stage_name,
                        "run_id": str(state.run_id),
                        "tenant_id": str(state.tenant_id),
                        "iteration": state.iteration_count,
                        "duration_ms": duration_ms,
                        "state_summary": result_summary,
                    },
                )
                return result

            except Exception as e:
                try:
                    session.rollback()
                except Exception:
                    logger.exception(
                        "node_error_rollback_failed",
                        extra={
                            "stage": stage_name,
                            "run_id": str(state.run_id),
                            "tenant_id": str(state.tenant_id),
                        },
                    )
                logger.exception(
                    "node_error",
                    extra={
                        "stage": stage_name,
                        "run_id": str(state.run_id),
                        "tenant_id": str(state.tenant_id),
                        "iteration": state.iteration_count,
                        "error": str(e),
                        "state_summary": state_summary,
                    },
                )
                # Emit error event
                emit_run_event(
                    session=session,
                    tenant_id=state.tenant_id,
                    run_id=state.run_id,
                    event_type="error",
                    stage=stage_name,
                    data={
                        "iteration": state.iteration_count,
                        "error": str(e),
                        "traceback": traceback.format_exc(),
                        "state_summary": state_summary,
                    },
                )
                raise

        return wrapper

    return decorator
