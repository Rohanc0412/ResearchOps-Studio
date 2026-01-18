"""Integration tests for run lifecycle state machine and SSE streaming."""

from __future__ import annotations

import time
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from db.init_db import init_db
from db.models import ProjectRow, RunRow
from db.models.runs import RunStatusDb
from db.services.truth import create_project, create_run, get_run, list_run_events
from researchops_core.runs import (
    RunNotFoundError,
    RunTransitionError,
    check_cancel_requested,
    emit_error_event,
    emit_stage_finish,
    emit_stage_start,
    request_cancel,
    retry_run,
    transition_run_status,
    validate_transition,
)


@pytest.fixture
def sqlite_engine():
    """Create a temporary SQLite database for testing."""
    engine = create_engine("sqlite:///:memory:", echo=False)
    init_db(engine=engine)
    return engine


@pytest.fixture
def session(sqlite_engine):
    """Create a test session."""
    SessionLocal = sessionmaker(bind=sqlite_engine)
    session = SessionLocal()
    try:
        yield session
    finally:
        session.rollback()
        session.close()


@pytest.fixture
def test_tenant_id():
    """Fixed tenant ID for tests."""
    return uuid4()


@pytest.fixture
def test_project(session, test_tenant_id):
    """Create a test project."""
    return create_project(
        session=session,
        tenant_id=test_tenant_id,
        name="Test Project",
        description="For testing",
        created_by="test_user",
    )


@pytest.fixture
def test_run(session, test_tenant_id, test_project):
    """Create a test run."""
    run = create_run(
        session=session,
        tenant_id=test_tenant_id,
        project_id=test_project.id,
        status=RunStatusDb.created,
    )
    session.commit()
    return run


class TestStateTransitions:
    """Test run state machine transitions."""

    def test_allowed_transitions(self):
        """Test that allowed transitions are validated correctly."""
        # created -> queued is allowed
        validate_transition(RunStatusDb.created, RunStatusDb.queued)

        # queued -> running is allowed
        validate_transition(RunStatusDb.queued, RunStatusDb.running)

        # running -> succeeded is allowed
        validate_transition(RunStatusDb.running, RunStatusDb.succeeded)

        # running -> failed is allowed
        validate_transition(RunStatusDb.running, RunStatusDb.failed)

        # running -> canceled is allowed
        validate_transition(RunStatusDb.running, RunStatusDb.canceled)

        # Same state is always allowed (idempotent)
        validate_transition(RunStatusDb.running, RunStatusDb.running)

    def test_illegal_transitions(self):
        """Test that illegal transitions are rejected."""
        # succeeded is terminal
        with pytest.raises(RunTransitionError, match="Illegal transition"):
            validate_transition(RunStatusDb.succeeded, RunStatusDb.running)

        # canceled is terminal
        with pytest.raises(RunTransitionError, match="Illegal transition"):
            validate_transition(RunStatusDb.canceled, RunStatusDb.running)

        # created cannot go directly to succeeded
        with pytest.raises(RunTransitionError, match="Illegal transition"):
            validate_transition(RunStatusDb.created, RunStatusDb.succeeded)

    def test_transition_run_status(self, session, test_tenant_id, test_run):
        """Test atomic state transition."""
        # created -> queued
        updated_run = transition_run_status(
            session=session,
            tenant_id=test_tenant_id,
            run_id=test_run.id,
            to_status=RunStatusDb.queued,
        )
        assert updated_run.status == RunStatusDb.queued
        session.commit()

        # queued -> running
        updated_run = transition_run_status(
            session=session,
            tenant_id=test_tenant_id,
            run_id=test_run.id,
            to_status=RunStatusDb.running,
            started_at=datetime.now(UTC),
        )
        assert updated_run.status == RunStatusDb.running
        assert updated_run.started_at is not None
        session.commit()

        # running -> succeeded
        updated_run = transition_run_status(
            session=session,
            tenant_id=test_tenant_id,
            run_id=test_run.id,
            to_status=RunStatusDb.succeeded,
            finished_at=datetime.now(UTC),
        )
        assert updated_run.status == RunStatusDb.succeeded
        assert updated_run.finished_at is not None
        session.commit()

    def test_transition_emits_event(self, session, test_tenant_id, test_run):
        """Test that transitions emit state change events."""
        # Transition to queued
        transition_run_status(
            session=session,
            tenant_id=test_tenant_id,
            run_id=test_run.id,
            to_status=RunStatusDb.queued,
        )
        session.commit()

        # Check that event was emitted
        events = list_run_events(session=session, tenant_id=test_tenant_id, run_id=test_run.id)
        assert len(events) > 0
        state_events = [e for e in events if e.event_type == "state"]
        assert len(state_events) == 1
        assert "created -> queued" in state_events[0].message

    def test_transition_nonexistent_run(self, session, test_tenant_id):
        """Test that transitioning a nonexistent run raises error."""
        fake_run_id = uuid4()
        with pytest.raises(RunNotFoundError, match="not found"):
            transition_run_status(
                session=session,
                tenant_id=test_tenant_id,
                run_id=fake_run_id,
                to_status=RunStatusDb.running,
            )


