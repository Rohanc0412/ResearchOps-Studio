"""
Event emission for orchestrator nodes.

Provides utilities to emit SSE events during graph execution.
"""

from __future__ import annotations

import functools
import traceback
from datetime import UTC, datetime
from typing import Any, Callable
from uuid import UUID

from sqlalchemy.orm import Session

from db.models.run_events import RunEventRow


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
            # Emit stage_start
            emit_run_event(
                session=session,
                tenant_id=state.tenant_id,
                run_id=state.run_id,
                event_type="stage_start",
                stage=stage_name,
                data={"iteration": state.iteration_count},
            )

            try:
                # Execute the node
                result = func(state, session, **kwargs)

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
                    },
                )

                return result

            except Exception as e:
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
                    },
                )
                raise

        return wrapper

    return decorator
