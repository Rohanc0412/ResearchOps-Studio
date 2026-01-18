from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import TypedDict
from uuid import UUID

from langgraph.graph import END, StateGraph
from researchops_core.audit.logger import write_audit_log
from researchops_core.auth.identity import Identity
from researchops_core.models import RunStatus
from researchops_core.runs import (
    check_cancel_requested,
    emit_error_event,
    emit_stage_finish,
    emit_stage_start,
    transition_run_status,
)
from researchops_observability.logging import bind_log_context
from sqlalchemy import select
from sqlalchemy.orm import Session

from db.models import JobRow, ProjectRow, RunRow
from db.models.jobs import JobStatusDb
from db.models.runs import RunStatusDb
from db.services.truth import create_artifact, create_project

logger = logging.getLogger(__name__)


def _now_utc() -> datetime:
    return datetime.now(UTC)


class HelloState(TypedDict):
    run_id: UUID
    tenant_id: UUID


def _create_run(state: HelloState, *, session: Session) -> HelloState:
    """Transition run to running status and emit stage_start for first stage."""
    bind_log_context(tenant_id_value=str(state["tenant_id"]), run_id_value=str(state["run_id"]))

    # Check if cancellation was requested
    if check_cancel_requested(session=session, tenant_id=state["tenant_id"], run_id=state["run_id"]):
        logger.info("run_cancel_detected", extra={"stage": "create_run"})
        transition_run_status(
            session=session,
            tenant_id=state["tenant_id"],
            run_id=state["run_id"],
            to_status=RunStatusDb.canceled,
            finished_at=_now_utc(),
        )
        raise RuntimeError("Run was canceled")

    # Transition to running
    now = _now_utc()
    transition_run_status(
        session=session,
        tenant_id=state["tenant_id"],
        run_id=state["run_id"],
        to_status=RunStatusDb.running,
        started_at=now,
    )
    logger.info("run_status_transition", extra={"to": RunStatus.running.value})

    # Emit stage_start for the hello stage
    emit_stage_start(
        session=session,
        tenant_id=state["tenant_id"],
        run_id=state["run_id"],
        stage="retrieve",  # Using "retrieve" as the stage name for hello workflow
        payload={"step": "create_run"},
    )

    return state


def _write_dummy_artifact(state: HelloState, *, session: Session) -> HelloState:
    """Write a dummy artifact and emit stage events."""
    # Check for cancellation
    if check_cancel_requested(session=session, tenant_id=state["tenant_id"], run_id=state["run_id"]):
        logger.info("run_cancel_detected", extra={"stage": "write_dummy_artifact"})
        transition_run_status(
            session=session,
            tenant_id=state["tenant_id"],
            run_id=state["run_id"],
            to_status=RunStatusDb.canceled,
            finished_at=_now_utc(),
        )
        raise RuntimeError("Run was canceled")

    # Start ingest stage
    emit_stage_start(
        session=session,
        tenant_id=state["tenant_id"],
        run_id=state["run_id"],
        stage="ingest",
        payload={"step": "write_dummy_artifact"},
    )

    identity = Identity(
        user_id="system", tenant_id=str(state["tenant_id"]), roles=["owner"], raw_claims={}
    )
    run = session.execute(
        select(RunRow).where(RunRow.id == state["run_id"], RunRow.tenant_id == state["tenant_id"])
    ).scalar_one()

    try:
        create_artifact(
            session=session,
            tenant_id=state["tenant_id"],
            project_id=run.project_id,
            run_id=run.id,
            artifact_type="hello",
            blob_ref=f"inline://hello/{run.id}.json",
            mime_type="application/json",
            size_bytes=None,
            metadata_json={"message": "hello", "run_id": str(run.id)},
        )
        write_audit_log(
            db=session,
            identity=identity,
            action="artifact.write",
            target_type="artifact",
            target_id=str(state["run_id"]),
            metadata={"artifact_type": "hello"},
            request=None,
        )
        logger.info("artifact_written", extra={"artifact_type": "hello"})

        # Finish ingest stage
        emit_stage_finish(
            session=session,
            tenant_id=state["tenant_id"],
            run_id=state["run_id"],
            stage="ingest",
            payload={"artifact_type": "hello"},
        )
    except Exception as e:
        logger.error("artifact_write_failed", extra={"error": str(e)})
        emit_error_event(
            session=session,
            tenant_id=state["tenant_id"],
            run_id=state["run_id"],
            error_code="artifact_write_error",
            reason=str(e),
            stage="ingest",
        )
        raise

    return state