class TestCancellation:
    """Test run cancellation."""

    def test_cancel_queued_run(self, session, test_tenant_id, test_run):
        """Test that canceling a queued run transitions immediately to canceled."""
        # Transition to queued
        transition_run_status(
            session=session,
            tenant_id=test_tenant_id,
            run_id=test_run.id,
            to_status=RunStatusDb.queued,
        )
        session.commit()

        # Request cancel
        updated_run = request_cancel(
            session=session,
            tenant_id=test_tenant_id,
            run_id=test_run.id,
        )
        session.commit()

        # Should transition to canceled immediately
        assert updated_run.status == RunStatusDb.canceled
        assert updated_run.cancel_requested_at is not None
        assert updated_run.finished_at is not None

    def test_cancel_running_run_cooperative(self, session, test_tenant_id, test_run):
        """Test that canceling a running run sets the flag for cooperative cancellation."""
        # Transition to running
        transition_run_status(
            session=session,
            tenant_id=test_tenant_id,
            run_id=test_run.id,
            to_status=RunStatusDb.queued,
        )
        transition_run_status(
            session=session,
            tenant_id=test_tenant_id,
            run_id=test_run.id,
            to_status=RunStatusDb.running,
        )
        session.commit()

        # Request cancel
        updated_run = request_cancel(
            session=session,
            tenant_id=test_tenant_id,
            run_id=test_run.id,
        )
        session.commit()

        # Should set cancel_requested_at but may not transition immediately
        assert updated_run.cancel_requested_at is not None

        # Check cancel flag
        assert check_cancel_requested(session=session, tenant_id=test_tenant_id, run_id=test_run.id)

    def test_cancel_terminal_run_is_noop(self, session, test_tenant_id, test_run):
        """Test that canceling an already terminal run is a no-op."""
        # Transition to succeeded
        transition_run_status(
            session=session,
            tenant_id=test_tenant_id,
            run_id=test_run.id,
            to_status=RunStatusDb.queued,
        )
        transition_run_status(
            session=session,
            tenant_id=test_tenant_id,
            run_id=test_run.id,
            to_status=RunStatusDb.running,
        )
        transition_run_status(
            session=session,
            tenant_id=test_tenant_id,
            run_id=test_run.id,
            to_status=RunStatusDb.succeeded,
        )
        session.commit()

        # Request cancel
        updated_run = request_cancel(
            session=session,
            tenant_id=test_tenant_id,
            run_id=test_run.id,
        )
        session.commit()

        # Should remain succeeded
        assert updated_run.status == RunStatusDb.succeeded


class TestRetry:
    """Test run retry."""

    def test_retry_failed_run(self, session, test_tenant_id, test_run):
        """Test that retrying a failed run resets it to queued."""
        # Transition to failed
        transition_run_status(
            session=session,
            tenant_id=test_tenant_id,
            run_id=test_run.id,
            to_status=RunStatusDb.queued,
        )
        transition_run_status(
            session=session,
            tenant_id=test_tenant_id,
            run_id=test_run.id,
            to_status=RunStatusDb.running,
        )
        transition_run_status(
            session=session,
            tenant_id=test_tenant_id,
            run_id=test_run.id,
            to_status=RunStatusDb.failed,
            failure_reason="Test failure",
            error_code="test_error",
        )
        session.commit()

        # Retry
        updated_run = retry_run(
            session=session,
            tenant_id=test_tenant_id,
            run_id=test_run.id,
        )
        session.commit()

        # Should be queued again
        assert updated_run.status == RunStatusDb.queued
        assert updated_run.retry_count == 1
        assert updated_run.failure_reason is None
        assert updated_run.error_code is None
        assert updated_run.finished_at is None

    def test_retry_succeeded_run_fails(self, session, test_tenant_id, test_run):
        """Test that retrying a succeeded run raises error."""
        # Transition to succeeded
        transition_run_status(
            session=session,
            tenant_id=test_tenant_id,
            run_id=test_run.id,
            to_status=RunStatusDb.queued,
        )
        transition_run_status(
            session=session,
            tenant_id=test_tenant_id,
            run_id=test_run.id,
            to_status=RunStatusDb.running,
        )
        transition_run_status(
            session=session,
            tenant_id=test_tenant_id,
            run_id=test_run.id,
            to_status=RunStatusDb.succeeded,
        )
        session.commit()

        # Retry should fail
        with pytest.raises(RunTransitionError, match="Cannot retry"):
            retry_run(
                session=session,
                tenant_id=test_tenant_id,
                run_id=test_run.id,
            )


