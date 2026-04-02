from __future__ import annotations

import asyncio
import os
import sys
import types
from threading import Event
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

sys.modules.setdefault(
    "bcrypt",
    types.SimpleNamespace(
        gensalt=lambda rounds=12: b"salt",
        hashpw=lambda password, salt: b"hash",
        checkpw=lambda password, hashed: True,
    ),
)

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "..", "backend"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "..", "backend", "data"))

import db.models  # noqa: F401
from db.models.jobs import JobRow, JobStatusDb
from db.models.projects import ProjectRow
from db.models.run_events import RunEventLevelDb
from db.models.runs import RunRow, RunStatusDb
from services.workers import main as worker_main

_TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql+psycopg://postgres:postgres@localhost:5432/researchops_test",
)
_TEST_ASYNC_DATABASE_URL = _TEST_DATABASE_URL.replace(
    "postgresql+psycopg://", "postgresql+asyncpg://"
)


@pytest.mark.asyncio
async def test_recover_orphaned_jobs_marks_running_jobs_and_runs_failed():
    from db.init_db import init_db as _init_db
    from sqlalchemy.ext.asyncio import async_sessionmaker

    engine = create_async_engine(_TEST_ASYNC_DATABASE_URL, future=True)
    await _init_db(engine)
    AsyncSessionLocal = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)

    async with AsyncSessionLocal() as session:
        tenant_id = uuid4()
        project = ProjectRow(tenant_id=tenant_id, name=f"proj-{uuid4()}", created_by="tester")
        session.add(project)
        await session.flush()

        run = RunRow(
            tenant_id=tenant_id,
            project_id=project.id,
            status=RunStatusDb.running,
            current_stage="retrieve",
            question="stuck run",
        )
        session.add(run)
        await session.flush()

        job = JobRow(
            tenant_id=tenant_id,
            run_id=run.id,
            job_type="research.run",
            status=JobStatusDb.running,
            attempts=1,
        )
        session.add(job)
        await session.flush()
        await session.commit()

    recovered = await worker_main.recover_orphaned_jobs(AsyncSessionLocal)

    async with AsyncSessionLocal() as session:
        refreshed_run = (await session.execute(select(RunRow).where(RunRow.id == run.id))).scalar_one()
        refreshed_job = (await session.execute(select(JobRow).where(JobRow.id == job.id))).scalar_one()

    assert recovered >= 1
    assert refreshed_job.status == JobStatusDb.failed
    assert refreshed_job.last_error is not None
    assert "orphaned" in refreshed_job.last_error.lower()
    assert refreshed_run.status == RunStatusDb.failed
    assert refreshed_run.error_code == "stale_running_recovered"
    assert refreshed_run.failure_reason is not None
    assert "orphaned" in refreshed_run.failure_reason.lower()

    await engine.dispose()


@pytest.mark.asyncio
async def test_async_claim_returns_none_and_recover_recovers_stale_run_without_job():
    from db.init_db import init_db as _init_db

    engine = create_async_engine(_TEST_ASYNC_DATABASE_URL, future=True)
    await _init_db(engine)
    SessionLocal = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)

    async with SessionLocal() as session:
        assert await worker_main._claim_next_job(session) is None

        tenant_id = uuid4()
        project = ProjectRow(tenant_id=tenant_id, name=f"proj-{uuid4()}", created_by="tester")
        session.add(project)
        await session.flush()

        run = RunRow(
            tenant_id=tenant_id,
            project_id=project.id,
            status=RunStatusDb.running,
            current_stage="retrieve",
            question="stale run without job",
        )
        session.add(run)
        await session.commit()

    recovered = await worker_main.recover_orphaned_jobs(SessionLocal)

    async with SessionLocal() as session:
        refreshed_run = (await session.execute(select(RunRow).where(RunRow.id == run.id))).scalar_one()
        assert recovered == 1
        assert refreshed_run.status == RunStatusDb.failed
        assert refreshed_run.error_code == "stale_running_recovered"

    await engine.dispose()


