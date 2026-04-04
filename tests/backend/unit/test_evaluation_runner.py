"""Unit tests for the refactored EvaluationRunner."""

from __future__ import annotations

import json
import os
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

_TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql+psycopg://postgres:postgres@localhost:5432/researchops_test",
)
_TEST_ASYNC_DATABASE_URL = _TEST_DATABASE_URL.replace(
    "postgresql+psycopg://", "postgresql+asyncpg://"
)


def _make_execute_result(rows=None, scalar_result=None):
    result = MagicMock()
    if rows is not None:
        result.all.return_value = rows
        result.scalars.return_value.all.return_value = rows
        result.scalars.return_value.first.return_value = rows[0] if rows else None
        result.scalar_one_or_none.return_value = rows[0] if rows else None
    elif scalar_result is not None:
        result.scalar_one_or_none.return_value = scalar_result
        result.scalars.return_value.first.return_value = scalar_result
        result.all.return_value = [scalar_result]
    else:
        result.all.return_value = []
        result.scalars.return_value.all.return_value = []
        result.scalars.return_value.first.return_value = None
        result.scalar_one_or_none.return_value = None
    return result


def _make_async_session(*execute_returns):
    session = MagicMock()
    session.execute = AsyncMock(side_effect=list(execute_returns))
    session.flush = AsyncMock()
    session.commit = AsyncMock()
    session.add = MagicMock()
    return session


async def _collect(async_gen):
    events = []
    async for event in async_gen:
        events.append(event)
    return events


def _make_sec_row(section_id: str, title: str = "Section", order: int = 1):
    r = MagicMock()
    r.section_id = section_id
    r.title = title
    r.section_order = order
    return r


def _make_draft_row(section_id: str, text: str = "Section text."):
    r = MagicMock()
    r.section_id = section_id
    r.text = text
    return r


def _make_snippet_row(text: str = "Evidence snippet."):
    r = MagicMock()
    r.id = uuid4()
    r.text = text
    return r


def _make_claim_row(claim_text: str, claim_index: int = 0):
    r = MagicMock()
    r.claim_text = claim_text
    r.claim_index = claim_index
    return r


def _make_pass_row():
    r = MagicMock()
    r.id = uuid4()
    r.status = "running"
    return r


@pytest.mark.asyncio
async def test_run_yields_started_and_complete_events():
    """run() yields evaluation.started and evaluation.complete in order."""
    from app_services.evaluation_runner import EvaluationRunner

    tenant_id = uuid4()
    run_id = uuid4()
    sec = _make_sec_row("s1")
    draft = _make_draft_row("s1", "Model A achieves 95% accuracy.")
    claim = _make_claim_row("Model A achieves 95% accuracy.", 0)
    snippet = _make_snippet_row("Benchmarks show 95% accuracy.")
    pass_row = _make_pass_row()

    verdict_response = json.dumps({
        "verdicts": [{"claim_index": 0, "verdict": "supported", "citations": [], "notes": ""}]
    })
    mock_llm = MagicMock()
    mock_llm.generate.return_value = verdict_response

    session = _make_async_session(
        _make_execute_result(scalar_result=pass_row),     # create_evaluation_pass flush
        _make_execute_result(scalar_result=None),         # _write_metric(METRIC_EVAL_STATUS)
        _make_execute_result(rows=[sec]),                 # _load_sections: RunSectionRow
        _make_execute_result(rows=[draft]),               # _load_sections: DraftSectionRow
        _make_execute_result(rows=[claim]),               # _load_or_extract_claims: cached claims
        _make_execute_result(rows=[snippet]),             # _load_section_snippets
        _make_execute_result(scalar_result=None),         # record_eval_section select (upsert)
        _make_execute_result(scalar_result=None),         # finalize_evaluation_pass select
        _make_execute_result(scalar_result=None),         # _write_metric(quality_pct)
        _make_execute_result(scalar_result=None),         # _write_metric(hallucination_rate)
        _make_execute_result(scalar_result=None),         # _write_metric(evaluated_at)
        _make_execute_result(scalar_result=None),         # _write_metric(status=complete)
    )

    with patch("app_services.evaluation_runner.get_llm_client_for_stage", return_value=mock_llm):
        runner = EvaluationRunner(session=session, tenant_id=tenant_id, run_id=run_id)
        events = await _collect(runner.run())

    event_types = [e["type"] for e in events]
    assert "evaluation.started" in event_types
    assert "evaluation.complete" in event_types
    assert event_types.index("evaluation.started") < event_types.index("evaluation.complete")