class TestStageEvents:
    """Test stage event emission."""

    def test_emit_stage_start(self, session, test_tenant_id, test_run):
        """Test emitting stage_start event."""
        emit_stage_start(
            session=session,
            tenant_id=test_tenant_id,
            run_id=test_run.id,
            stage="retrieve",
            payload={"test": "data"},
        )
        session.commit()

        # Check event
        events = list_run_events(session=session, tenant_id=test_tenant_id, run_id=test_run.id)
        assert len(events) == 1
        assert events[0].event_type == "stage_start"
        assert events[0].stage == "retrieve"
        assert events[0].message == "Starting stage: retrieve"

        # Check that current_stage was updated
        run = get_run(session=session, tenant_id=test_tenant_id, run_id=test_run.id)
        assert run.current_stage == "retrieve"

    def test_emit_stage_start_idempotent(self, session, test_tenant_id, test_run):
        """Test that emitting stage_start twice is idempotent."""
        emit_stage_start(
            session=session,
            tenant_id=test_tenant_id,
            run_id=test_run.id,
            stage="retrieve",
        )
        session.commit()

        emit_stage_start(
            session=session,
            tenant_id=test_tenant_id,
            run_id=test_run.id,
            stage="retrieve",
        )
        session.commit()

        # Should only have one stage_start event
        events = list_run_events(session=session, tenant_id=test_tenant_id, run_id=test_run.id)
        stage_start_events = [e for e in events if e.event_type == "stage_start"]
        assert len(stage_start_events) == 1

    def test_emit_stage_finish(self, session, test_tenant_id, test_run):
        """Test emitting stage_finish event."""
        emit_stage_finish(
            session=session,
            tenant_id=test_tenant_id,
            run_id=test_run.id,
            stage="retrieve",
            payload={"duration": 1.5},
        )
        session.commit()

        # Check event
        events = list_run_events(session=session, tenant_id=test_tenant_id, run_id=test_run.id)
        assert len(events) == 1
        assert events[0].event_type == "stage_finish"
        assert events[0].stage == "retrieve"

    def test_emit_error_event(self, session, test_tenant_id, test_run):
        """Test emitting error event transitions run to failed."""
        # First transition to running
        transition_run_status(
            session=session,
            tenant_id=test_tenant_id,
            run_id=test_run.id,
            to_status=RunStatusDb.queued,
        )
        transition_run_status(
            session=session,
            tenant_id=test_tenant_id,
            run_id=test_run.id,
            to_status=RunStatusDb.running,
        )
        session.commit()

        # Emit error
        emit_error_event(
            session=session,
            tenant_id=test_tenant_id,
            run_id=test_run.id,
            error_code="test_error",
            reason="Test error message",
            stage="retrieve",
        )
        session.commit()

        # Check run is failed
        run = get_run(session=session, tenant_id=test_tenant_id, run_id=test_run.id)
        assert run.status == RunStatusDb.failed
        assert run.error_code == "test_error"
        assert run.failure_reason == "Test error message"

        # Check error event
        events = list_run_events(session=session, tenant_id=test_tenant_id, run_id=test_run.id)
        error_events = [e for e in events if e.event_type == "error"]
        assert len(error_events) == 1
        assert error_events[0].level.value == "error"


class TestEventOrdering:
    """Test event ordering and SSE support."""

    def test_events_have_sequential_numbers(self, session, test_tenant_id, test_run):
        """Test that events get sequential event_number values."""
        # Emit multiple events
        emit_stage_start(session=session, tenant_id=test_tenant_id, run_id=test_run.id, stage="retrieve")
        session.commit()

        emit_stage_finish(session=session, tenant_id=test_tenant_id, run_id=test_run.id, stage="retrieve")
        session.commit()

        emit_stage_start(session=session, tenant_id=test_tenant_id, run_id=test_run.id, stage="ingest")
        session.commit()

        # Get events
        events = list_run_events(session=session, tenant_id=test_tenant_id, run_id=test_run.id)

        # Should have sequential event numbers
        assert len(events) == 3
        event_numbers = [e.event_number for e in events]
        assert event_numbers == sorted(event_numbers)
        # Event numbers should be unique
        assert len(set(event_numbers)) == len(event_numbers)

    def test_list_events_after_event_number(self, session, test_tenant_id, test_run):
        """Test filtering events by after_event_number for SSE reconnect."""
        # Emit several events
        emit_stage_start(session=session, tenant_id=test_tenant_id, run_id=test_run.id, stage="retrieve")
        session.commit()

        emit_stage_finish(session=session, tenant_id=test_tenant_id, run_id=test_run.id, stage="retrieve")
        session.commit()

        emit_stage_start(session=session, tenant_id=test_tenant_id, run_id=test_run.id, stage="ingest")
        session.commit()

        # Get all events
        all_events = list_run_events(session=session, tenant_id=test_tenant_id, run_id=test_run.id)
        assert len(all_events) == 3

        # Get events after the first event
        first_event_number = all_events[0].event_number
        new_events = list_run_events(
            session=session,
            tenant_id=test_tenant_id,
            run_id=test_run.id,
            after_event_number=first_event_number,
        )

        # Should only get the last 2 events
        assert len(new_events) == 2
        assert new_events[0].event_number > first_event_number
        assert new_events[1].event_number > first_event_number
