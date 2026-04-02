from __future__ import annotations

import json
import os
from uuid import uuid4

import pytest
import pytest_asyncio
from db.init_db import init_db
from db.models.projects import ProjectRow
from db.models.run_usage_metrics import RunUsageMetricRow
from db.models.runs import RunRow, RunStatusDb
from services.orchestrator.research import process_research_run
from services.orchestrator.runtime import ResearchRuntime, run_research_orchestrator
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

    session.add_all(
        [
            RunUsageMetricRow(
                tenant_id=tenant_id,
                run_id=run.id,
                metric_name="user_query",
                metric_text="seeded user query",
            ),
            RunUsageMetricRow(
                tenant_id=tenant_id,
                run_id=run.id,
                metric_name="research_goal",
                metric_text="seeded goal",
            ),
            RunUsageMetricRow(
                tenant_id=tenant_id,
                run_id=run.id,
                metric_name="llm_provider",
                metric_text="openai",
            ),
            RunUsageMetricRow(
                tenant_id=tenant_id,
                run_id=run.id,
                metric_name="llm_model",
                metric_text="gpt-5",
            ),
            RunUsageMetricRow(
                tenant_id=tenant_id,
                run_id=run.id,
                metric_name="stage_models",
                metric_text=json.dumps({"retrieve": "gpt-5-mini", "synthesize": None}),
            ),
            RunUsageMetricRow(
                tenant_id=tenant_id,
                run_id=run.id,
                metric_name="max_iterations",
                metric_text="7",
            ),
        ]
    )
    await session.flush()
    return run


@pytest.mark.asyncio
async def test_research_runtime_create_sets_runtime_fields(
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
async def test_research_run_inputs_defaults() -> None:
    inputs = ResearchRunInputs(user_query="defaults query")
    assert inputs.user_query == "defaults query"
    assert inputs.research_goal is None
    assert inputs.llm_provider is None
    assert inputs.llm_model is None
    assert inputs.stage_models == {}
    assert inputs.max_iterations == 5


@pytest.mark.asyncio
async def test_run_research_orchestrator_transitions_to_running_before_graph_execution(
    monkeypatch: pytest.MonkeyPatch, session: AsyncSession, seeded_run: RunRow
) -> None:
    call_order: list[str] = []
    sentinel = object()

    async def fake_run_orchestrator(**kwargs):
        call_order.append("graph")
        run = await kwargs["session"].get(RunRow, kwargs["run_id"])
        assert run is not None
        assert run.status == RunStatusDb.running
        assert run.current_stage == "retrieve"
        assert kwargs["transition_to_running"] is False
        return sentinel

    monkeypatch.setattr("services.orchestrator.runtime.run_orchestrator", fake_run_orchestrator)
    result = await run_research_orchestrator(
        session=session,
        tenant_id=seeded_run.tenant_id,
        run_id=seeded_run.id,
        inputs=ResearchRunInputs(user_query="runtime handoff query"),
    )

    assert result is sentinel
    assert call_order == ["graph"]


@pytest.mark.asyncio
async def test_process_research_run_delegates_to_async_runtime_with_constructed_inputs(
    monkeypatch: pytest.MonkeyPatch, session: AsyncSession, seeded_run: RunRow
) -> None:
    called: dict[str, object] = {}

    async def fake_run_research_orchestrator(**kwargs):
        called.update(kwargs)

    monkeypatch.setattr(
        "services.orchestrator.research.run_research_orchestrator",
        fake_run_research_orchestrator,
    )
    await process_research_run(session=session, run_id=seeded_run.id, tenant_id=seeded_run.tenant_id)
    assert called["run_id"] == seeded_run.id
    assert called["tenant_id"] == seeded_run.tenant_id
    assert called["session"] is session
    expected_inputs_type = process_research_run.__globals__["ResearchRunInputs"]
    assert isinstance(called["inputs"], expected_inputs_type)

    forwarded_inputs = called["inputs"]
    assert forwarded_inputs.user_query == "seeded user query"
    assert forwarded_inputs.research_goal == "seeded goal"
    assert forwarded_inputs.llm_provider == "openai"
    assert forwarded_inputs.llm_model == "gpt-5"
    assert forwarded_inputs.stage_models == {"retrieve": "gpt-5-mini", "synthesize": None}
    assert forwarded_inputs.max_iterations == 7
