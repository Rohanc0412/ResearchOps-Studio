from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from db.models import JobRow, RunRow
from db.models.jobs import JobStatusDb
from db.models.runs import RunStatusDb



def _now_utc() -> datetime:
    return datetime.now(UTC)


def enqueue_run_job(*, session: Session, tenant_id: UUID, run_id: UUID, job_type: str) -> UUID:
    """Ensure a queued job exists for the run."""
    existing = (
        session.execute(
            select(JobRow.id)
            .where(
                JobRow.tenant_id == tenant_id,
                JobRow.run_id == run_id,
                JobRow.status.in_([JobStatusDb.queued, JobStatusDb.running]),
            )
            .order_by(JobRow.created_at.desc())
        )
        .scalars()
        .first()
    )
    if existing:
        return existing

    run = (
        session.execute(
            select(RunRow).where(RunRow.tenant_id == tenant_id, RunRow.id == run_id)
        )
        .scalars()
        .first()
    )
    if run is None:
        raise ValueError("run not found")

    now = _now_utc()
    if run.status == RunStatusDb.created:
        run.status = RunStatusDb.queued
        run.updated_at = now

    job = JobRow(
        run_id=run.id,
        tenant_id=tenant_id,
        job_type=job_type,
        status=JobStatusDb.queued,
        attempts=0,
        last_error=None,
        created_at=now,
        updated_at=now,
    )
    session.add(job)
    session.flush()
    return job.id
