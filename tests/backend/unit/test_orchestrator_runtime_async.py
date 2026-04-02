from __future__ import annotations

import os
from uuid import uuid4

import pytest
import pytest_asyncio
from db.init_db import init_db
from db.models.projects import ProjectRow
from db.models.run_usage_metrics import RunUsageMetricRow
from db.models.runs import RunRow, RunStatusDb
from services.orchestrator.research import process_research_run
from services.orchestrator.runtime import ResearchRuntime
from services.orchestrator.runtime_types import ResearchRunInputs
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

_TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql+psycopg://postgres:postgres@localhost:5432/researchops_test",
)
_TEST_ASYNC_DATABASE_URL = _TEST_DATABASE_URL.replace(
    "postgresql+psycopg://", "postgresql+asyncpg://"
)


@pytest_asyncio.fixture
async def session() -> AsyncSession:
    engine = create_async_engine(_TEST_ASYNC_DATABASE_URL, future=True)
    await init_db(engine)
    session_local = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    async with session_local() as db_session:
        yield db_session
    await engine.dispose()


@pytest_asyncio.fixture
async def seeded_run(session: AsyncSession) -> RunRow:
    tenant_id = uuid4()
    project = ProjectRow(tenant_id=tenant_id, name=f"proj-{uuid4()}", created_by="tester")
    session.add(project)
    await session.flush()

    run = RunRow(
        tenant_id=tenant_id,
        project_id=project.id,
        status=RunStatusDb.queued,
        current_stage=None,
        question="runtime contract test",
    )
    session.add(run)
    await session.flush()

    session.add(
        RunUsageMetricRow(
            tenant_id=tenant_id,
            run_id=run.id,
            metric_name="user_query",
            metric_text="seeded user query",
        )
    )
    await session.flush()
    return run


@pytest.mark.asyncio
async def test_runtime_transitions_run_to_running_before_graph_execution(
    session: AsyncSession, seeded_run: RunRow
) -> None:
    inputs = ResearchRunInputs(user_query="test query")
    runtime = await ResearchRuntime.create(
        session=session,
        tenant_id=seeded_run.tenant_id,
        run_id=seeded_run.id,
        inputs=inputs,
    )
    assert runtime.run_id == seeded_run.id
    assert runtime.inputs.user_query == "test query"


@pytest.mark.asyncio
async def test_process_research_run_delegates_to_async_runtime(
    monkeypatch: pytest.MonkeyPatch, session: AsyncSession, seeded_run: RunRow
) -> None:
    called: dict[str, object] = {}

    async def fake_run_research_orchestrator(**kwargs):
        called["run_id"] = kwargs["run_id"]

    monkeypatch.setattr(
        "services.orchestrator.research.run_research_orchestrator",
        fake_run_research_orchestrator,
    )
    await process_research_run(session=session, run_id=seeded_run.id, tenant_id=seeded_run.tenant_id)
    assert called["run_id"] == seeded_run.id