@pytest.mark.asyncio
async def test_run_emits_section_event_with_quality_score():
    """run() emits evaluation.section with quality_score and verdicts."""
    from app_services.evaluation_runner import EvaluationRunner

    tenant_id = uuid4()
    run_id = uuid4()
    sec = _make_sec_row("s1", "Results")
    draft = _make_draft_row("s1", "Model A achieves 95% accuracy.")
    claim = _make_claim_row("Model A achieves 95% accuracy.", 0)
    snippet = _make_snippet_row("Benchmarks show 95% accuracy.")
    pass_row = _make_pass_row()

    verdict_response = json.dumps({
        "verdicts": [{"claim_index": 0, "verdict": "supported", "citations": ["s1"], "notes": ""}]
    })
    mock_llm = MagicMock()
    mock_llm.generate.return_value = verdict_response

    session = _make_async_session(
        _make_execute_result(scalar_result=pass_row),
        _make_execute_result(scalar_result=None),
        _make_execute_result(rows=[sec]),
        _make_execute_result(rows=[draft]),
        _make_execute_result(rows=[claim]),
        _make_execute_result(rows=[snippet]),
        _make_execute_result(scalar_result=None),
        _make_execute_result(scalar_result=None),
        _make_execute_result(scalar_result=None),
        _make_execute_result(scalar_result=None),
        _make_execute_result(scalar_result=None),
        _make_execute_result(scalar_result=None),
    )

    with patch("app_services.evaluation_runner.get_llm_client_for_stage", return_value=mock_llm):
        runner = EvaluationRunner(session=session, tenant_id=tenant_id, run_id=run_id)
        events = await _collect(runner.run())

    section_events = [e for e in events if e["type"] == "evaluation.section"]
    assert len(section_events) == 1
    assert section_events[0]["section_id"] == "s1"
    assert section_events[0]["quality_score"] == 100  # 1 supported claim


@pytest.mark.asyncio
async def test_run_complete_event_has_quality_pct_and_hallucination_rate():
    """evaluation.complete event includes quality_pct and hallucination_rate."""
    from app_services.evaluation_runner import EvaluationRunner

    tenant_id = uuid4()
    run_id = uuid4()
    sec = _make_sec_row("s1")
    draft = _make_draft_row("s1", "Unsupported claim about AI.")
    claim = _make_claim_row("Unsupported claim about AI.", 0)
    snippet = _make_snippet_row("Evidence text.")
    pass_row = _make_pass_row()

    verdict_response = json.dumps({
        "verdicts": [{"claim_index": 0, "verdict": "unsupported", "citations": [], "notes": "No evidence"}]
    })
    mock_llm = MagicMock()
    mock_llm.generate.return_value = verdict_response

    session = _make_async_session(
        _make_execute_result(scalar_result=pass_row),
        _make_execute_result(scalar_result=None),
        _make_execute_result(rows=[sec]),
        _make_execute_result(rows=[draft]),
        _make_execute_result(rows=[claim]),
        _make_execute_result(rows=[snippet]),
        _make_execute_result(scalar_result=None),
        _make_execute_result(scalar_result=None),
        _make_execute_result(scalar_result=None),
        _make_execute_result(scalar_result=None),
        _make_execute_result(scalar_result=None),
        _make_execute_result(scalar_result=None),
    )

    with patch("app_services.evaluation_runner.get_llm_client_for_stage", return_value=mock_llm):
        runner = EvaluationRunner(session=session, tenant_id=tenant_id, run_id=run_id)
        events = await _collect(runner.run())

    complete = next(e for e in events if e["type"] == "evaluation.complete")
    assert complete["quality_pct"] == 0     # 1 unsupported → weight=0 → quality=0
    assert complete["hallucination_rate"] == 100  # 1 unsupported counts as hallucination


@pytest.mark.asyncio
async def test_run_uses_cached_claims_without_extracting():
    """Cached claims from section_claims table are used without calling the extractor."""
    from app_services.evaluation_runner import EvaluationRunner

    tenant_id = uuid4()
    run_id = uuid4()
    sec = _make_sec_row("s1")
    draft = _make_draft_row("s1", "Model achieves 95% accuracy.")
    cached_claim = _make_claim_row("Model achieves 95% accuracy.", 0)
    snippet = _make_snippet_row()
    pass_row = _make_pass_row()

    verdict_response = json.dumps({
        "verdicts": [{"claim_index": 0, "verdict": "supported", "citations": [], "notes": ""}]
    })
    mock_llm = MagicMock()
    mock_llm.generate.return_value = verdict_response

    session = _make_async_session(
        _make_execute_result(scalar_result=pass_row),
        _make_execute_result(scalar_result=None),
        _make_execute_result(rows=[sec]),
        _make_execute_result(rows=[draft]),
        _make_execute_result(rows=[cached_claim]),  # cached claims found
        _make_execute_result(rows=[snippet]),
        _make_execute_result(scalar_result=None),
        _make_execute_result(scalar_result=None),
        _make_execute_result(scalar_result=None),
        _make_execute_result(scalar_result=None),
        _make_execute_result(scalar_result=None),
        _make_execute_result(scalar_result=None),
    )

    with patch("app_services.evaluation_runner.get_llm_client_for_stage", return_value=mock_llm):
        runner = EvaluationRunner(session=session, tenant_id=tenant_id, run_id=run_id)
        await _collect(runner.run())

    # Only 1 generate call: the verification (not extraction, since cache was used)
    assert mock_llm.generate.call_count == 1
    verify_prompt = mock_llm.generate.call_args_list[0].args[0]
    assert "Model achieves 95% accuracy." in verify_prompt


