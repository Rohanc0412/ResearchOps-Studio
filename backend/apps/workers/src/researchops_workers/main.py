from __future__ import annotations

import time
from datetime import UTC, datetime
from threading import Event
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from db.init_db import init_db
from db.models import JobRow, RunRow
from db.models.jobs import JobStatusDb
from db.models.runs import RunStatusDb
from db.session import create_db_engine, create_sessionmaker, session_scope
from researchops_core import get_settings
from researchops_core.constants import SERVICE_WORKER
from researchops_observability import setup_logging
from researchops_orchestrator import RESEARCH_JOB_TYPE, process_research_run



def _now_utc() -> datetime:
    return datetime.now(UTC)


def _claim_next_job(session: Session) -> JobRow | None:
    stmt = (
        select(JobRow)
        .where(JobRow.status == JobStatusDb.queued)
        .order_by(JobRow.created_at.asc())
        .limit(1)
    )
    # SQLite doesn't support SKIP LOCKED; this code path is for local tests only.
    if session.get_bind().dialect.name != "sqlite":
        stmt = stmt.with_for_update(skip_locked=True)
    job = session.execute(stmt).scalars().first()
    if job is None:
        return None
    job.status = JobStatusDb.running
    job.attempts = job.attempts + 1
    job.updated_at = _now_utc()
    return job


def _mark_job_done(session: Session, job_id: UUID) -> None:
    session.execute(
        update(JobRow)
        .where(JobRow.id == job_id)
        .values(status=JobStatusDb.succeeded, updated_at=_now_utc())
    )


def _mark_job_failed(session: Session, job_id: UUID, error: str) -> None:
    session.execute(
        update(JobRow)
        .where(JobRow.id == job_id)
        .values(status=JobStatusDb.failed, last_error=error, updated_at=_now_utc())
    )


def _mark_run_failed(session: Session, *, run_id: UUID, tenant_id: UUID, error: str) -> None:
    now = _now_utc()
    session.execute(
        update(RunRow)
        .where(RunRow.id == run_id, RunRow.tenant_id == tenant_id)
        .values(
            status=RunStatusDb.failed,
            failure_reason=error,
            error_code="worker_error",
            finished_at=now,
            updated_at=now,
        )
    )


def run_forever(*, poll_seconds: float, stop_event: Event | None = None) -> None:
    settings = get_settings()
    engine = create_db_engine(settings)
    init_db(engine)
    SessionLocal = create_sessionmaker(engine)

    while stop_event is None or not stop_event.is_set():
        ran = run_once(SessionLocal=SessionLocal)
        if not ran:
            time.sleep(poll_seconds)


def run_once(*, SessionLocal) -> bool:
    with session_scope(SessionLocal) as session:
        job = _claim_next_job(session)
        if job is None:
            return False

        job_id = job.id
        run_id = job.run_id
        tenant_id = job.tenant_id
        job_type = job.job_type
        try:
            if job_type == RESEARCH_JOB_TYPE:
                process_research_run(session=session, run_id=run_id, tenant_id=tenant_id)
            else:
                raise RuntimeError(f"Unknown job_type: {job_type}")
            _mark_job_done(session, job_id)
        except Exception as e:
            err = str(e)
            session.rollback()
            _mark_job_failed(session, job_id, err)
            _mark_run_failed(session, run_id=run_id, tenant_id=tenant_id, error=err)
        return True


def main() -> None:
    setup_logging(SERVICE_WORKER)
    settings = get_settings()
    run_forever(poll_seconds=settings.worker_poll_seconds)


if __name__ == "__main__":
    main()
