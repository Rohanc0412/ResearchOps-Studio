from __future__ import annotations

import asyncio
import time
from datetime import UTC, datetime
from threading import Event
from uuid import UUID

from core import get_settings
from core.constants import SERVICE_WORKER
from core.env import resolve_env_files
from db.init_db import init_db
from db.models import JobRow, RunRow
from db.models.jobs import JobStatusDb
from db.models.runs import RunStatusDb
from db.session import create_db_engine, create_sessionmaker, session_scope
from dotenv import load_dotenv
from observability import setup_logging
from research import RESEARCH_JOB_TYPE, process_research_run
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import Session

ORPHANED_JOB_RECOVERY_ERROR = "Recovered orphaned running job after service restart"
ORPHANED_RUN_RECOVERY_ERROR_CODE = "stale_running_recovered"


def _now_utc() -> datetime:
    return datetime.now(UTC)


async def _claim_next_job(session: AsyncSession) -> JobRow | None:
    stmt = (
        select(JobRow)
        .where(JobRow.status == JobStatusDb.queued)
        .order_by(JobRow.created_at.asc())
        .limit(1)
    )
    sync_engine = session.sync_session.get_bind()
    if sync_engine.dialect.name != "sqlite":
        stmt = stmt.with_for_update(skip_locked=True)
    job = (await session.execute(stmt)).scalars().first()
    if job is None:
        return None
    job.status = JobStatusDb.running
    job.attempts = job.attempts + 1
    job.updated_at = _now_utc()
    return job


async def _mark_job_done(session: AsyncSession, job_id: UUID) -> None:
    await session.execute(
        update(JobRow)
        .where(JobRow.id == job_id)
        .values(status=JobStatusDb.succeeded, updated_at=_now_utc())
    )


async def _mark_job_failed(session: AsyncSession, job_id: UUID, error: str) -> None:
    await session.execute(
        update(JobRow)
        .where(JobRow.id == job_id)
        .values(status=JobStatusDb.failed, last_error=error, updated_at=_now_utc())
    )


