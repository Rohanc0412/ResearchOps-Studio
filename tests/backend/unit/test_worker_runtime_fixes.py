from __future__ import annotations

import os
import sys
import types
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

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