@pytest.mark.asyncio
async def test_run_extracts_claims_when_cache_empty():
    """When no cached claims exist, RagasExtractor is used to extract them."""
    from app_services.evaluation_runner import EvaluationRunner

    tenant_id = uuid4()
    run_id = uuid4()
    sec = _make_sec_row("s1")
    draft = _make_draft_row("s1", "AI is widely used.")
    snippet = _make_snippet_row("AI is widely adopted.")
    pass_row = _make_pass_row()

    mock_llm = MagicMock()
    # First call: extraction fallback, second call: verification
    mock_llm.generate.side_effect = [
        '{"claims": ["AI is widely used."]}',
        json.dumps({
            "verdicts": [{"claim_index": 0, "verdict": "supported", "citations": [], "notes": ""}]
        }),
    ]

    session = _make_async_session(
        _make_execute_result(scalar_result=pass_row),
        _make_execute_result(scalar_result=None),
        _make_execute_result(rows=[sec]),
        _make_execute_result(rows=[draft]),
        _make_execute_result(rows=[]),        # no cached claims
        _make_execute_result(rows=[snippet]), # snippets for extraction
        _make_execute_result(rows=[snippet]), # snippets for verification
        _make_execute_result(scalar_result=None),
        _make_execute_result(scalar_result=None),
        _make_execute_result(scalar_result=None),
        _make_execute_result(scalar_result=None),
        _make_execute_result(scalar_result=None),
        _make_execute_result(scalar_result=None),
    )

    with patch("app_services.evaluation_runner.get_llm_client_for_stage", return_value=mock_llm):
        runner = EvaluationRunner(session=session, tenant_id=tenant_id, run_id=run_id)
        events = await _collect(runner.run())

    assert mock_llm.generate.call_count == 2
    complete = next(e for e in events if e["type"] == "evaluation.complete")
    assert complete["quality_pct"] == 100


@pytest.mark.asyncio
async def test_runner_persists_running_status_before_completion():
    """Evaluation pass and eval_status=running are visible in DB before run() completes."""
    from app_services.evaluation_runner import EvaluationRunner
    import db.models  # noqa: F401
    from db.init_db import init_db as _init_db
    from db.models.evaluation_passes import EvaluationPassRow
    from db.models.run_sections import RunSectionRow
    from db.models.run_usage_metrics import RunUsageMetricRow
    from db.models.runs import RunStatusDb
    from db.models.draft_sections import DraftSectionRow
    from db.repositories.project_runs import create_project, create_run
    from sqlalchemy import select
    from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
    from sqlalchemy.orm import sessionmaker

    engine = create_async_engine(_TEST_ASYNC_DATABASE_URL, future=True)
    await _init_db(engine)
    AsyncSessionLocal = sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)

    tenant_id = uuid4()

    async with AsyncSessionLocal() as session:
        project = await create_project(
            session=session,
            tenant_id=tenant_id,
            name="Evaluation Progress Visibility",
            description=None,
            created_by="user-1",
        )
        run = await create_run(
            session=session,
            tenant_id=tenant_id,
            project_id=project.id,
            status=RunStatusDb.succeeded,
            question="Why is evaluation progress stale?",
        )
        # Add a section so the runner doesn't short-circuit to complete immediately
        session.add(RunSectionRow(
            tenant_id=tenant_id,
            run_id=run.id,
            section_id="intro",
            title="Introduction",
            goal="Intro",
            section_order=1,
        ))
        session.add(DraftSectionRow(
            tenant_id=tenant_id,
            run_id=run.id,
            section_id="intro",
            text="AI is widely used in healthcare.",
        ))
        await session.commit()
        run_id = run.id

    async with AsyncSessionLocal() as writer_session:
        runner = EvaluationRunner(session=writer_session, tenant_id=tenant_id, run_id=run_id)
        event_stream = runner.run()

        started = await event_stream.__anext__()
        assert started["type"] == "evaluation.started"

        step_event = await event_stream.__anext__()
        assert step_event["type"] == "evaluation.step"
        assert step_event["step"] == 1

        async with AsyncSessionLocal() as reader_session:
            evaluation_pass = (await reader_session.execute(
                select(EvaluationPassRow).where(
                    EvaluationPassRow.tenant_id == tenant_id,
                    EvaluationPassRow.run_id == run_id,
                )
            )).scalar_one_or_none()
            status_metric = (await reader_session.execute(
                select(RunUsageMetricRow).where(
                    RunUsageMetricRow.tenant_id == tenant_id,
                    RunUsageMetricRow.run_id == run_id,
                    RunUsageMetricRow.metric_name == "eval_status",
                )
            )).scalar_one_or_none()

            assert evaluation_pass is not None
            assert evaluation_pass.status == "running"
            assert status_metric is not None
            assert status_metric.metric_text == "running"

        # Exhaust the generator
        await _collect(event_stream)

    await engine.dispose()