async def _mark_run_failed(
    session: AsyncSession, *, run_id: UUID, tenant_id: UUID, error: str
) -> None:
    now = _now_utc()
    await session.execute(
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


async def recover_orphaned_jobs(SessionLocal: async_sessionmaker[AsyncSession]) -> int:
    async with session_scope(SessionLocal) as session:
        now = _now_utc()
        recovered_run_ids: set[UUID] = set()

        running_jobs = (await session.execute(
            select(JobRow).where(JobRow.status == JobStatusDb.running)
        )).scalars().all()
        for job in running_jobs:
            job.status = JobStatusDb.failed
            job.last_error = ORPHANED_JOB_RECOVERY_ERROR
            job.updated_at = now
            recovered_run_ids.add(job.run_id)
            await session.execute(
                update(RunRow)
                .where(RunRow.id == job.run_id, RunRow.tenant_id == job.tenant_id)
                .values(
                    status=RunStatusDb.failed,
                    failure_reason=ORPHANED_JOB_RECOVERY_ERROR,
                    error_code=ORPHANED_RUN_RECOVERY_ERROR_CODE,
                    finished_at=now,
                    updated_at=now,
                )
            )

        active_job_run_ids = set(
            (await session.execute(
                select(JobRow.run_id).where(
                    JobRow.status.in_([JobStatusDb.queued, JobStatusDb.running])
                )
            )).scalars()
        )
        stale_runs = [
            run
            for run in (await session.execute(
                select(RunRow).where(RunRow.status == RunStatusDb.running)
            )).scalars().all()
            if run.id not in active_job_run_ids
        ]
        for run in stale_runs:
            if run.id in recovered_run_ids:
                continue
            run.status = RunStatusDb.failed
            run.failure_reason = ORPHANED_JOB_RECOVERY_ERROR
            run.error_code = ORPHANED_RUN_RECOVERY_ERROR_CODE
            run.finished_at = now
            run.updated_at = now
            recovered_run_ids.add(run.id)

        return len(recovered_run_ids)


def _claim_next_job_sync(session: Session) -> JobRow | None:
    stmt = (
        select(JobRow)
        .where(JobRow.status == JobStatusDb.queued)
        .order_by(JobRow.created_at.asc())
        .limit(1)
    )
    bind = session.get_bind()
    if hasattr(bind, "dialect") and bind.dialect.name != "sqlite":
        stmt = stmt.with_for_update(skip_locked=True)
    job = session.execute(stmt).scalars().first()
    if job is None:
        return None
    job.status = JobStatusDb.running
    job.attempts = job.attempts + 1
    job.updated_at = _now_utc()
    return job


def _mark_job_done_sync(session: Session, job_id: UUID) -> None:
    job = session.get(JobRow, job_id)
    if job is not None:
        job.status = JobStatusDb.succeeded
        job.updated_at = _now_utc()


def _mark_job_failed_sync(session: Session, job_id: UUID, error: str) -> None:
    job = session.get(JobRow, job_id)
    if job is not None:
        job.status = JobStatusDb.failed
        job.last_error = error
        job.updated_at = _now_utc()


def _mark_run_failed_sync(
    session: Session, *, run_id: UUID, tenant_id: UUID, error: str
) -> None:
    now = _now_utc()
    run = session.get(RunRow, run_id)
    if run is not None and run.tenant_id == tenant_id:
        run.status = RunStatusDb.failed
        run.failure_reason = error
        run.error_code = "worker_error"
        run.finished_at = now
        run.updated_at = now


def recover_orphaned_jobs_sync(session: Session) -> int:
    now = _now_utc()
    recovered_run_ids: set[UUID] = set()

    running_jobs = session.execute(
        select(JobRow).where(JobRow.status == JobStatusDb.running)
    ).scalars().all()
    for job in running_jobs:
        job.status = JobStatusDb.failed
        job.last_error = ORPHANED_JOB_RECOVERY_ERROR
        job.updated_at = now
        recovered_run_ids.add(job.run_id)
        session.execute(
            update(RunRow)
            .where(RunRow.id == job.run_id, RunRow.tenant_id == job.tenant_id)
            .values(
                status=RunStatusDb.failed,
                failure_reason=ORPHANED_JOB_RECOVERY_ERROR,
                error_code=ORPHANED_RUN_RECOVERY_ERROR_CODE,
                finished_at=now,
                updated_at=now,
            )
        )

    active_job_run_ids = set(
        session.execute(
            select(JobRow.run_id).where(
                JobRow.status.in_([JobStatusDb.queued, JobStatusDb.running])
            )
        ).scalars()
    )
    stale_runs = [
        run
        for run in session.execute(
            select(RunRow).where(RunRow.status == RunStatusDb.running)
        ).scalars().all()
        if run.id not in active_job_run_ids
    ]
    for run in stale_runs:
        if run.id in recovered_run_ids:
            continue
        run.status = RunStatusDb.failed
        run.failure_reason = ORPHANED_JOB_RECOVERY_ERROR
        run.error_code = ORPHANED_RUN_RECOVERY_ERROR_CODE
        run.finished_at = now
        run.updated_at = now
        recovered_run_ids.add(run.id)

    return len(recovered_run_ids)


def run_once_sync(*, SessionLocal) -> bool:
    import inspect

    with SessionLocal() as session:
        job = _claim_next_job_sync(session)
        if job is None:
            session.commit()
            return False
        job_id = job.id
        run_id = job.run_id
        tenant_id = job.tenant_id
        job_type = job.job_type
        session.commit()

    try:
        with SessionLocal() as session:
            if job_type == RESEARCH_JOB_TYPE:
                result = process_research_run(
                    session=session, run_id=run_id, tenant_id=tenant_id
                )
                if inspect.isawaitable(result):
                    asyncio.run(result)
            else:
                raise RuntimeError(f"Unknown job_type: {job_type}")
            session.commit()
        with SessionLocal() as session:
            _mark_job_done_sync(session, job_id)
            session.commit()
    except Exception as e:
        err = str(e)
        with SessionLocal() as session:
            _mark_job_failed_sync(session, job_id, err)
            _mark_run_failed_sync(session, run_id=run_id, tenant_id=tenant_id, error=err)
            session.commit()
    finally:
        from embeddings import release_gpu_memory
        release_gpu_memory()

    return True


def run_once(*, SessionLocal: async_sessionmaker[AsyncSession]) -> bool:
    async def _inner():
        async with session_scope(SessionLocal) as session:
            job = await _claim_next_job(session)
            if job is None:
                return False, None, None, None, None
            return True, job.id, job.run_id, job.tenant_id, job.job_type

    found, job_id, run_id, tenant_id, job_type = asyncio.run(_inner())
    if not found:
        return False

    try:
        async def _process() -> None:
            async with session_scope(SessionLocal) as session:
                if job_type == RESEARCH_JOB_TYPE:
                    await process_research_run(
                        session=session, run_id=run_id, tenant_id=tenant_id
                    )
                else:
                    raise RuntimeError(f"Unknown job_type: {job_type}")

        asyncio.run(_process())
        asyncio.run(_finish(SessionLocal, job_id))
    except Exception as e:
        err = str(e)
        asyncio.run(_fail(SessionLocal, job_id, run_id, tenant_id, err))
    finally:
        from embeddings import release_gpu_memory
        release_gpu_memory()

    return True


async def _finish(SessionLocal, job_id):
    async with session_scope(SessionLocal) as session:
        await _mark_job_done(session, job_id)


async def _fail(SessionLocal, job_id, run_id, tenant_id, err):
    async with session_scope(SessionLocal) as session:
        await _mark_job_failed(session, job_id, err)
        await _mark_run_failed(session, run_id=run_id, tenant_id=tenant_id, error=err)


def run_forever(*, poll_seconds: float, stop_event: Event | None = None) -> None:
    settings = get_settings()
    engine = create_db_engine(settings)
    init_db(engine)
    SessionLocal = create_sessionmaker(engine)

    asyncio.run(recover_orphaned_jobs(SessionLocal))

    while stop_event is None or not stop_event.is_set():
        ran = run_once(SessionLocal=SessionLocal)
        if not ran:
            time.sleep(poll_seconds)


def main() -> None:
    for env_file in resolve_env_files():
        load_dotenv(env_file, override=False)
    setup_logging(SERVICE_WORKER)
    settings = get_settings()
    run_forever(poll_seconds=settings.worker_poll_seconds)


if __name__ == "__main__":
    main()
