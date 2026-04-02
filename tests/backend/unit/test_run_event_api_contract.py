from __future__ import annotations

import os
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
import db.models  # noqa: F401
from db.models.base import Base
from db.models.projects import ProjectRow
from db.models.run_events import RunEventAudienceDb, RunEventLevelDb
from db.models.runs import RunRow, RunStatusDb
from services.orchestrator.checkpoint_store import write_checkpoint
from services.orchestrator.event_store import append_runtime_event
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
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    session_local = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    async with session_local() as db_session:
        yield db_session
    await engine.dispose()


@pytest_asyncio.fixture
async def seeded_run(session: AsyncSession) -> tuple[UUID, UUID]:
    tenant_id = uuid4()
    project = ProjectRow(tenant_id=tenant_id, name=f"proj-{uuid4()}", created_by="tester")
    session.add(project)
    await session.flush()

    run = RunRow(
        tenant_id=tenant_id,
        project_id=project.id,
        status=RunStatusDb.running,
        current_stage="retrieve",
        question="contract test",
    )
    session.add(run)
    await session.flush()
    return tenant_id, run.id


@pytest.mark.asyncio
async def test_append_runtime_event_persists_audience_and_event_type(
    session: AsyncSession, seeded_run: tuple[UUID, UUID]
) -> None:
    tenant_id, run_id = seeded_run
    row = await append_runtime_event(
        session=session,
        tenant_id=tenant_id,
        run_id=run_id,
        audience=RunEventAudienceDb.progress,
        event_type="retrieve.connector_query_started",
        level=RunEventLevelDb.info,
        stage="retrieve",
        message="Searching OpenAlex for query 1/3",
        payload={"connector": "openalex", "completed_count": 0, "total_count": 3},
    )
    assert row.audience == RunEventAudienceDb.progress
    assert row.event_type == "retrieve.connector_query_started"


@pytest.mark.asyncio
async def test_write_checkpoint_persists_resume_metadata(
    session: AsyncSession, seeded_run: tuple[UUID, UUID]
) -> None:
    tenant_id, run_id = seeded_run
    row = await write_checkpoint(
        session=session,
        tenant_id=tenant_id,
        run_id=run_id,
        node_name="retriever",
        iteration_count=1,
        state_payload={"user_query": "test", "generated_queries": ["a"]},
        summary_payload={"query_count": 1},
    )
    assert row.node_name == "retriever"
    assert row.iteration_count == 1