@pytest.mark.asyncio
async def test_stage_start_event_updates_run_current_stage():
    from db.init_db import init_db as _init_db
    from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
    from sqlalchemy.orm import sessionmaker
    from db.repositories.project_runs import append_run_event

    engine = create_async_engine(_TEST_ASYNC_DATABASE_URL, future=True)
    await _init_db(engine)
    AsyncSessionLocal = sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)

    async with AsyncSessionLocal() as session:
        tenant_id = uuid4()
        project = ProjectRow(tenant_id=tenant_id, name=f"proj-{uuid4()}", created_by="tester")
        session.add(project)
        await session.flush()

        run = RunRow(
            tenant_id=tenant_id,
            project_id=project.id,
            status=RunStatusDb.running,
            current_stage="retrieve",
            question="advance stages",
        )
        session.add(run)
        await session.flush()

        await append_run_event(
            session=session,
            tenant_id=tenant_id,
            run_id=run.id,
            level=RunEventLevelDb.info,
            event_type="stage_start",
            stage="outline",
            message="Starting stage: outline",
            payload_json={"iteration": 0},
            allow_finished=False,
        )
        await session.flush()

        refreshed_run = (await session.execute(select(RunRow).where(RunRow.id == run.id))).scalar_one()
        assert refreshed_run.current_stage == "outline"

    await engine.dispose()


@pytest.mark.asyncio
async def test_async_worker_helpers_update_job_and_run_state():
    from db.init_db import init_db as _init_db

    engine = create_async_engine(_TEST_ASYNC_DATABASE_URL, future=True)
    await _init_db(engine)
    SessionLocal = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)

    async with SessionLocal() as session:
        tenant_id = uuid4()
        project = ProjectRow(tenant_id=tenant_id, name=f"proj-{uuid4()}", created_by="tester")
        session.add(project)
        await session.flush()

        run = RunRow(
            tenant_id=tenant_id,
            project_id=project.id,
            status=RunStatusDb.running,
            current_stage="retrieve",
            question="async worker helper coverage",
        )
        session.add(run)
        await session.flush()

        job = JobRow(
            tenant_id=tenant_id,
            run_id=run.id,
            job_type="research.run",
            status=JobStatusDb.queued,
            attempts=0,
        )
        session.add(job)
        await session.flush()

        claimed = await worker_main._claim_next_job(session)
        assert claimed is not None
        assert claimed.id == job.id
        assert claimed.status == JobStatusDb.running
        assert claimed.attempts == 1

        await worker_main._mark_job_done(session, job.id)
        await session.flush()
        await session.refresh(job)
        assert job.status == JobStatusDb.succeeded

        await worker_main._mark_job_failed(session, job.id, "boom")
        await worker_main._mark_run_failed(
            session,
            run_id=run.id,
            tenant_id=tenant_id,
            error="boom",
        )
        await session.flush()
        await session.refresh(job)
        await session.refresh(run)
        assert job.status == JobStatusDb.failed
        assert job.last_error == "boom"
        assert run.status == RunStatusDb.failed
        assert run.error_code == "worker_error"

    await engine.dispose()


@pytest.mark.asyncio
async def test_async_worker_finish_and_fail_helpers():
    from db.init_db import init_db as _init_db

    engine = create_async_engine(_TEST_ASYNC_DATABASE_URL, future=True)
    await _init_db(engine)
    SessionLocal = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)

    async with SessionLocal() as session:
        tenant_id = uuid4()
        project = ProjectRow(tenant_id=tenant_id, name=f"proj-{uuid4()}", created_by="tester")
        session.add(project)
        await session.flush()

        run = RunRow(
            tenant_id=tenant_id,
            project_id=project.id,
            status=RunStatusDb.running,
            question="finish/fail helpers",
        )
        session.add(run)
        await session.flush()

        job = JobRow(
            tenant_id=tenant_id,
            run_id=run.id,
            job_type="research.run",
            status=JobStatusDb.running,
            attempts=1,
        )
        session.add(job)
        await session.commit()

    await worker_main._finish(SessionLocal, job.id)
    async with SessionLocal() as session:
        refreshed_job = (await session.execute(select(JobRow).where(JobRow.id == job.id))).scalar_one()
        assert refreshed_job.status == JobStatusDb.succeeded

        refreshed_job.status = JobStatusDb.running
        refreshed_job.last_error = None
        refreshed_run = (await session.execute(select(RunRow).where(RunRow.id == run.id))).scalar_one()
        refreshed_run.status = RunStatusDb.running
        refreshed_run.failure_reason = None
        refreshed_run.error_code = None
        await session.commit()

    await worker_main._fail(SessionLocal, job.id, run.id, tenant_id, "async failure")
    async with SessionLocal() as session:
        failed_job = (await session.execute(select(JobRow).where(JobRow.id == job.id))).scalar_one()
        failed_run = (await session.execute(select(RunRow).where(RunRow.id == run.id))).scalar_one()
        assert failed_job.status == JobStatusDb.failed
        assert failed_job.last_error == "async failure"
        assert failed_run.status == RunStatusDb.failed
        assert failed_run.failure_reason == "async failure"

    await engine.dispose()


