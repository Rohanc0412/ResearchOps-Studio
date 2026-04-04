from __future__ import annotations

import json
import os
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from llm import LLMError

_TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql+psycopg://postgres:postgres@localhost:5432/researchops_test",
)
_TEST_ASYNC_DATABASE_URL = _TEST_DATABASE_URL.replace(
    "postgresql+psycopg://", "postgresql+asyncpg://"
)


def _make_execute_result(rows=None, scalar_result=None):
    """Return a mock result object suitable for await session.execute(...)."""
    result = MagicMock()
    if rows is not None:
        result.all.return_value = rows
        result.scalars.return_value.all.return_value = rows
        result.scalars.return_value.first.return_value = rows[0] if rows else None
        result.scalar_one_or_none.return_value = rows[0] if rows else None
    elif scalar_result is not None:
        result.scalar_one_or_none.return_value = scalar_result
        result.scalars.return_value.first.return_value = scalar_result
        result.all.return_value = [scalar_result] if scalar_result is not None else []
    else:
        result.all.return_value = []
        result.scalars.return_value.all.return_value = []
        result.scalars.return_value.first.return_value = None
        result.scalar_one_or_none.return_value = None
    return result


def _make_async_session(*execute_returns):
    """Return a mock AsyncSession whose execute() calls return the given results in order."""
    session = MagicMock()
    session.execute = AsyncMock(side_effect=list(execute_returns))
    session.flush = AsyncMock()
    session.commit = AsyncMock()
    session.add = MagicMock()
    return session


async def _collect(async_gen):
    """Exhaust an async generator into a list."""
    events = []
    async for event in async_gen:
        events.append(event)
    return events


@pytest.mark.asyncio
async def test_grounding_step_yields_section_and_done_events():
    """EvaluationRunner yields evaluation.section and evaluation.grounding_done events."""
    from app_services.evaluation_runner import EvaluationRunner

    tenant_id = uuid4()
    run_id = uuid4()
    section_id = "s1"

    grounding_response = json.dumps({
        "section_id": section_id,
        "grounding_score": 90,
        "verdict": "pass",
        "issues": [],
    })

    mock_llm = MagicMock()
    mock_llm.generate.return_value = grounding_response

    draft_row = MagicMock()
    draft_row.section_id = section_id
    draft_row.text = "The model achieved 95% accuracy on the test set."

    sec_row = MagicMock()
    sec_row.section_id = section_id
    sec_row.title = "Results"
    sec_row.section_order = 0

    snippet_row = MagicMock()
    snippet_row.id = uuid4()
    snippet_row.text = "Evaluation results show 95% accuracy on held-out test data."

    # _run_grounding executes: drafts, sections, snippets per section, _persist_section_review (select), flush
    # _persist_section_review: select SectionReviewRow -> None (no existing), then add
    # After loop: write_metric (select x2), flush, commit
    metric_none = _make_execute_result(scalar_result=None)

    session = _make_async_session(
        _make_execute_result(rows=[draft_row]),    # drafts
        _make_execute_result(rows=[sec_row]),      # sections
        _make_execute_result(rows=[snippet_row]),  # snippets for section
        _make_execute_result(scalar_result=None),  # _persist_section_review select
        _make_execute_result(scalar_result=None),  # _write_metric(METRIC_EVAL_GROUNDING_PCT)
        _make_execute_result(scalar_result=None),  # _write_metric(eval_sections_passed)
        _make_execute_result(scalar_result=None),  # _write_metric(eval_sections_total)
    )

    with patch("app_services.evaluation_runner.get_llm_client_for_stage", return_value=mock_llm):
        runner = EvaluationRunner(session=session, tenant_id=tenant_id, run_id=run_id)
        events = await _collect(runner._run_grounding())

    event_types = [e["type"] for e in events]
    assert "evaluation.section" in event_types
    assert "evaluation.grounding_done" in event_types

    section_event = next(e for e in events if e["type"] == "evaluation.section")
    assert section_event["grounding_score"] == 90
    assert section_event["verdict"] == "pass"

    done_event = next(e for e in events if e["type"] == "evaluation.grounding_done")
    assert done_event["overall_grounding_pct"] == 90
    assert done_event["pass_count"] == 1
    assert done_event["fail_count"] == 0


