from __future__ import annotations

import logging
import time
from threading import Event
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from db.init_db import init_db
from db.models import JobRow, RunRow
from db.models.jobs import JobStatusDb
from db.models.runs import RunStatusDb
from db.session import create_db_engine, create_sessionmaker, session_scope
from researchops_core import SERVICE_WORKER, get_settings
from researchops_observability import configure_logging
from researchops_orchestrator import process_hello_run

logger = logging.getLogger(__name__)


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _claim_next_job(session: Session) -> JobRow | None:
    stmt = (
        select(JobRow).where(JobRow.status == JobStatusDb.queued).order_by(JobRow.created_at.asc()).limit(1)
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
        update(JobRow).where(JobRow.id == job_id).values(status=JobStatusDb.succeeded, updated_at=_now_utc())
    )


def _mark_job_failed(session: Session, job_id: UUID, error: str) -> None:
    session.execute(
        update(JobRow)
        .where(JobRow.id == job_id)
        .values(status=JobStatusDb.failed, last_error=error, updated_at=_now_utc())
    )


def _mark_run_failed(session: Session, *, run_id: UUID, tenant_id: str, error: str) -> None:
    session.execute(
        update(RunRow)
        .where(RunRow.id == run_id, RunRow.tenant_id == tenant_id)
        .values(status=RunStatusDb.failed, error_message=error, updated_at=_now_utc())
    )

def run_forever(*, poll_seconds: float, stop_event: Event | None = None) -> None:
    settings = get_settings()
    engine = create_db_engine(settings)
    init_db(engine)
    SessionLocal = create_sessionmaker(engine)

    logger.info("worker_started")
    while stop_event is None or not stop_event.is_set():
        ran = run_once(SessionLocal=SessionLocal)
        if not ran:
            time.sleep(poll_seconds)


def run_once(*, SessionLocal) -> bool:
    with session_scope(SessionLocal) as session:
        job = _claim_next_job(session)
        if job is None:
            return False

        logger.info(
            "job_claimed", extra={"job_id": str(job.id), "job_type": job.job_type, "run_id": str(job.run_id)}
        )

        try:
            if job.job_type == "hello.run":
                process_hello_run(session=session, run_id=job.run_id, tenant_id=job.tenant_id)
            else:
                raise RuntimeError(f"Unknown job_type: {job.job_type}")
            _mark_job_done(session, job.id)
            logger.info("job_succeeded", extra={"job_id": str(job.id)})
        except Exception as e:
            err = str(e)
            _mark_job_failed(session, job.id, err)
            _mark_run_failed(session, run_id=job.run_id, tenant_id=job.tenant_id, error=err)
            logger.exception("job_failed", extra={"job_id": str(job.id)})
        return True


def main() -> None:
    settings = get_settings()
    configure_logging(SERVICE_WORKER, level=settings.log_level)
    run_forever(poll_seconds=settings.worker_poll_seconds)


if __name__ == "__main__":
    main()
