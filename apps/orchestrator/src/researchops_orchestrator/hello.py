from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import TypedDict
from uuid import UUID

from langgraph.graph import END, StateGraph
from sqlalchemy import select
from sqlalchemy.orm import Session

from db.models import ArtifactRow, JobRow, RunRow
from db.models.jobs import JobStatusDb
from db.models.runs import RunStatusDb
from researchops_core.audit.logger import write_audit_log
from researchops_core.auth.identity import Identity
from researchops_core.models import RunStatus
from researchops_observability.logging import bind_log_context

logger = logging.getLogger(__name__)


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


class HelloState(TypedDict):
    run_id: UUID
    tenant_id: str


def _create_run(state: HelloState, *, session: Session) -> HelloState:
    run = session.execute(
        select(RunRow).where(RunRow.id == state["run_id"], RunRow.tenant_id == state["tenant_id"])
    ).scalar_one_or_none()
    now = _now_utc()
    if run is None:
        run = RunRow(
            id=state["run_id"],
            tenant_id=state["tenant_id"],
            status=RunStatusDb.running,
            created_at=now,
            updated_at=now,
            error_message=None,
        )
        session.add(run)
    else:
        run.status = RunStatusDb.running
        run.updated_at = now
    bind_log_context(tenant_id_value=state["tenant_id"], run_id_value=str(state["run_id"]))
    logger.info("run_status_transition", extra={"to": RunStatus.running.value})
    return state


def _write_dummy_artifact(state: HelloState, *, session: Session) -> HelloState:
    now = _now_utc()
    identity = Identity(user_id="system", tenant_id=state["tenant_id"], roles=["owner"], raw_claims={})
    session.add(
        ArtifactRow(
            run_id=state["run_id"],
            tenant_id=state["tenant_id"],
            artifact_type="hello",
            payload_json={"message": "hello", "run_id": str(state["run_id"])},
            created_at=now,
        )
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
    return state


def _mark_succeeded(state: HelloState, *, session: Session) -> HelloState:
    run = session.execute(
        select(RunRow).where(RunRow.id == state["run_id"], RunRow.tenant_id == state["tenant_id"])
    ).scalar_one()
    run.status = RunStatusDb.succeeded
    run.updated_at = _now_utc()
    logger.info("run_status_transition", extra={"to": RunStatus.succeeded.value})
    return state


def _build_graph(*, session: Session):
    graph = StateGraph(HelloState)
    graph.add_node("create_run", lambda state: _create_run(state, session=session))
    graph.add_node("write_dummy_artifact", lambda state: _write_dummy_artifact(state, session=session))
    graph.add_node("mark_succeeded", lambda state: _mark_succeeded(state, session=session))
    graph.set_entry_point("create_run")
    graph.add_edge("create_run", "write_dummy_artifact")
    graph.add_edge("write_dummy_artifact", "mark_succeeded")
    graph.add_edge("mark_succeeded", END)
    return graph.compile()


def enqueue_hello_run(*, session: Session, tenant_id: str) -> UUID:
    now = _now_utc()
    run = RunRow(
        tenant_id=tenant_id,
        status=RunStatusDb.queued,
        created_at=now,
        updated_at=now,
        error_message=None,
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


def process_hello_run(*, session: Session, run_id: UUID, tenant_id: str) -> None:
    bind_log_context(tenant_id_value=tenant_id, run_id_value=str(run_id))
    graph = _build_graph(session=session)
    graph.invoke({"run_id": run_id, "tenant_id": tenant_id})