@pytest.mark.asyncio
async def test_faithfulness_step_yields_faithfulness_done_event():
    """Faithfulness step extracts claims and verifies them, yielding faithfulness_done."""
    from app_services.evaluation_runner import EvaluationRunner

    tenant_id = uuid4()
    run_id = uuid4()
    section_id = "s1"

    claims_response = json.dumps({"claims": ["Model achieves 95% accuracy.", "Training used 400B tokens."]})
    faithfulness_response = json.dumps({
        "verdicts": [
            {"claim_index": 0, "supported": True},
            {"claim_index": 1, "supported": False},
        ]
    })

    mock_llm = MagicMock()
    mock_llm.generate.side_effect = [claims_response, faithfulness_response]

    draft_row = MagicMock()
    draft_row.section_id = section_id
    draft_row.text = "Model achieves 95% accuracy. Training used 400B tokens."

    section_row = MagicMock()
    section_row.section_id = section_id
    section_row.title = "Results"
    section_row.section_order = 1

    snippet_row = MagicMock()
    snippet_row.id = uuid4()
    snippet_row.text = "Evaluation shows 95% accuracy on held-out test data."

    session = _make_async_session(
        _make_execute_result(scalar_result=None),   # artifact
        _make_execute_result(rows=[draft_row]),     # drafts
        _make_execute_result(rows=[section_row]),   # sections
        _make_execute_result(rows=[snippet_row]),   # snippets
        _make_execute_result(scalar_result=None),   # faithfulness_pct metric
    )

    with patch("app_services.evaluation_runner.get_llm_client_for_stage", return_value=mock_llm):
        runner = EvaluationRunner(session=session, tenant_id=tenant_id, run_id=run_id)
        events = await _collect(runner._run_faithfulness())

    assert len(events) == 1
    event = events[0]
    assert event["type"] == "evaluation.faithfulness_done"
    assert event["total_claims"] == 2
    assert event["supported_claims"] == 1
    assert event["faithfulness_pct"] == 50
    session.add.assert_called_once()
    session.flush.assert_called()


@pytest.mark.asyncio
async def test_faithfulness_runs_per_section_against_section_evidence():
    """Faithfulness should verify claims section-by-section against each section's evidence."""
    from app_services.evaluation_runner import EvaluationRunner

    tenant_id = uuid4()
    run_id = uuid4()

    intro_section = MagicMock()
    intro_section.section_id = "intro"
    intro_section.title = "Introduction"
    intro_section.section_order = 1
    intro_draft = MagicMock()
    intro_draft.section_id = "intro"
    intro_draft.text = "Model A supports 100 languages."
    intro_snippet = MagicMock()
    intro_snippet.id = uuid4()
    intro_snippet.text = "Benchmarks confirm Model A supports 100 languages."

    gpu_section = MagicMock()
    gpu_section.section_id = "gpu"
    gpu_section.title = "GPU Fit"
    gpu_section.section_order = 2
    gpu_draft = MagicMock()
    gpu_draft.section_id = "gpu"
    gpu_draft.text = "Model B fits within an 8 GB VRAM budget."
    gpu_snippet = MagicMock()
    gpu_snippet.id = uuid4()
    gpu_snippet.text = "Measurements show Model B runs within an 8 GB VRAM budget."

    mock_llm = MagicMock()
    mock_llm.generate.side_effect = [
        json.dumps({"claims": ["Model A supports 100 languages."]}),
        json.dumps({"verdicts": [{"claim_index": 0, "supported": True}]}),
        json.dumps({"claims": ["Model B fits within an 8 GB VRAM budget."]}),
        json.dumps({"verdicts": [{"claim_index": 0, "supported": True}]}),
    ]

    session = _make_async_session(
        _make_execute_result(scalar_result=None),           # artifact
        _make_execute_result(rows=[intro_draft, gpu_draft]),  # drafts
        _make_execute_result(rows=[intro_section, gpu_section]),  # sections
        _make_execute_result(rows=[intro_snippet]),         # intro snippets
        _make_execute_result(rows=[gpu_snippet]),           # gpu snippets
        _make_execute_result(scalar_result=None),           # faithfulness_pct metric
    )

    with patch("app_services.evaluation_runner.get_llm_client_for_stage", return_value=mock_llm):
        runner = EvaluationRunner(session=session, tenant_id=tenant_id, run_id=run_id)
        events = await _collect(runner._run_faithfulness())

    assert len(events) == 1
    event = events[0]
    assert event["type"] == "evaluation.faithfulness_done"
    assert event["total_claims"] == 2
    assert event["supported_claims"] == 2
    assert event["faithfulness_pct"] == 100
    assert mock_llm.generate.call_count == 4

    verify_prompts = [
        call.args[0]
        for call in mock_llm.generate.call_args_list
        if isinstance(call.args[0], str) and call.args[0].startswith("For each numbered claim")
    ]
    assert len(verify_prompts) == 2
    assert "100 languages" in verify_prompts[0]
    assert "8 GB VRAM budget" not in verify_prompts[0]
    assert "8 GB VRAM budget" in verify_prompts[1]
    assert "100 languages" not in verify_prompts[1]