def _mark_succeeded(state: HelloState, *, session: Session) -> HelloState:
    """Mark run as succeeded and emit final stage events."""
    # Check for cancellation one last time
    if check_cancel_requested(session=session, tenant_id=state["tenant_id"], run_id=state["run_id"]):
        logger.info("run_cancel_detected", extra={"stage": "mark_succeeded"})
        transition_run_status(
            session=session,
            tenant_id=state["tenant_id"],
            run_id=state["run_id"],
            to_status=RunStatusDb.canceled,
            finished_at=_now_utc(),
        )
        raise RuntimeError("Run was canceled")

    # Emit stage_start and stage_finish for export (final stage)
    emit_stage_start(
        session=session,
        tenant_id=state["tenant_id"],
        run_id=state["run_id"],
        stage="export",
        payload={"step": "mark_succeeded"},
    )

    emit_stage_finish(
        session=session,
        tenant_id=state["tenant_id"],
        run_id=state["run_id"],
        stage="export",
        payload={"status": "succeeded"},
    )

    # Transition to succeeded
    now = _now_utc()
    transition_run_status(
        session=session,
        tenant_id=state["tenant_id"],
        run_id=state["run_id"],
        to_status=RunStatusDb.succeeded,
        finished_at=now,
    )
    logger.info("run_status_transition", extra={"to": RunStatus.succeeded.value})
    return state


def _build_graph(*, session: Session):
    graph = StateGraph(HelloState)
    graph.add_node("create_run", lambda state: _create_run(state, session=session))
    graph.add_node(
        "write_dummy_artifact", lambda state: _write_dummy_artifact(state, session=session)
    )
    graph.add_node("mark_succeeded", lambda state: _mark_succeeded(state, session=session))
    graph.set_entry_point("create_run")
    graph.add_edge("create_run", "write_dummy_artifact")
    graph.add_edge("write_dummy_artifact", "mark_succeeded")
    graph.add_edge("mark_succeeded", END)
    return graph.compile()


def enqueue_hello_run(*, session: Session, tenant_id: UUID) -> UUID:
    now = _now_utc()
    project = session.execute(
        select(ProjectRow).where(ProjectRow.tenant_id == tenant_id, ProjectRow.name == "Hello")
    ).scalar_one_or_none()
    if project is None:
        project = create_project(
            session=session,
            tenant_id=tenant_id,
            name="Hello",
            description="Hello pipeline project",
            created_by="system",
        )

    run = RunRow(
        tenant_id=tenant_id,
        project_id=project.id,
        status=RunStatusDb.queued,
        budgets_json={},
        usage_json={},
        created_at=now,
        updated_at=now,
    )
    session.add(run)
    session.flush()

    session.add(
        JobRow(
            run_id=run.id,
            tenant_id=tenant_id,
            job_type="hello.run",
            status=JobStatusDb.queued,
            attempts=0,
            last_error=None,
            created_at=now,
            updated_at=now,
        )
    )
    logger.info("run_enqueued", extra={"run_id": str(run.id), "tenant_id": tenant_id})
    return run.id


def process_hello_run(*, session: Session, run_id: UUID, tenant_id: UUID) -> None:
    """Process a hello run with proper error handling and cancellation support."""
    bind_log_context(tenant_id_value=str(tenant_id), run_id_value=str(run_id))

    try:
        graph = _build_graph(session=session)
        graph.invoke({"run_id": run_id, "tenant_id": tenant_id})
    except Exception as e:
        # Check if this was a cancellation
        if "canceled" in str(e).lower():
            logger.info("run_canceled", extra={"run_id": str(run_id)})
            # Already handled in the node that detected cancellation
        else:
            # Unexpected error - emit error event and mark as failed
            logger.error("run_failed", extra={"run_id": str(run_id), "error": str(e)})
            emit_error_event(
                session=session,
                tenant_id=tenant_id,
                run_id=run_id,
                error_code="workflow_error",
                reason=str(e),
            )
        raise
