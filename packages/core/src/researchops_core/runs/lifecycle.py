"""Run lifecycle state machine service.

This module provides production-grade run lifecycle management with:
- State transition validation (enforces allowed transitions)
- Atomic transitions (row-level locking to prevent race conditions)
- Event emission (every state/stage change emits events)
- Idempotency (guards against duplicate event emission)
- Cooperative cancellation (cancel flag checked between stages)
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from db.models.run_events import RunEventLevelDb, RunEventRow
from db.models.runs import RunRow, RunStatusDb
from db.services.truth import append_run_event

if TYPE_CHECKING:
    pass

# Run state machine: allowed transitions
# Maps from_status -> set of allowed to_status values
ALLOWED_TRANSITIONS: dict[RunStatusDb, set[RunStatusDb]] = {
    RunStatusDb.created: {RunStatusDb.queued, RunStatusDb.canceled},
    RunStatusDb.queued: {RunStatusDb.running, RunStatusDb.canceled},
    RunStatusDb.running: {
        RunStatusDb.blocked,
        RunStatusDb.failed,
        RunStatusDb.succeeded,
        RunStatusDb.canceled,
    },
    RunStatusDb.blocked: {RunStatusDb.running, RunStatusDb.failed, RunStatusDb.canceled},
    RunStatusDb.failed: {RunStatusDb.queued},  # only via explicit retry
    RunStatusDb.succeeded: set(),  # terminal
    RunStatusDb.canceled: set(),  # terminal
}

# Terminal states (cannot transition out except via retry for failed)
TERMINAL_STATES = {RunStatusDb.succeeded, RunStatusDb.canceled}

# Valid run stages
VALID_STAGES = {"retrieve", "ingest", "outline", "draft", "validate", "factcheck", "export"}

# Event types
EVENT_TYPE_STAGE_START = "stage_start"
EVENT_TYPE_STAGE_FINISH = "stage_finish"
EVENT_TYPE_LOG = "log"
EVENT_TYPE_ERROR = "error"
EVENT_TYPE_STATE = "state"


class RunTransitionError(ValueError):
    """Raised when an illegal run state transition is attempted."""

    pass


class RunNotFoundError(ValueError):
    """Raised when a run cannot be found."""

    pass


def validate_transition(from_status: RunStatusDb, to_status: RunStatusDb) -> None:
    """Validate that a state transition is allowed.

    Args:
        from_status: Current run status
        to_status: Desired run status

    Raises:
        RunTransitionError: If the transition is not allowed
    """
    if from_status == to_status:
        # Same state is always allowed (idempotent)
        return

    allowed = ALLOWED_TRANSITIONS.get(from_status, set())
    if to_status not in allowed:
        raise RunTransitionError(
            f"Illegal transition: {from_status.value} -> {to_status.value}. "
            f"Allowed transitions from {from_status.value}: {[s.value for s in allowed]}"
        )


def transition_run_status(
    session: Session,
    tenant_id: UUID,
    run_id: UUID,
    to_status: RunStatusDb,
    *,
    current_stage: str | None = None,
    failure_reason: str | None = None,
    error_code: str | None = None,
    started_at: datetime | None = None,
    finished_at: datetime | None = None,
    cancel_requested_at: datetime | None = None,
    emit_event: bool = True,
) -> RunRow:
    """Atomically transition a run to a new status with validation.

    This function:
    1. Acquires a row lock on the run (SELECT FOR UPDATE)
    2. Validates the transition is allowed
    3. Updates the run status and related fields
    4. Optionally emits a state change event
    5. Commits the transaction

    Args:
        session: Database session (must be in a transaction)
        tenant_id: Tenant ID
        run_id: Run ID
        to_status: Target status
        current_stage: Optional stage to set
        failure_reason: Optional failure reason (for failed status)
        error_code: Optional error code (for failed status)
        started_at: Optional started timestamp
        finished_at: Optional finished timestamp
        cancel_requested_at: Optional cancel request timestamp
        emit_event: Whether to emit a state change event (default True)

    Returns:
        Updated RunRow

    Raises:
        RunNotFoundError: If run not found
        RunTransitionError: If transition is not allowed
    """
    # Acquire row lock to prevent concurrent modifications
    stmt = (
        select(RunRow)
        .where(RunRow.tenant_id == tenant_id, RunRow.id == run_id)
        .with_for_update()
    )
    run = session.execute(stmt).scalar_one_or_none()

    if run is None:
        raise RunNotFoundError(f"Run {run_id} not found for tenant {tenant_id}")

    # Validate transition
    from_status = run.status
    validate_transition(from_status, to_status)

    # Update run fields
    run.status = to_status

    if current_stage is not None:
        run.current_stage = current_stage

    if failure_reason is not None:
        run.failure_reason = failure_reason

    if error_code is not None:
        run.error_code = error_code

    if started_at is not None:
        run.started_at = started_at

    if finished_at is not None:
        run.finished_at = finished_at

    if cancel_requested_at is not None:
        run.cancel_requested_at = cancel_requested_at

    run.updated_at = datetime.now(UTC)

    session.flush()

    # Emit state change event
    if emit_event:
        emit_run_event(
            session=session,
            tenant_id=tenant_id,
            run_id=run_id,
            event_type=EVENT_TYPE_STATE,
            level=RunEventLevelDb.info,
            message=f"Run transitioned: {from_status.value} -> {to_status.value}",
            stage=current_stage,
            payload={
                "from_status": from_status.value,
                "to_status": to_status.value,
            },
        )

    return run


def emit_run_event(
    session: Session,
    tenant_id: UUID,
    run_id: UUID,
    event_type: str,
    level: RunEventLevelDb,
    message: str,
    stage: str | None = None,
    payload: dict | None = None,
) -> RunEventRow:
    """Emit a run event with automatic event_number assignment.

    Args:
        session: Database session
        tenant_id: Tenant ID
        run_id: Run ID
        event_type: Event type (stage_start, stage_finish, log, error, state)
        level: Event level (debug, info, warn, error)
        message: Event message
        stage: Optional stage name
        payload: Optional payload dictionary

    Returns:
        Created RunEventRow
    """
    return append_run_event(
        session=session,
        tenant_id=tenant_id,
        run_id=run_id,
        level=level,
        message=message,
        stage=stage,
        event_type=event_type,
        payload_json=payload or {},
        allow_finished=True,
    )


def emit_stage_start(
    session: Session, tenant_id: UUID, run_id: UUID, stage: str, payload: dict | None = None
) -> RunEventRow:
    """Emit a stage_start event and update run's current_stage.

    This is idempotent: if the most recent event for this run+stage is already
    a stage_start, we skip emitting a duplicate.

    Args:
        session: Database session
        tenant_id: Tenant ID
        run_id: Run ID
        stage: Stage name
        payload: Optional payload

    Returns:
        Created or existing RunEventRow
    """
    if stage not in VALID_STAGES:
        raise ValueError(f"Invalid stage: {stage}. Must be one of {VALID_STAGES}")

    # Check if we already emitted stage_start for this stage
    # (idempotency guard)
    last_event_stmt = (
        select(RunEventRow)
        .where(
            RunEventRow.tenant_id == tenant_id,
            RunEventRow.run_id == run_id,
            RunEventRow.stage == stage,
        )
        .order_by(RunEventRow.event_number.desc())
        .limit(1)
    )
    last_event = session.execute(last_event_stmt).scalar_one_or_none()

    if last_event and last_event.event_type == EVENT_TYPE_STAGE_START:
        # Already emitted, return existing event
        return last_event

    # Update run's current_stage
    stmt = (
        select(RunRow)
        .where(RunRow.tenant_id == tenant_id, RunRow.id == run_id)
        .with_for_update()
    )
    run = session.execute(stmt).scalar_one_or_none()
    if run:
        run.current_stage = stage
        run.updated_at = datetime.now(UTC)
        session.flush()

    # Emit event
    return emit_run_event(
        session=session,
        tenant_id=tenant_id,
        run_id=run_id,
        event_type=EVENT_TYPE_STAGE_START,
        level=RunEventLevelDb.info,
        message=f"Starting stage: {stage}",
        stage=stage,
        payload=payload,
    )


def emit_stage_finish(
    session: Session, tenant_id: UUID, run_id: UUID, stage: str, payload: dict | None = None
) -> RunEventRow:
    """Emit a stage_finish event.

    Args:
        session: Database session
        tenant_id: Tenant ID
        run_id: Run ID
        stage: Stage name
        payload: Optional payload

    Returns:
        Created RunEventRow
    """
    if stage not in VALID_STAGES:
        raise ValueError(f"Invalid stage: {stage}. Must be one of {VALID_STAGES}")

    return emit_run_event(
        session=session,
        tenant_id=tenant_id,
        run_id=run_id,
        event_type=EVENT_TYPE_STAGE_FINISH,
        level=RunEventLevelDb.info,
        message=f"Finished stage: {stage}",
        stage=stage,
        payload=payload,
    )


def emit_error_event(
    session: Session,
    tenant_id: UUID,
    run_id: UUID,
    error_code: str,
    reason: str,
    stage: str | None = None,
    payload: dict | None = None,
) -> RunEventRow:
    """Emit an error event and transition run to failed status.

    Args:
        session: Database session
        tenant_id: Tenant ID
        run_id: Run ID
        error_code: Error code (e.g., "validation_error", "timeout")
        reason: Human-readable error reason
        stage: Optional stage where error occurred
        payload: Optional additional error context

    Returns:
        Created RunEventRow
    """
    event_payload = payload or {}
    event_payload["error_code"] = error_code
    event_payload["reason"] = reason

    # Emit error event
    event = emit_run_event(
        session=session,
        tenant_id=tenant_id,
        run_id=run_id,
        event_type=EVENT_TYPE_ERROR,
        level=RunEventLevelDb.error,
        message=f"Error: {reason}",
        stage=stage,
        payload=event_payload,
    )

    # Transition run to failed (if not already terminal)
    stmt = select(RunRow).where(RunRow.tenant_id == tenant_id, RunRow.id == run_id)
    run = session.execute(stmt).scalar_one_or_none()

    if run and run.status not in TERMINAL_STATES:
        try:
            transition_run_status(
                session=session,
                tenant_id=tenant_id,
                run_id=run_id,
                to_status=RunStatusDb.failed,
                failure_reason=reason,
                error_code=error_code,
                finished_at=datetime.now(UTC),
                current_stage=stage,
                emit_event=False,  # We already emitted the error event
            )
        except RunTransitionError:
            # Already in a terminal state or invalid transition, ignore
            pass

    return event


def check_cancel_requested(session: Session, tenant_id: UUID, run_id: UUID) -> bool:
    """Check if cancellation has been requested for a run.

    Args:
        session: Database session
        tenant_id: Tenant ID
        run_id: Run ID

    Returns:
        True if cancel_requested_at is set, False otherwise
    """
    stmt = select(RunRow.cancel_requested_at).where(
        RunRow.tenant_id == tenant_id, RunRow.id == run_id
    )
    result = session.execute(stmt).scalar_one_or_none()
    return result is not None


def request_cancel(
    session: Session, tenant_id: UUID, run_id: UUID, force_immediate: bool = False
) -> RunRow:
    """Request cancellation of a run.

    If the run is in a non-terminal state:
    - Sets cancel_requested_at timestamp
    - If force_immediate=True or run is queued, transitions to canceled immediately
    - Otherwise, sets the flag for cooperative cancellation (worker checks between stages)

    Args:
        session: Database session
        tenant_id: Tenant ID
        run_id: Run ID
        force_immediate: If True, cancel immediately regardless of state

    Returns:
        Updated RunRow

    Raises:
        RunNotFoundError: If run not found
    """
    stmt = (
        select(RunRow)
        .where(RunRow.tenant_id == tenant_id, RunRow.id == run_id)
        .with_for_update()
    )
    run = session.execute(stmt).scalar_one_or_none()

    if run is None:
        raise RunNotFoundError(f"Run {run_id} not found for tenant {tenant_id}")

    # If already terminal, nothing to do
    if run.status in TERMINAL_STATES:
        return run

    # Set cancel_requested_at
    cancel_ts = datetime.now(UTC)
    run.cancel_requested_at = cancel_ts
    run.updated_at = cancel_ts

    # Emit cancel request event
    emit_run_event(
        session=session,
        tenant_id=tenant_id,
        run_id=run_id,
        event_type=EVENT_TYPE_STATE,
        level=RunEventLevelDb.info,
        message="Cancel requested",
        payload={"cancel_requested_at": cancel_ts.isoformat()},
    )

    # If queued or force_immediate, cancel immediately
    if force_immediate or run.status == RunStatusDb.queued:
        try:
            transition_run_status(
                session=session,
                tenant_id=tenant_id,
                run_id=run_id,
                to_status=RunStatusDb.canceled,
                finished_at=cancel_ts,
                emit_event=True,
            )
        except RunTransitionError:
            # Already in a state that can't be canceled, ignore
            pass

    session.flush()
    return run


def retry_run(session: Session, tenant_id: UUID, run_id: UUID) -> RunRow:
    """Retry a failed or blocked run by resetting to queued status.

    Args:
        session: Database session
        tenant_id: Tenant ID
        run_id: Run ID

    Returns:
        Updated RunRow

    Raises:
        RunNotFoundError: If run not found
        RunTransitionError: If run is not in failed or blocked status
    """
    stmt = (
        select(RunRow)
        .where(RunRow.tenant_id == tenant_id, RunRow.id == run_id)
        .with_for_update()
    )
    run = session.execute(stmt).scalar_one_or_none()

    if run is None:
        raise RunNotFoundError(f"Run {run_id} not found for tenant {tenant_id}")

    # Only allow retry from failed or blocked states
    if run.status not in {RunStatusDb.failed, RunStatusDb.blocked}:
        raise RunTransitionError(
            f"Cannot retry run in status {run.status.value}. "
            f"Retry is only allowed for failed or blocked runs."
        )

    # Increment retry count
    run.retry_count += 1

    # Clear prior failure/cancel info for a clean retry view.
    run.failure_reason = None
    run.error_code = None
    run.finished_at = None
    run.cancel_requested_at = None
    run.current_stage = None

    # Transition to queued
    transition_run_status(
        session=session,
        tenant_id=tenant_id,
        run_id=run_id,
        to_status=RunStatusDb.queued,
        current_stage=None,  # Reset stage
        failure_reason=None,  # Cleared above (retained for clarity)
        error_code=None,
        finished_at=None,  # Cleared above
        cancel_requested_at=None,  # Cleared above
        emit_event=False,  # We'll emit our own event
    )

    # Emit retry event
    emit_run_event(
        session=session,
        tenant_id=tenant_id,
        run_id=run_id,
        event_type=EVENT_TYPE_STATE,
        level=RunEventLevelDb.info,
        message=f"Retry requested (attempt #{run.retry_count})",
        payload={"retry_count": run.retry_count},
    )

    session.flush()
    return run