def test_async_run_once_handles_empty_queue_success_and_failure(monkeypatch):
    from contextlib import asynccontextmanager

    calls: list[tuple[str, object]] = []
    fake_session = object()
    fake_session_local = object()

    @asynccontextmanager
    async def fake_session_scope(_session_local):
        yield fake_session

    monkeypatch.setattr(worker_main, "session_scope", fake_session_scope)
    monkeypatch.setattr(worker_main, "RESEARCH_JOB_TYPE", "research.run")
    monkeypatch.setattr("embeddings.release_gpu_memory", lambda: calls.append(("release", None)))

    async def claim_none(session):
        calls.append(("claim_none", session))
        return None

    monkeypatch.setattr(worker_main, "_claim_next_job", claim_none)
    assert worker_main.run_once(SessionLocal=fake_session_local) is False

    job = SimpleNamespace(
        id="job-1",
        run_id="run-1",
        tenant_id="tenant-1",
        job_type="research.run",
    )

    async def claim_job(session):
        calls.append(("claim_job", session))
        return job

    async def fake_process(*, session, run_id, tenant_id):
        calls.append(("process", (session, run_id, tenant_id)))

    async def fake_mark_done(session, job_id):
        calls.append(("mark_done", (session, job_id)))

    async def fake_mark_job_failed(session, job_id, err):
        calls.append(("mark_job_failed", (session, job_id, err)))

    async def fake_mark_run_failed(session, *, run_id, tenant_id, error):
        calls.append(("mark_run_failed", (session, run_id, tenant_id, error)))

    monkeypatch.setattr(worker_main, "_claim_next_job", claim_job)
    monkeypatch.setattr(worker_main, "process_research_run", fake_process)
    monkeypatch.setattr(worker_main, "_mark_job_done", fake_mark_done)
    monkeypatch.setattr(worker_main, "_mark_job_failed", fake_mark_job_failed)
    monkeypatch.setattr(worker_main, "_mark_run_failed", fake_mark_run_failed)

    assert worker_main.run_once(SessionLocal=fake_session_local) is True
    assert ("process", (fake_session, "run-1", "tenant-1")) in calls
    assert ("mark_done", (fake_session, "job-1")) in calls

    calls.clear()
    async def fake_process_failure(*, session, run_id, tenant_id):
        raise RuntimeError("runtime failure")

    monkeypatch.setattr(worker_main, "process_research_run", fake_process_failure)
    assert worker_main.run_once(SessionLocal=fake_session_local) is True
    assert any(name == "mark_job_failed" for name, _ in calls)
    assert not any(name == "mark_run_failed" for name, _ in calls)

    calls.clear()
    job.job_type = "unexpected.job"
    assert worker_main.run_once(SessionLocal=fake_session_local) is True
    assert any(name == "mark_job_failed" for name, _ in calls)
    assert any(name == "mark_run_failed" for name, _ in calls)