@pytest.mark.asyncio
async def test_faithfulness_always_uses_llm_claim_extraction():
    """Faithfulness always uses LLM extraction for all factual claims, not just cited sentences."""
    from app_services.evaluation_runner import EvaluationRunner

    tenant_id = uuid4()
    run_id = uuid4()
    section_id = "s1"

    draft_row = MagicMock()
    draft_row.section_id = section_id
    draft_row.text = (
        "This is a framing sentence without evidence. "
        "Model A supports 100 languages [^1]. "
        "Model B fits within 8 GB VRAM [^2]."
    )
    section_row = MagicMock()
    section_row.section_id = section_id
    section_row.title = "Results"
    section_row.section_order = 1
    snippet_row = MagicMock()
    snippet_row.id = uuid4()
    snippet_row.text = "Benchmarks show Model A supports 100 languages and Model B fits within 8 GB VRAM."

    session = _make_async_session(
        _make_execute_result(scalar_result=None),   # artifact
        _make_execute_result(rows=[draft_row]),     # drafts
        _make_execute_result(rows=[section_row]),   # sections
        _make_execute_result(rows=[snippet_row]),   # snippets
        _make_execute_result(scalar_result=None),   # faithfulness_pct metric
    )

    claims_response = json.dumps({"claims": ["Model A supports 100 languages.", "Model B fits within 8 GB VRAM."]})
    verdicts_response = json.dumps({
        "verdicts": [
            {"claim_index": 0, "supported": True},
            {"claim_index": 1, "supported": True},
        ]
    })

    mock_llm = MagicMock()
    mock_llm.generate.side_effect = [claims_response, verdicts_response]

    with patch("app_services.evaluation_runner.get_llm_client_for_stage", return_value=mock_llm):
        runner = EvaluationRunner(session=session, tenant_id=tenant_id, run_id=run_id)
        events = await _collect(runner._run_faithfulness())

    event = events[0]
    assert event["total_claims"] == 2
    assert event["supported_claims"] == 2
    assert event["faithfulness_pct"] == 100
    assert mock_llm.generate.call_count == 2


