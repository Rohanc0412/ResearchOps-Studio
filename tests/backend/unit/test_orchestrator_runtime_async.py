from __future__ import annotations

import json
import os
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
import pytest_asyncio
from core.pipeline_events.events import emit_node_progress, emit_run_event, instrument_node
from db.init_db import init_db
from core.orchestrator.state import OrchestratorState
from db.models.run_events import RunEventRow
from db.models.projects import ProjectRow
from db.models.run_usage_metrics import RunUsageMetricRow
from db.models.runs import RunRow, RunStatusDb
from services.orchestrator.cancellation import RunCancelledError
from services.orchestrator.research import process_research_run
from services.orchestrator.runner import resume_orchestrator, run_orchestrator
from services.orchestrator.runtime import (
    ResearchRuntime,
    RuntimeCheckpointStore,
    RuntimeEventStore,
    run_research_orchestrator,
)
from services.orchestrator.runtime_types import ResearchRunInputs
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

_TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql+psycopg://postgres:postgres@localhost:5432/researchops_test",
)


def _to_async_url(url: str) -> str:
    for prefix in ("postgresql+psycopg2://", "postgresql+psycopg://", "postgresql://"):
        if url.startswith(prefix):
            return "postgresql+asyncpg://" + url[len(prefix) :]
    if url.startswith("sqlite+pysqlite://"):
        return "sqlite+aiosqlite://" + url[len("sqlite+pysqlite://") :]
    if url.startswith("sqlite://"):
        return "sqlite+aiosqlite://" + url[len("sqlite://") :]
    return url


_TEST_ASYNC_DATABASE_URL = _to_async_url(_TEST_DATABASE_URL)


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