def test_run_once_sync_research_dispatch_is_disabled(monkeypatch):
    calls: list[tuple[str, object]] = []
    process_called = False

    class _Session:
        def commit(self):
            return None

    class _SessionLocal:
        def __call__(self):
            return self

        def __enter__(self):
            return _Session()

        def __exit__(self, exc_type, exc, tb):
            return False

    session_local = _SessionLocal()
    job = SimpleNamespace(
        id="job-1",
        run_id="run-1",
        tenant_id="tenant-1",
        job_type="research.run",
    )

    monkeypatch.setattr(worker_main, "RESEARCH_JOB_TYPE", "research.run")
    monkeypatch.setattr("embeddings.release_gpu_memory", lambda: calls.append(("release", None)))
    monkeypatch.setattr(worker_main, "_claim_next_job_sync", lambda _session: job)
    monkeypatch.setattr(worker_main, "_mark_job_done_sync", lambda _session, _job_id: calls.append(("mark_done", _job_id)))
    monkeypatch.setattr(
        worker_main,
        "_mark_job_failed_sync",
        lambda _session, _job_id, _err: calls.append(("mark_job_failed", (_job_id, _err))),
    )
    monkeypatch.setattr(
        worker_main,
        "_mark_run_failed_sync",
        lambda _session, **_kwargs: calls.append(("mark_run_failed", _kwargs)),
    )

    async def fake_process(**_kwargs):
        nonlocal process_called
        process_called = True

    monkeypatch.setattr(worker_main, "process_research_run", fake_process)

    assert worker_main.run_once_sync(SessionLocal=session_local) is True
    assert process_called is False
    assert any(name == "mark_job_failed" for name, _ in calls)
    assert not any(name == "mark_run_failed" for name, _ in calls)
    assert not any(name == "mark_done" for name, _ in calls)


def test_run_forever_and_main_delegate_runtime_setup(monkeypatch):
    stop_event = Event()
    calls: list[str] = []
    class FakeEngine:
        async def dispose(self):
            calls.append("dispose")

    fake_engine = FakeEngine()
    fake_session_local = object()
    settings = SimpleNamespace(worker_poll_seconds=0.25)
    original_run_forever = worker_main.run_forever

    monkeypatch.setattr(worker_main, "get_settings", lambda: settings)
    monkeypatch.setattr(worker_main, "create_db_engine", lambda _settings: fake_engine)
    async def fake_init_db(engine):
        calls.append(f"init:{engine is fake_engine}")

    monkeypatch.setattr(worker_main, "init_db", fake_init_db)
    monkeypatch.setattr(
        worker_main,
        "create_sessionmaker",
        lambda engine: calls.append(f"sessionmaker:{engine is fake_engine}") or fake_session_local,
    )
    async def fake_recover(session_local):
        calls.append(f"recover:{session_local is fake_session_local}")

    monkeypatch.setattr(worker_main, "recover_orphaned_jobs", fake_recover)

    async def fake_run_once_async(*, SessionLocal):
        calls.append(f"run_once:{SessionLocal is fake_session_local}")
        stop_event.set()
        return False

    monkeypatch.setattr(worker_main, "run_once_async", fake_run_once_async)
    async def fake_sleep(seconds):
        calls.append(f"sleep:{seconds}")

    monkeypatch.setattr(worker_main.asyncio, "sleep", fake_sleep)
    monkeypatch.setattr(worker_main, "resolve_env_files", lambda: ["a.env", "b.env"])
    monkeypatch.setattr(worker_main, "load_dotenv", lambda path, override=False: calls.append(f"dotenv:{path}:{override}"))
    monkeypatch.setattr(worker_main, "setup_logging", lambda service: calls.append(f"logging:{service}"))
    original_run_forever(poll_seconds=0.25, stop_event=stop_event)
    monkeypatch.setattr(worker_main, "run_forever", lambda poll_seconds: calls.append(f"main_run:{poll_seconds}"))
    worker_main.main()

    assert "init:True" in calls
    assert "sessionmaker:True" in calls
    assert "recover:True" in calls
    assert "run_once:True" in calls
    assert "sleep:0.25" in calls
    assert "dispose" in calls
    assert "dotenv:a.env:False" in calls
    assert "dotenv:b.env:False" in calls
    assert f"logging:{worker_main.SERVICE_WORKER}" in calls
    assert "main_run:0.25" in calls
