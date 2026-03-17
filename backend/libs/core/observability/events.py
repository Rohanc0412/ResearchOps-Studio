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


def _get_state_value(state: Any, key: str) -> Any:
    if isinstance(state, dict):
        return state.get(key)
    return getattr(state, key, None)


def _truncate_text(text: str, max_chars: int = 2000) -> str:
    cleaned = (text or "").strip()
    if len(cleaned) <= max_chars:
        return cleaned
    return cleaned[:max_chars].rstrip() + "...(truncated)"



def _event_session(session: Session) -> Session:
    return Session(
        bind=session.get_bind(),
        expire_on_commit=False,
        autoflush=False,
        future=True,
    )

def _state_summary(state: Any) -> dict[str, Any]:
    summary: dict[str, Any] = {}
    if state is None:
        return summary

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
        value = _get_state_value(state, field)
        count = maybe_len(value) if value is not None else None
        if count is not None:
            summary[field] = count

    outline = _get_state_value(state, "outline")
    if outline is not None:
        sections = outline.get("sections") if isinstance(outline, dict) else getattr(outline, "sections", None)
        count = maybe_len(sections) if sections is not None else None
        if count is not None:
            summary["outline_sections"] = count

    draft_text = _get_state_value(state, "draft_text")
    if isinstance(draft_text, str) and draft_text:
        summary["draft_length"] = len(draft_text)

    evaluator_decision = _get_state_value(state, "evaluator_decision")
    if evaluator_decision:
        summary["evaluator_decision"] = getattr(evaluator_decision, "value", str(evaluator_decision))

    iteration_count = _get_state_value(state, "iteration_count")
    if isinstance(iteration_count, int):
        summary["iteration_count"] = iteration_count

    repair_attempts = _get_state_value(state, "repair_attempts")
    if isinstance(repair_attempts, int):
        summary["repair_attempts"] = repair_attempts

    return summary


def _source_preview(sources: Any, limit: int = 5) -> list[dict[str, Any]]:
    if not sources:
        return []
    preview: list[dict[str, Any]] = []
    for source in list(sources)[:limit]:
        preview.append(
            {
                "source_id": str(_get_state_value(source, "source_id") or ""),
                "title": _get_state_value(source, "title"),
                "year": _get_state_value(source, "year"),
                "connector": _get_state_value(source, "connector"),
            }
        )
    return preview


def _outline_preview(outline: Any, limit: int = 8) -> list[dict[str, Any]]:
    if outline is None:
        return []
    sections = outline.get("sections") if isinstance(outline, dict) else getattr(outline, "sections", None)
    if not sections:
        return []
    items: list[dict[str, Any]] = []
    for section in list(sections)[:limit]:
        items.append(
            {
                "section_id": _get_state_value(section, "section_id"),
                "title": _get_state_value(section, "title"),
            }
        )
    return items


def _stage_input_details(stage: str, state: Any) -> dict[str, Any]:
    details: dict[str, Any] = {}
    details["user_query"] = _truncate_text(str(_get_state_value(state, "user_query") or ""))
    if stage == "retrieve":
        details["existing_queries"] = list(_get_state_value(state, "generated_queries") or [])
    if stage == "evidence_pack":
        details["outline_sections"] = _outline_preview(_get_state_value(state, "outline"))
    if stage == "outline":
        details["vetted_sources_preview"] = _source_preview(_get_state_value(state, "vetted_sources"))
    if stage == "draft":
        details["outline_sections"] = _outline_preview(_get_state_value(state, "outline"))
        details["evidence_snippet_count"] = len(_get_state_value(state, "evidence_snippets") or [])
    if stage == "evaluate":
        details["draft_length"] = len(_get_state_value(state, "draft_text") or "")
    if stage == "repair":
        details["repair_attempts"] = _get_state_value(state, "repair_attempts")
    if stage == "export":
        details["draft_length"] = len(_get_state_value(state, "draft_text") or "")
    return {k: v for k, v in details.items() if v not in (None, "", [])}


def _stage_output_details(stage: str, state: Any) -> dict[str, Any]:
    details: dict[str, Any] = {}
    if stage == "retrieve":
        details["generated_queries"] = list(_get_state_value(state, "generated_queries") or [])
        vetted_sources = _get_state_value(state, "vetted_sources") or []
        details["selected_sources_count"] = len(vetted_sources)
        details["selected_sources_preview"] = _source_preview(vetted_sources)
    elif stage == "evidence_pack":
        section_snippets = _get_state_value(state, "section_evidence_snippets") or {}
        details["section_snippet_counts"] = {
            str(section_id): len(snippets or [])
            for section_id, snippets in list(section_snippets.items())[:12]
        }
    elif stage == "outline":
        details["outline_sections"] = _outline_preview(_get_state_value(state, "outline"))
    elif stage == "draft":
        draft_text = _get_state_value(state, "draft_text") or ""
        details["draft_length"] = len(draft_text)
        details["draft_preview"] = _truncate_text(str(draft_text), max_chars=800)
    elif stage == "evaluate":
        decision = _get_state_value(state, "evaluator_decision")
        if decision is not None:
            details["evaluator_decision"] = getattr(decision, "value", str(decision))
        details["evaluation_reason"] = _get_state_value(state, "evaluation_reason")
    elif stage == "repair":
        details["repair_attempts"] = _get_state_value(state, "repair_attempts")
        details["repair_edits_count"] = len(_get_state_value(state, "repair_edits_json") or [])
    elif stage == "export":
        artifacts = _get_state_value(state, "artifacts") or {}
        details["artifacts"] = list(artifacts.keys()) if isinstance(artifacts, dict) else []
    return {k: v for k, v in details.items() if v not in (None, "", [])}


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

    # Use a short-lived session so run events are visible immediately.
    event_session = _event_session(session)
    try:
        # Get the next event number for this run
        result = event_session.execute(
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

        event_session.add(event)
        event_session.commit()
        return event
    finally:
        event_session.close()


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
                f"Starting pipeline step: {stage_name}",
                extra={
                    "event": "pipeline.step.start",
                    "stage": stage_name,
                    "state_summary": state_summary,
                    "input": _stage_input_details(stage_name, state),
                    "iteration": _get_state_value(state, "iteration_count"),
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
                    f"Finished pipeline step: {stage_name}",
                    extra={
                        "event": "pipeline.step.finish",
                        "stage": stage_name,
                        "duration_ms": duration_ms,
                        "state_summary": result_summary,
                        "output": _stage_output_details(stage_name, result),
                        "iteration": _get_state_value(result, "iteration_count"),
                    },
                )

                return result

            except Exception as e:
                try:
                    session.rollback()
                except Exception:
                    pass
                logger.exception(
                    f"Pipeline step failed: {stage_name}",
                    extra={
                        "event": "pipeline.step.error",
                        "stage": stage_name,
                        "error": str(e),
                        "state_summary": state_summary,
                        "iteration": _get_state_value(state, "iteration_count"),
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