@pytest.fixture
def runtime() -> ResearchRuntime:
    session = AsyncMock(spec=AsyncSession)
    return ResearchRuntime(
        session=session,
        tenant_id=uuid4(),
        run_id=uuid4(),
        inputs=ResearchRunInputs(user_query="fixture query"),
        event_store=RuntimeEventStore(session=session),
        checkpoint_store=RuntimeCheckpointStore(session=session),
    )


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
async def test_run_research_orchestrator_transitions_to_running_before_graph_handoff(
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
async def test_runtime_execute_node_checks_cancellation_and_commits_after_node(
    monkeypatch: pytest.MonkeyPatch, runtime: ResearchRuntime
) -> None:
    calls: list[str] = []

    async def fake_assert_not_cancelled(self) -> None:
        calls.append("assert_not_cancelled")

    async def fake_write_after_node(self, *, state, node_name: str) -> None:
        calls.append(f"checkpoint:{node_name}")

    async def fake_flush_pending_events(self) -> None:
        calls.append("flush_pending_events")

    async def fake_commit() -> None:
        calls.append("commit")

    monkeypatch.setattr(type(runtime), "assert_not_cancelled", fake_assert_not_cancelled, raising=False)
    monkeypatch.setattr(type(runtime.checkpoint_store), "write_after_node", fake_write_after_node, raising=False)
    monkeypatch.setattr(type(runtime), "flush_pending_events", fake_flush_pending_events, raising=False)
    monkeypatch.setattr(runtime.session, "commit", fake_commit)

    async def fake_node(state, runtime):
        calls.append("node")
        state.iteration_count = 1
        return state

    next_state = await runtime.execute_node(
        node_name="retriever",
        node_func=fake_node,
        state=runtime.initial_state(),
    )
    assert next_state.iteration_count == 1
    assert calls == [
        "assert_not_cancelled",
        "node",
        "checkpoint:retriever",
        "flush_pending_events",
        "commit",
    ]


@pytest.mark.asyncio
async def test_runtime_execute_node_commits_each_step_on_repeated_execution(
    monkeypatch: pytest.MonkeyPatch, runtime: ResearchRuntime
) -> None:
    calls: list[str] = []

    async def fake_assert_not_cancelled(self) -> None:
        calls.append("assert_not_cancelled")

    async def fake_write_after_node(self, *, state, node_name: str) -> None:
        calls.append(f"checkpoint:{node_name}")

    async def fake_flush_pending_events(self) -> None:
        calls.append("flush_pending_events")

    async def fake_commit() -> None:
        calls.append("commit")

    monkeypatch.setattr(type(runtime), "assert_not_cancelled", fake_assert_not_cancelled, raising=False)
    monkeypatch.setattr(type(runtime.checkpoint_store), "write_after_node", fake_write_after_node, raising=False)
    monkeypatch.setattr(type(runtime), "flush_pending_events", fake_flush_pending_events, raising=False)
    monkeypatch.setattr(runtime.session, "commit", fake_commit)

    async def step_one(state, runtime):
        calls.append("node:retriever")
        state.iteration_count += 1
        return state

    async def step_two(state, runtime):
        calls.append("node:writer")
        state.iteration_count += 1
        return state

    state = runtime.initial_state()
    state = await runtime.execute_node(node_name="retriever", node_func=step_one, state=state)
    state = await runtime.execute_node(node_name="writer", node_func=step_two, state=state)

    assert state.iteration_count == 2
    assert calls == [
        "assert_not_cancelled",
        "node:retriever",
        "checkpoint:retriever",
        "flush_pending_events",
        "commit",
        "assert_not_cancelled",
        "node:writer",
        "checkpoint:writer",
        "flush_pending_events",
        "commit",
    ]


def test_emit_node_progress_requires_runtime_owned_session() -> None:
    with pytest.raises(RuntimeError, match="runtime-owned"):
        emit_node_progress(
            session=SimpleNamespace(),
            tenant_id=uuid4(),
            run_id=uuid4(),
            event_type="progress",
            stage="draft",
            data={"section_index": 1},
        )


@pytest.mark.asyncio
async def test_runtime_flush_pending_events_drains_queue_only_once(
    monkeypatch: pytest.MonkeyPatch, runtime: ResearchRuntime
) -> None:
    appended_event_types: list[str] = []
    flush_calls: list[str] = []

    async def fake_append(self, **kwargs):
        appended_event_types.append(kwargs["event_type"])
        return None

    async def fake_flush() -> None:
        flush_calls.append("flush")

    monkeypatch.setattr(type(runtime.event_store), "append", fake_append, raising=False)
    monkeypatch.setattr(runtime.session, "flush", fake_flush)

    runtime.queue_node_event(
        tenant_id=runtime.tenant_id,
        run_id=runtime.run_id,
        event_type="progress",
        stage="draft",
        data={"section_index": 1},
    )
    runtime.queue_node_event(
        tenant_id=runtime.tenant_id,
        run_id=runtime.run_id,
        event_type="draft.section_started",
        stage="draft",
        data={"section_id": "s1"},
    )

    await runtime.flush_pending_events()
    await runtime.flush_pending_events()

    assert appended_event_types == ["progress", "draft.section_started"]
    assert flush_calls == ["flush", "flush"]


@pytest.mark.asyncio
async def test_runtime_execute_node_uses_runtime_event_store_for_sync_node_progress(
    monkeypatch: pytest.MonkeyPatch, runtime: ResearchRuntime
) -> None:
    emitted_event_types: list[str] = []

    class _SyncSessionStub:
        def get_bind(self):
            return SimpleNamespace(
                dialect=SimpleNamespace(name="sqlite", driver="pysqlite")
            )

    async def fake_assert_not_cancelled(self) -> None:
        return None

    async def fake_write_after_node(self, *, state, node_name: str) -> None:
        return None

    async def fake_run_sync(fn):
        return fn(_SyncSessionStub())

    async def fake_append(self, **kwargs):
        emitted_event_types.append(kwargs["event_type"])
        return None

    async def fake_commit() -> None:
        return None

    def fail_if_direct_append(**_kwargs):
        raise AssertionError("node event writes must go through runtime event_store")

    monkeypatch.setattr(type(runtime), "assert_not_cancelled", fake_assert_not_cancelled, raising=False)
    monkeypatch.setattr(type(runtime.checkpoint_store), "write_after_node", fake_write_after_node, raising=False)
    monkeypatch.setattr(runtime.session, "run_sync", fake_run_sync)
    monkeypatch.setattr(type(runtime.event_store), "append", fake_append, raising=False)
    monkeypatch.setattr(runtime.session, "commit", fake_commit)
    monkeypatch.setattr("core.pipeline_events.events.append_run_event", fail_if_direct_append)

    @instrument_node("draft")
    def sync_node(state: OrchestratorState, session) -> OrchestratorState:
        emit_run_event(
            session=session,
            tenant_id=state.tenant_id,
            run_id=state.run_id,
            event_type="progress",
            stage="draft",
            data={"section_index": 1, "total_sections": 3},
        )
        state.iteration_count += 1
        return state

    state = runtime.initial_state()
    result = await runtime.execute_node(node_name="writer", node_func=sync_node, state=state)

    assert result.iteration_count == 1
    assert emitted_event_types == ["stage_start", "progress", "stage_finish"]


@pytest.mark.asyncio
async def test_runtime_execute_node_persists_single_progress_sequence_without_duplicate_direct_writes(
    monkeypatch: pytest.MonkeyPatch, session: AsyncSession, seeded_run: RunRow
) -> None:
    def fail_if_direct_append(**_kwargs):
        raise AssertionError("direct sync append path must not be used for node progress")

    monkeypatch.setattr("core.pipeline_events.events.append_run_event", fail_if_direct_append)
    runtime = await ResearchRuntime.create(
        session=session,
        tenant_id=seeded_run.tenant_id,
        run_id=seeded_run.id,
        inputs=ResearchRunInputs(user_query="persisted progress"),
    )

    @instrument_node("draft")
    def sync_node(state: OrchestratorState, sync_session) -> OrchestratorState:
        emit_node_progress(
            session=sync_session,
            tenant_id=state.tenant_id,
            run_id=state.run_id,
            event_type="progress",
            stage="draft",
            data={"section_index": 1, "total_sections": 1},
        )
        state.iteration_count += 1
        return state

    state = runtime.initial_state()
    await runtime.execute_node(node_name="writer", node_func=sync_node, state=state)
    rows = (
        await session.execute(
            select(RunEventRow)
            .where(
                RunEventRow.tenant_id == seeded_run.tenant_id,
                RunEventRow.run_id == seeded_run.id,
            )
            .order_by(RunEventRow.event_number.asc())
        )
    ).scalars().all()

    event_types = [row.event_type for row in rows]
    assert event_types == ["stage_start", "progress", "stage_finish"]
    assert [row.event_number for row in rows] == [1, 2, 3]


@pytest.mark.asyncio
async def test_run_orchestrator_final_execute_node_commit_ignores_late_cancel(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id = uuid4()
    run_id = uuid4()
    run_row = SimpleNamespace(id=run_id, tenant_id=tenant_id, project_id=uuid4())
    statuses: list[RunStatusDb] = []

    class _ExecuteResult:
        def scalar_one_or_none(self):
            return run_row

    class _SessionStub:
        def __init__(self):
            self.cancel_requested = False

        async def execute(self, _stmt):
            return _ExecuteResult()

        async def flush(self):
            return None

        async def run_sync(self, fn):
            return fn(None)

        async def commit(self):
            # Simulate a cancellation signal landing right after final-step commit.
            self.cancel_requested = True

        async def rollback(self):
            return None

    session = _SessionStub()
    runtime = ResearchRuntime(
        session=session,
        tenant_id=tenant_id,
        run_id=run_id,
        inputs=ResearchRunInputs(user_query="q"),
        event_store=RuntimeEventStore(session=session),
        checkpoint_store=RuntimeCheckpointStore(session=session),
    )

    async def fake_transition(**kwargs):
        statuses.append(kwargs["to_status"])
        return run_row

    async def fake_checkpoint(*args, **kwargs):
        return None

    async def fake_assert_not_cancelled(self):
        if self.session.cancel_requested:
            raise RunCancelledError("cancelled after commit")

    class _FakeGraph:
        def __init__(self, graph_runtime: ResearchRuntime):
            self.graph_runtime = graph_runtime

        async def ainvoke(self, state, config=None):
            orchestrator_state = OrchestratorState(**state)

            def final_node(node_state, _session):
                node_state.artifacts = {}
                return node_state

            next_state = await self.graph_runtime.execute_node(
                node_name="exporter",
                node_func=final_node,
                state=orchestrator_state,
            )
            return next_state.model_dump()

    monkeypatch.setattr("services.orchestrator.runner.transition_run_status_async", fake_transition)
    monkeypatch.setattr("services.orchestrator.runner._persist_artifacts", AsyncMock(return_value=0))
    monkeypatch.setattr(
        "services.orchestrator.runner.create_orchestrator_graph",
        lambda graph_runtime: _FakeGraph(graph_runtime),
    )
    monkeypatch.setattr(type(runtime.checkpoint_store), "write_after_node", fake_checkpoint, raising=False)
    monkeypatch.setattr(type(runtime), "assert_not_cancelled", fake_assert_not_cancelled, raising=False)

    result = await run_orchestrator(
        session=session,
        tenant_id=tenant_id,
        run_id=run_id,
        user_query="q",
        transition_to_running=False,
        runtime=runtime,
    )

    assert result.user_query == "q"
    assert statuses == [RunStatusDb.succeeded]


@pytest.mark.asyncio
async def test_run_orchestrator_no_longer_uses_sync_session(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import importlib

    tenant_id = uuid4()
    run_id = uuid4()
    project_id = uuid4()
    run_row = SimpleNamespace(id=run_id, tenant_id=tenant_id, project_id=project_id)

    class _ExecuteResult:
        def scalar_one_or_none(self):
            return run_row

    class _SessionStub:
        @property
        def sync_session(self):
            raise AssertionError("sync_session should not be accessed")

        async def execute(self, _stmt):
            return _ExecuteResult()

        async def commit(self):
            return None

        async def rollback(self):
            return None

    class _FakeGraph:
        def invoke(self, state, config=None):
            return state

        async def ainvoke(self, state, config=None):
            return state

    async def _noop_transition(*args, **kwargs):
        return None

    run_orchestrator_func = run_research_orchestrator.__globals__["run_orchestrator"]
    runner_module = importlib.import_module(run_orchestrator_func.__module__)

    session = _SessionStub()
    monkeypatch.setitem(
        run_research_orchestrator.__globals__,
        "transition_run_status_async",
        _noop_transition,
    )
    monkeypatch.setattr(runner_module, "transition_run_status_async", _noop_transition)
    monkeypatch.setattr(runner_module, "_persist_artifacts", AsyncMock(return_value=0))
    monkeypatch.setattr(runner_module, "create_orchestrator_graph", lambda *_a, **_k: _FakeGraph())

    final_state = await run_research_orchestrator(
        session=session,
        tenant_id=tenant_id,
        run_id=run_id,
        inputs=ResearchRunInputs(user_query="q"),
    )

    assert final_state.user_query == "q"


@pytest.mark.asyncio
async def test_resume_orchestrator_transitions_to_canceled_on_run_cancelled_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id = uuid4()
    run_id = uuid4()
    statuses: list[RunStatusDb] = []
    commits = 0
    rollbacks = 0
    checkpoint_payload = {
        "tenant_id": str(tenant_id),
        "run_id": str(run_id),
        "user_query": "checkpoint query",
        "max_iterations": 5,
    }

    class _ExecuteResult:
        def scalars(self):
            return self

        def first(self):
            return checkpoint_payload

    class _SessionStub:
        async def execute(self, _stmt):
            return _ExecuteResult()

        async def commit(self):
            nonlocal commits
            commits += 1

        async def rollback(self):
            nonlocal rollbacks
            rollbacks += 1

    class _FakeGraph:
        async def ainvoke(self, _state, config=None):
            raise resume_orchestrator.__globals__["RunCancelledError"]("resume canceled")

    async def _fake_transition(**kwargs):
        statuses.append(kwargs["to_status"])
        return SimpleNamespace(status=kwargs["to_status"])

    monkeypatch.setattr("services.orchestrator.runner.create_orchestrator_graph", lambda *_a, **_k: _FakeGraph())
    monkeypatch.setattr("services.orchestrator.runner.transition_run_status_async", _fake_transition)

    result = await resume_orchestrator(
        session=_SessionStub(),
        tenant_id=tenant_id,
        run_id=run_id,
    )

    assert result.user_query == "checkpoint query"
    assert statuses == [RunStatusDb.canceled]
    assert rollbacks == 1
    assert commits == 1


@pytest.mark.asyncio
async def test_resume_orchestrator_transitions_to_failed_on_graph_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id = uuid4()
    run_id = uuid4()
    statuses: list[RunStatusDb] = []
    failure_reasons: list[str] = []
    commits = 0
    rollbacks = 0
    checkpoint_payload = {
        "tenant_id": str(tenant_id),
        "run_id": str(run_id),
        "user_query": "checkpoint query",
        "max_iterations": 5,
    }

    class _ExecuteResult:
        def scalars(self):
            return self

        def first(self):
            return checkpoint_payload

    class _SessionStub:
        async def execute(self, _stmt):
            return _ExecuteResult()

        async def commit(self):
            nonlocal commits
            commits += 1

        async def rollback(self):
            nonlocal rollbacks
            rollbacks += 1

    class _FakeGraph:
        async def ainvoke(self, _state, config=None):
            raise RuntimeError("resume failure")

    async def _fake_transition(**kwargs):
        statuses.append(kwargs["to_status"])
        failure_reasons.append(kwargs.get("failure_reason"))
        return SimpleNamespace(status=kwargs["to_status"])

    monkeypatch.setattr("services.orchestrator.runner.create_orchestrator_graph", lambda *_a, **_k: _FakeGraph())
    monkeypatch.setattr("services.orchestrator.runner.transition_run_status_async", _fake_transition)

    with pytest.raises(RuntimeError, match="resume failure"):
        await resume_orchestrator(
            session=_SessionStub(),
            tenant_id=tenant_id,
            run_id=run_id,
        )

    assert statuses == [RunStatusDb.failed]
    assert failure_reasons == ["resume failure"]
    assert rollbacks == 1
    assert commits == 1


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