@pytest.mark.asyncio
async def test_faithfulness_uses_artifact_markdown_over_draft_text():
    """Artifact markdown should win over plain draft text for claim extraction source."""
    from app_services.evaluation_runner import EvaluationRunner

    tenant_id = uuid4()
    run_id = uuid4()
    section_id = "s1"

    draft_row = MagicMock()
    draft_row.section_id = section_id
    draft_row.text = "Model A supports 100 languages. Model B fits within 8 GB VRAM."
    section_row = MagicMock()
    section_row.section_id = section_id
    section_row.title = "Results"
    section_row.section_order = 1
    artifact_row = MagicMock()
    artifact_row.metadata_json = {
        "markdown": "# Research Report\n\n## 1. Results\n\nModel A supports 100 languages [^1]. Model B fits within 8 GB VRAM [^2]."
    }
    snippet_row = MagicMock()
    snippet_row.id = uuid4()
    snippet_row.text = "Benchmarks show Model A supports 100 languages and Model B fits within 8 GB VRAM."

    session = _make_async_session(
        _make_execute_result(rows=[artifact_row]),  # artifact
        _make_execute_result(rows=[draft_row]),     # drafts
        _make_execute_result(rows=[section_row]),   # sections
        _make_execute_result(rows=[snippet_row]),   # snippets
        _make_execute_result(scalar_result=None),   # faithfulness_pct metric
    )

    claims_response = json.dumps({"claims": ["Model A supports 100 languages.", "Model B fits within 8 GB VRAM."]})
    verdicts_response = json.dumps({
        "verdicts": [
            {"claim_index": 0, "supported": True},
            {"claim_index": 1, "supported": True},
        ]
    })

    mock_llm = MagicMock()
    mock_llm.generate.side_effect = [claims_response, verdicts_response]

    with patch("app_services.evaluation_runner.get_llm_client_for_stage", return_value=mock_llm):
        runner = EvaluationRunner(session=session, tenant_id=tenant_id, run_id=run_id)
        events = await _collect(runner._run_faithfulness())

    event = events[0]
    assert event["total_claims"] == 2
    assert event["supported_claims"] == 2
    assert event["faithfulness_pct"] == 100
    assert mock_llm.generate.call_count == 2
    # Verify the extraction prompt used the artifact markdown text, not the plain draft
    extraction_prompt = mock_llm.generate.call_args_list[0].args[0]
    assert "[^1]" in extraction_prompt


@pytest.mark.asyncio
async def test_faithfulness_skips_section_when_claim_extraction_llm_fails():
    """Manual evaluation should skip extraction failures instead of aborting the whole rerun."""
    from app_services.evaluation_runner import EvaluationRunner

    tenant_id = uuid4()
    run_id = uuid4()

    uncited_section = MagicMock()
    uncited_section.section_id = "uncited"
    uncited_section.title = "Background"
    uncited_section.section_order = 1
    uncited_draft = MagicMock()
    uncited_draft.section_id = "uncited"
    uncited_draft.text = "Transformer variants reduce attention cost through sparse routing."

    cited_section = MagicMock()
    cited_section.section_id = "cited"
    cited_section.title = "Results"
    cited_section.section_order = 2
    cited_draft = MagicMock()
    cited_draft.section_id = "cited"
    cited_draft.text = "A benchmark shows 15% lower latency [^1]."

    snippet_row = MagicMock()
    snippet_row.id = uuid4()
    snippet_row.text = "The benchmark measured 15% lower latency."

    session = _make_async_session(
        _make_execute_result(scalar_result=None),                      # artifact
        _make_execute_result(rows=[uncited_draft, cited_draft]),        # drafts
        _make_execute_result(rows=[uncited_section, cited_section]),    # sections
        _make_execute_result(rows=[snippet_row]),                       # snippets for cited section
        _make_execute_result(scalar_result=None),                       # faithfulness_pct metric
    )

    mock_llm = MagicMock()
    mock_llm.generate.side_effect = [
        LLMError("Hosted LLM request failed: 402 Payment Required"),  # uncited extraction fails
        json.dumps({"claims": ["A benchmark shows 15% lower latency."]}),  # cited extraction
        json.dumps({"verdicts": [{"claim_index": 0, "supported": True}]}),  # cited verification
    ]

    with patch("app_services.evaluation_runner.get_llm_client_for_stage", return_value=mock_llm):
        runner = EvaluationRunner(session=session, tenant_id=tenant_id, run_id=run_id)
        events = await _collect(runner._run_faithfulness())

    assert len(events) == 1
    event = events[0]
    assert event["type"] == "evaluation.faithfulness_done"
    assert event["total_claims"] == 1
    assert event["supported_claims"] == 1
    assert event["faithfulness_pct"] == 100


