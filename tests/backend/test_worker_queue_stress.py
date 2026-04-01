"""
Load and stress tests for the database-driven worker queue.

Tests cover:
- Concurrent job claiming (SKIP LOCKED semantics on PostgreSQL)
- FIFO ordering under concurrent insertion
- Orphan recovery with many stale jobs
- Failure handling: job and run marked failed on worker error
- Job deduplication in enqueue_run_job
- Throughput: N jobs processed sequentially with mock processors
"""

from __future__ import annotations

import os
import threading
import time
from typing import Any
from unittest.mock import patch
from uuid import UUID, uuid4

import pytest
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import Session, sessionmaker

from db.init_db import init_db_sync as init_db
from db.models import JobRow, ProjectRow, RunRow
from db.models.jobs import JobStatusDb
from db.models.runs import RunStatusDb
from services.orchestrator.job_queue import enqueue_run_job
from services.workers.main import (
    ORPHANED_JOB_RECOVERY_ERROR,
    _claim_next_job_sync as _claim_next_job,
    _mark_job_done_sync as _mark_job_done,
    _mark_job_failed_sync as _mark_job_failed,
    _mark_run_failed_sync as _mark_run_failed,
    recover_orphaned_jobs_sync as recover_orphaned_jobs,
    run_once_sync as run_once,
)

RESEARCH_JOB_TYPE = "research.run"


# ── Fixtures ─────────────────────────────────────────────────────────────────

_DEFAULT_PG_URL = "postgresql+psycopg://postgres:postgres@localhost:5432/researchops_test"


def _ensure_test_db(url: str) -> None:
    """Create the test database if it doesn't exist (cannot run inside a transaction)."""
    from sqlalchemy.engine import make_url
    from sqlalchemy import event

    u = make_url(url)
    db_name = u.database
    admin_url = u.set(database="postgres")
    admin_engine = create_engine(admin_url, isolation_level="AUTOCOMMIT")
    try:
        with admin_engine.connect() as conn:
            exists = conn.execute(
                text("SELECT 1 FROM pg_database WHERE datname = :name"),
                {"name": db_name},
            ).scalar()
            if not exists:
                conn.execute(text(f'CREATE DATABASE "{db_name}"'))
    finally:
        admin_engine.dispose()


@pytest.fixture(scope="module")
def engine():
    url = os.environ.get("TEST_DATABASE_URL", _DEFAULT_PG_URL)
    try:
        _ensure_test_db(url)
        eng = create_engine(url, echo=False)
        with eng.connect():
            pass  # fail fast if PostgreSQL is unreachable
    except Exception:
        pytest.skip(
            "PostgreSQL not available — run `docker compose -f backend/deployment/compose.yaml up -d postgres` or set TEST_DATABASE_URL"
        )
    init_db(engine=eng)
    yield eng
    # Drop all tables after the module so each test run starts clean.
    with eng.begin() as conn:
        conn.execute(text("DROP SCHEMA public CASCADE; CREATE SCHEMA public;"))
    eng.dispose()


@pytest.fixture(autouse=True)
def clean_tables(engine):
    """Truncate all queue-related tables before every test so committed data
    from one test never leaks into the next."""
    with engine.begin() as conn:
        conn.execute(text("TRUNCATE jobs, runs, projects RESTART IDENTITY CASCADE"))
    yield


@pytest.fixture()
def SessionLocal(engine):
    return sessionmaker(bind=engine)


@pytest.fixture()
def session(engine):
    """Each test gets a transaction that is rolled back on teardown."""
    conn = engine.connect()
    trans = conn.begin()
    s = Session(bind=conn)
    yield s
    s.close()
    trans.rollback()
    conn.close()


def _make_tenant_project_run(
    session: Session,
    *,
    run_status: RunStatusDb = RunStatusDb.created,
    question: str = "test",
) -> tuple[UUID, UUID, UUID]:
    """Insert project + run and return (tenant_id, project_id, run_id)."""
    tenant_id = uuid4()
    project = ProjectRow(tenant_id=tenant_id, name=f"proj-{uuid4()}", created_by="test")
    session.add(project)
    session.flush()
    run = RunRow(
        id=uuid4(),
        tenant_id=tenant_id,
        project_id=project.id,
        status=run_status,
        question=question,
    )
    session.add(run)
    session.flush()
    return tenant_id, project.id, run.id


