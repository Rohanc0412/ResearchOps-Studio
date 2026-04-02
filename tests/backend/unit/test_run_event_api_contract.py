from __future__ import annotations

import os
import json
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from db.init_db import init_db
from db.models.run_checkpoints import RunCheckpointRow
from db.models.run_events import RunEventRow
from db.models.projects import ProjectRow
from db.models.run_events import RunEventAudienceDb, RunEventLevelDb
from db.models.runs import RunRow, RunStatusDb
from core.runs.lifecycle import transition_run_status_async
from routes.runs import _event_to_sse
from schemas.truth import RunEventOut
from services.orchestrator.checkpoint_store import write_checkpoint
from services.orchestrator.event_store import append_runtime_event
from sqlalchemy import select
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
    await session.flush()
    session.expunge_all()

    stored_row = (
        await session.execute(
            select(RunEventRow).where(
                RunEventRow.tenant_id == tenant_id,
                RunEventRow.run_id == run_id,
                RunEventRow.id == row.id,
            )
        )
    ).scalar_one()
    assert stored_row.audience == RunEventAudienceDb.progress
    assert stored_row.event_type == "retrieve.connector_query_started"


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
    await session.flush()
    session.expunge_all()

    stored_row = (
        await session.execute(
            select(RunCheckpointRow).where(
                RunCheckpointRow.tenant_id == tenant_id,
                RunCheckpointRow.run_id == run_id,
                RunCheckpointRow.id == row.id,
            )
        )
    ).scalar_one()
    assert stored_row.node_name == "retriever"
    assert stored_row.iteration_count == 1
    assert stored_row.checkpoint_version == 1
    assert stored_row.summary_json == {"query_count": 1}


def test_run_event_out_includes_audience_and_event_type() -> None:
    tenant_id = uuid4()
    run_id = uuid4()
    event_id = uuid4()
    row = SimpleNamespace(
        id=event_id,
        tenant_id=tenant_id,
        run_id=run_id,
        ts=datetime.now(UTC),
        stage="retrieve",
        level=RunEventLevelDb.info,
        audience=RunEventAudienceDb.progress,
        event_type="retrieve.plan_created",
        message="Created query plan",
        payload_json={"query_count": 3},
    )

    event = RunEventOut.model_validate(row)
    assert event.audience == "progress"
    assert event.event_type == "retrieve.plan_created"


def test_sse_payload_includes_audience_and_event_type() -> None:
    event = SimpleNamespace(
        event_number=42,
        ts=datetime(2026, 4, 2, 12, 30, tzinfo=UTC),
        level=RunEventLevelDb.info,
        stage="draft",
        audience=RunEventAudienceDb.progress,
        event_type="draft.section_started",
        message="draft.section_started",
        payload_json={"section_id": "introduction"},
    )

    sse_payload = _event_to_sse(event)
    lines = [line for line in sse_payload.splitlines() if line]
    assert lines[0] == "id: 42"
    assert lines[1] == "event: run_event"
    data = json.loads(lines[2].removeprefix("data: "))
    assert data["audience"] == "progress"
    assert data["event_type"] == "draft.section_started"


@pytest.mark.asyncio
async def test_lifecycle_terminal_transition_emits_state_audience_event(tmp_path) -> None:
    db_path = tmp_path / "lifecycle_event_contract.sqlite3"
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}", future=True)
    await init_db(engine)

    session_local = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    async with session_local() as session:
        tenant_id = uuid4()
        project = ProjectRow(tenant_id=tenant_id, name=f"proj-{uuid4()}", created_by="tester")
        session.add(project)
        await session.flush()

        run = RunRow(
            tenant_id=tenant_id,
            project_id=project.id,
            status=RunStatusDb.running,
            current_stage="evaluate",
            question="lifecycle contract test",
        )
        session.add(run)
        await session.flush()

        await transition_run_status_async(
            session=session,
            tenant_id=tenant_id,
            run_id=run.id,
            to_status=RunStatusDb.failed,
            current_stage="evaluate",
            finished_at=datetime.now(UTC),
        )
        await session.commit()

        rows = list(
            (
                await session.execute(
                    select(RunEventRow)
                    .where(RunEventRow.tenant_id == tenant_id, RunEventRow.run_id == run.id)
                    .order_by(RunEventRow.event_number.asc())
                )
            ).scalars().all()
        )

    await engine.dispose()

    assert len(rows) >= 1
    terminal_event = rows[-1]
    assert terminal_event.event_type == "state"
    assert terminal_event.audience == RunEventAudienceDb.state
    assert terminal_event.payload_json.get("to_status") == "failed"