@pytest.mark.asyncio
async def test_faithfulness_skips_section_when_extraction_llm_fails():
    """Manual evaluation should keep scoring later sections when one extraction call fails."""
    from app_services.evaluation_runner import EvaluationRunner

    tenant_id = uuid4()
    run_id = uuid4()

    first_section = MagicMock()
    first_section.section_id = "first"
    first_section.title = "Section One"
    first_section.section_order = 1
    first_draft = MagicMock()
    first_draft.section_id = "first"
    first_draft.text = "Model A supports 100 languages."

    second_section = MagicMock()
    second_section.section_id = "second"
    second_section.title = "Section Two"
    second_section.section_order = 2
    second_draft = MagicMock()
    second_draft.section_id = "second"
    second_draft.text = "Model B fits within 8 GB VRAM."

    second_snippet = MagicMock()
    second_snippet.id = uuid4()
    second_snippet.text = "Measurements show Model B fits within an 8 GB VRAM budget."

    session = _make_async_session(
        _make_execute_result(scalar_result=None),                        # artifact
        _make_execute_result(rows=[first_draft, second_draft]),          # drafts
        _make_execute_result(rows=[first_section, second_section]),      # sections
        # first section is skipped (extraction fails) so no snippets query for it
        _make_execute_result(rows=[second_snippet]),                     # snippets for second
        _make_execute_result(scalar_result=None),                        # faithfulness_pct metric
    )

    mock_llm = MagicMock()
    mock_llm.generate.side_effect = [
        LLMError("Hosted LLM request failed: 402 Payment Required"),         # first extraction fails
        json.dumps({"claims": ["Model B fits within 8 GB VRAM."]}),          # second extraction
        json.dumps({"verdicts": [{"claim_index": 0, "supported": True}]}),   # second verification
    ]

    with patch("app_services.evaluation_runner.get_llm_client_for_stage", return_value=mock_llm):
        runner = EvaluationRunner(session=session, tenant_id=tenant_id, run_id=run_id)
        events = await _collect(runner._run_faithfulness())

    assert len(events) == 1
    event = events[0]
    assert event["type"] == "evaluation.faithfulness_done"
    assert event["total_claims"] == 1
    assert event["supported_claims"] == 1
    assert event["faithfulness_pct"] == 100


@pytest.mark.asyncio
async def test_finalize_step_yields_complete_event_with_issue_counts():
    """Finalize step counts section verdicts and yields evaluation.complete."""
    from app_services.evaluation_runner import EvaluationRunner

    tenant_id = uuid4()
    run_id = uuid4()

    review1 = MagicMock()
    review1.verdict = "pass"
    review1.issues_json = []

    review2 = MagicMock()
    review2.verdict = "fail"
    review2.issues_json = [
        {"sentence_index": 0, "problem": "unsupported", "notes": "no evidence", "citations": []},
        {"sentence_index": 1, "problem": "missing_citation", "notes": "needs cite", "citations": []},
    ]

    session = _make_async_session(
        _make_execute_result(rows=[review1, review2]),  # reviews
        _make_execute_result(scalar_result=None),       # _write_metric(METRIC_EVAL_STATUS)
        _make_execute_result(scalar_result=None),       # _write_metric(eval_evaluated_at)
        _make_execute_result(scalar_result=None),       # _write_metric(eval_sections_passed)
        _make_execute_result(scalar_result=None),       # _write_metric(eval_sections_total)
        _make_execute_result(scalar_result=None),       # _write_metric(METRIC_EVAL_GROUNDING_PCT) - _grounding_pct=75
    )

    runner = EvaluationRunner(session=session, tenant_id=tenant_id, run_id=run_id)
    runner._grounding_pct = 75

    events = await _collect(runner._run_finalize())

    assert len(events) == 1
    event = events[0]
    assert event["type"] == "evaluation.complete"
    assert event["sections_passed"] == 1
    assert event["sections_total"] == 2
    assert event["issues_by_type"]["unsupported"] == 1
    assert event["issues_by_type"]["missing_citation"] == 1
    session.flush.assert_called()


@pytest.mark.asyncio
async def test_runner_persists_running_status_before_completion(tmp_path):
    from app_services.evaluation_runner import EvaluationRunner
    import db.models  # noqa: F401
    from db.init_db import init_db as _init_db
    from db.models.evaluation_passes import EvaluationPassRow
    from db.models.run_usage_metrics import RunUsageMetricRow
    from db.models.runs import RunStatusDb
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

    await engine.dispose()