# ── Job claiming ──────────────────────────────────────────────────────────────


def test_claim_returns_none_when_queue_empty(session):
    job = _claim_next_job(session)
    assert job is None


def test_claim_transitions_job_to_running(session):
    tenant_id, _, run_id = _make_tenant_project_run(session)
    enqueue_run_job(session=session, tenant_id=tenant_id, run_id=run_id, job_type=RESEARCH_JOB_TYPE)
    session.flush()

    job = _claim_next_job(session)
    assert job is not None
    assert job.status == JobStatusDb.running
    assert job.attempts == 1


def test_claim_increments_attempts_counter(session):
    tenant_id, _, run_id = _make_tenant_project_run(session)
    job_id = enqueue_run_job(
        session=session, tenant_id=tenant_id, run_id=run_id, job_type=RESEARCH_JOB_TYPE
    )
    session.flush()

    job = _claim_next_job(session)
    assert job.attempts == 1

    # Reset to queued and claim again (simulates retry scenario)
    job.status = JobStatusDb.queued
    session.flush()
    job2 = _claim_next_job(session)
    assert job2.attempts == 2


def test_claim_fifo_order(session):
    """Jobs are claimed in insertion order (FIFO)."""
    run_ids: list[UUID] = []
    for i in range(5):
        tenant_id, _, run_id = _make_tenant_project_run(session, question=f"q{i}")
        enqueue_run_job(
            session=session, tenant_id=tenant_id, run_id=run_id, job_type=RESEARCH_JOB_TYPE
        )
        run_ids.append(run_id)
        session.flush()

    claimed_order: list[UUID] = []
    for _ in range(5):
        job = _claim_next_job(session)
        assert job is not None
        claimed_order.append(job.run_id)
        session.flush()

    assert claimed_order == run_ids, "Jobs must be claimed in FIFO (insertion) order"


def test_claim_skips_already_running_jobs(session):
    """A running job is not claimed again by a second worker."""
    tenant_id, _, run_id = _make_tenant_project_run(session)
    enqueue_run_job(session=session, tenant_id=tenant_id, run_id=run_id, job_type=RESEARCH_JOB_TYPE)
    session.flush()

    job1 = _claim_next_job(session)
    assert job1 is not None
    session.flush()

    # Second claim attempt sees no queued jobs
    job2 = _claim_next_job(session)
    assert job2 is None


# ── Concurrent claiming ───────────────────────────────────────────────────────


def test_concurrent_claiming_no_double_claim(engine):
    """Under concurrent access, each job is claimed at most once (SKIP LOCKED).

    PostgreSQL's SKIP LOCKED ensures two workers racing on the same queue
    never claim the same job.  N_JOBS * 2 threads compete; each job must
    appear in the claimed list at most once.
    """
    N_JOBS = 20
    SessionLocal = sessionmaker(bind=engine)

    # Seed jobs
    with SessionLocal() as seed_session:
        for _ in range(N_JOBS):
            tenant_id = uuid4()
            project = ProjectRow(tenant_id=tenant_id, name=f"proj-{uuid4()}", created_by="test")
            seed_session.add(project)
            seed_session.flush()
            run = RunRow(
                id=uuid4(),
                tenant_id=tenant_id,
                project_id=project.id,
                status=RunStatusDb.created,
                question="concurrent test",
            )
            seed_session.add(run)
            seed_session.flush()
            enqueue_run_job(
                session=seed_session,
                tenant_id=tenant_id,
                run_id=run.id,
                job_type=RESEARCH_JOB_TYPE,
            )
        seed_session.commit()

    claimed_job_ids: list[UUID] = []
    lock = threading.Lock()
    errors: list[Exception] = []

    def worker():
        with SessionLocal() as s:
            try:
                job = _claim_next_job(s)
                if job is not None:
                    with lock:
                        claimed_job_ids.append(job.id)
                s.commit()
            except Exception as exc:
                with lock:
                    errors.append(exc)

    threads = [threading.Thread(target=worker) for _ in range(N_JOBS * 2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors, f"Worker threads raised errors: {errors}"
    assert len(claimed_job_ids) == len(set(claimed_job_ids)), "Duplicate job claims detected"
    assert len(claimed_job_ids) <= N_JOBS


# ── Orphan recovery ───────────────────────────────────────────────────────────


def test_recover_orphaned_jobs_marks_running_as_failed(session):
    """Running jobs left by a crashed worker are recovered on startup."""
    tenant_id, _, run_id = _make_tenant_project_run(session, run_status=RunStatusDb.running)
    job = JobRow(
        run_id=run_id,
        tenant_id=tenant_id,
        job_type=RESEARCH_JOB_TYPE,
        status=JobStatusDb.running,
        attempts=1,
    )
    session.add(job)
    session.flush()

    recovered = recover_orphaned_jobs(session)
    assert recovered >= 1

    session.refresh(job)
    assert job.status == JobStatusDb.failed
    assert ORPHANED_JOB_RECOVERY_ERROR in (job.last_error or "")


def test_recover_orphaned_jobs_many_stale(session):
    """N stale running jobs are all recovered in one pass."""
    N = 10
    for _ in range(N):
        tenant_id, _, run_id = _make_tenant_project_run(session, run_status=RunStatusDb.running)
        job = JobRow(
            run_id=run_id,
            tenant_id=tenant_id,
            job_type=RESEARCH_JOB_TYPE,
            status=JobStatusDb.running,
            attempts=1,
        )
        session.add(job)
    session.flush()

    recovered = recover_orphaned_jobs(session)
    assert recovered == N

    running_remaining = session.execute(
        select(JobRow).where(JobRow.status == JobStatusDb.running)
    ).scalars().all()
    assert len(running_remaining) == 0


def test_recover_orphaned_jobs_leaves_queued_intact(session):
    """Queued jobs are untouched during orphan recovery."""
    tenant_id, _, run_id = _make_tenant_project_run(session)
    enqueue_run_job(session=session, tenant_id=tenant_id, run_id=run_id, job_type=RESEARCH_JOB_TYPE)
    session.flush()

    recovered = recover_orphaned_jobs(session)
    assert recovered == 0

    job = session.execute(select(JobRow)).scalars().first()
    assert job is not None
    assert job.status == JobStatusDb.queued


def test_recover_also_fixes_orphaned_run_without_job(session):
    """A run stuck in 'running' with no active job is also recovered."""
    # Create a run in running state with no corresponding job
    tenant_id = uuid4()
    project = ProjectRow(tenant_id=tenant_id, name=f"proj-{uuid4()}", created_by="test")
    session.add(project)
    session.flush()
    run = RunRow(
        id=uuid4(),
        tenant_id=tenant_id,
        project_id=project.id,
        status=RunStatusDb.running,
        question="orphaned run",
    )
    session.add(run)
    session.flush()

    recovered = recover_orphaned_jobs(session)
    assert recovered >= 1
    # The identity map returns the same Python object, so the status is already
    # updated in-memory.  Flush so that a subsequent refresh reads the persisted
    # value rather than the pre-flush DB state.
    session.flush()
    assert run.status == RunStatusDb.failed


# ── Job completion and failure ────────────────────────────────────────────────


def test_mark_job_done(session):
    tenant_id, _, run_id = _make_tenant_project_run(session)
    job = JobRow(
        run_id=run_id,
        tenant_id=tenant_id,
        job_type=RESEARCH_JOB_TYPE,
        status=JobStatusDb.running,
        attempts=1,
    )
    session.add(job)
    session.flush()

    _mark_job_done(session, job.id)
    session.flush()

    refreshed = session.get(JobRow, job.id)
    assert refreshed.status == JobStatusDb.succeeded


def test_mark_job_failed_stores_error(session):
    tenant_id, _, run_id = _make_tenant_project_run(session)
    job = JobRow(
        run_id=run_id,
        tenant_id=tenant_id,
        job_type=RESEARCH_JOB_TYPE,
        status=JobStatusDb.running,
        attempts=1,
    )
    session.add(job)
    session.flush()

    _mark_job_failed(session, job.id, "something exploded")
    session.flush()

    # _mark_job_failed uses a bulk UPDATE which bypasses the ORM identity map;
    # expire the cached instance so session.get() reloads from the database.
    session.expire(job)
    refreshed = session.get(JobRow, job.id)
    assert refreshed.status == JobStatusDb.failed
    assert "something exploded" in refreshed.last_error


def test_mark_run_failed_updates_run(session):
    tenant_id, _, run_id = _make_tenant_project_run(session, run_status=RunStatusDb.running)
    _mark_run_failed(session, run_id=run_id, tenant_id=tenant_id, error="worker crash")
    session.flush()

    run = session.execute(
        select(RunRow).where(RunRow.id == run_id)
    ).scalars().first()
    assert run.status == RunStatusDb.failed
    assert run.failure_reason == "worker crash"
    assert run.error_code == "worker_error"


# ── Enqueue deduplication ─────────────────────────────────────────────────────


def test_enqueue_run_job_idempotent(session):
    """Calling enqueue twice for the same run returns the existing job."""
    tenant_id, _, run_id = _make_tenant_project_run(session)
    id1 = enqueue_run_job(
        session=session, tenant_id=tenant_id, run_id=run_id, job_type=RESEARCH_JOB_TYPE
    )
    session.flush()
    id2 = enqueue_run_job(
        session=session, tenant_id=tenant_id, run_id=run_id, job_type=RESEARCH_JOB_TYPE
    )

    assert id1 == id2
    jobs = session.execute(
        select(JobRow).where(JobRow.run_id == run_id)
    ).scalars().all()
    assert len(jobs) == 1


def test_enqueue_transitions_run_from_created_to_queued(session):
    tenant_id, _, run_id = _make_tenant_project_run(session, run_status=RunStatusDb.created)
    enqueue_run_job(session=session, tenant_id=tenant_id, run_id=run_id, job_type=RESEARCH_JOB_TYPE)
    session.flush()

    run = session.execute(select(RunRow).where(RunRow.id == run_id)).scalars().first()
    assert run.status == RunStatusDb.queued


def test_enqueue_raises_for_nonexistent_run(session):
    tenant_id = uuid4()
    with pytest.raises(ValueError, match="run not found"):
        enqueue_run_job(
            session=session,
            tenant_id=tenant_id,
            run_id=uuid4(),
            job_type=RESEARCH_JOB_TYPE,
        )


# ── run_once throughput ───────────────────────────────────────────────────────


def test_run_once_processes_job_and_marks_succeeded(engine):
    """run_once claims a job, calls the processor, marks it succeeded."""
    SessionLocal = sessionmaker(bind=engine)

    with SessionLocal() as seed:
        tenant_id, _, run_id = _make_tenant_project_run(seed, run_status=RunStatusDb.created)
        enqueue_run_job(
            session=seed, tenant_id=tenant_id, run_id=run_id, job_type=RESEARCH_JOB_TYPE
        )
        seed.commit()

    calls: list[tuple[Any, ...]] = []

    def fake_process(*, session, run_id, tenant_id):
        calls.append((run_id, tenant_id))

    with patch("services.workers.main.process_research_run", fake_process), \
         patch("services.workers.main.RESEARCH_JOB_TYPE", RESEARCH_JOB_TYPE), \
         patch("embeddings.release_gpu_memory"):
        ran = run_once(SessionLocal=SessionLocal)

    assert ran is True
    assert len(calls) == 1

    with SessionLocal() as verify:
        job = verify.execute(select(JobRow)).scalars().first()
        assert job.status == JobStatusDb.succeeded


def test_run_once_returns_false_on_empty_queue(engine):
    SessionLocal = sessionmaker(bind=engine)
    ran = run_once(SessionLocal=SessionLocal)
    assert ran is False


def test_run_once_marks_job_failed_on_exception(engine):
    """When the processor raises, job and run are both marked failed."""
    SessionLocal = sessionmaker(bind=engine)

    with SessionLocal() as seed:
        tenant_id, _, run_id = _make_tenant_project_run(seed, run_status=RunStatusDb.created)
        enqueue_run_job(
            session=seed, tenant_id=tenant_id, run_id=run_id, job_type=RESEARCH_JOB_TYPE
        )
        seed.commit()

    def boom(**_kwargs):
        raise RuntimeError("intentional test failure")

    with patch("services.workers.main.process_research_run", boom), \
         patch("services.workers.main.RESEARCH_JOB_TYPE", RESEARCH_JOB_TYPE), \
         patch("embeddings.release_gpu_memory"):
        ran = run_once(SessionLocal=SessionLocal)

    assert ran is True

    with SessionLocal() as verify:
        job = verify.execute(select(JobRow)).scalars().first()
        assert job.status == JobStatusDb.failed
        assert "intentional test failure" in (job.last_error or "")

        run = verify.execute(select(RunRow)).scalars().first()
        assert run.status == RunStatusDb.failed


def test_run_once_processes_awaitable_result(engine):
    """run_once also handles processors that return a coroutine."""
    SessionLocal = sessionmaker(bind=engine)

    with SessionLocal() as seed:
        tenant_id, _, run_id = _make_tenant_project_run(seed, run_status=RunStatusDb.created)
        enqueue_run_job(
            session=seed, tenant_id=tenant_id, run_id=run_id, job_type=RESEARCH_JOB_TYPE
        )
        seed.commit()

    calls: list[tuple[Any, ...]] = []

    async def fake_async_process(*, session, run_id, tenant_id):
        calls.append((run_id, tenant_id, session is not None))

    def fake_process(**kwargs):
        return fake_async_process(**kwargs)

    with patch("services.workers.main.process_research_run", fake_process), \
         patch("services.workers.main.RESEARCH_JOB_TYPE", RESEARCH_JOB_TYPE), \
         patch("embeddings.release_gpu_memory"):
        ran = run_once(SessionLocal=SessionLocal)

    assert ran is True
    assert calls == [(run_id, tenant_id, True)]


def test_run_once_marks_unknown_job_type_as_failed(engine):
    """Unexpected job types should fail the claimed job and run."""
    SessionLocal = sessionmaker(bind=engine)

    with SessionLocal() as seed:
        tenant_id, _, run_id = _make_tenant_project_run(seed, run_status=RunStatusDb.created)
        enqueue_run_job(
            session=seed, tenant_id=tenant_id, run_id=run_id, job_type="unexpected.job"
        )
        seed.commit()

    with patch("services.workers.main.RESEARCH_JOB_TYPE", RESEARCH_JOB_TYPE), \
         patch("embeddings.release_gpu_memory"):
        ran = run_once(SessionLocal=SessionLocal)

    assert ran is True

    with SessionLocal() as verify:
        job = verify.execute(select(JobRow)).scalars().first()
        run = verify.execute(select(RunRow)).scalars().first()
        assert job.status == JobStatusDb.failed
        assert "Unknown job_type" in (job.last_error or "")
        assert run.status == RunStatusDb.failed
        assert "Unknown job_type" in (run.failure_reason or "")


def test_run_once_throughput_n_sequential_jobs(engine):
    """N jobs inserted sequentially are all processed successfully."""
    N = 15
    SessionLocal = sessionmaker(bind=engine)

    with SessionLocal() as seed:
        for _ in range(N):
            tenant_id, _, run_id = _make_tenant_project_run(seed, run_status=RunStatusDb.created)
            enqueue_run_job(
                session=seed, tenant_id=tenant_id, run_id=run_id, job_type=RESEARCH_JOB_TYPE
            )
        seed.commit()

    processed = 0

    def noop_process(**_kwargs):
        nonlocal processed
        processed += 1

    with patch("services.workers.main.process_research_run", noop_process), \
         patch("services.workers.main.RESEARCH_JOB_TYPE", RESEARCH_JOB_TYPE), \
         patch("embeddings.release_gpu_memory"):
        while run_once(SessionLocal=SessionLocal):
            pass

    assert processed == N

    with SessionLocal() as verify:
        succeeded = verify.execute(
            select(JobRow).where(JobRow.status == JobStatusDb.succeeded)
        ).scalars().all()
        assert len(succeeded) == N
