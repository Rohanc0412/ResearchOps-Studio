from __future__ import annotations

import json
from unittest.mock import MagicMock, patch
from uuid import uuid4


def _make_session_with_drafts_and_snippets(tenant_id, run_id, section_id):
    """Returns a mock SQLAlchemy session pre-loaded with one draft section and one snippet."""
    session = MagicMock()

    draft_row = MagicMock()
    draft_row.section_id = section_id
    draft_row.text = "The model achieved 95% accuracy on the test set."

    snippet_row = MagicMock()
    snippet_row.id = uuid4()
    snippet_row.text = "Evaluation results show 95% accuracy on held-out test data."
    snippet_row.char_start = 0
    snippet_row.char_end = 60
    snippet_row.source_id = uuid4()

    sec_row = MagicMock()
    sec_row.section_id = section_id
    sec_row.title = "Results"
    sec_row.section_order = 0

    draft_query = MagicMock()
    draft_query.filter.return_value.all.return_value = [draft_row]
    snippet_query = MagicMock()
    snippet_query.join.return_value.join.return_value.filter.return_value.all.return_value = [snippet_row]
    review_query = MagicMock()
    review_query.filter.return_value.one_or_none.return_value = None
    section_query = MagicMock()
    section_query.filter.return_value.order_by.return_value.all.return_value = [sec_row]

    session.query.side_effect = [draft_query, snippet_query, review_query, section_query]
    return session


def test_grounding_step_yields_section_and_done_events():
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

    session = _make_session_with_drafts_and_snippets(tenant_id, run_id, section_id)

    with patch("app_services.evaluation_runner.get_llm_client_for_stage", return_value=mock_llm):
        runner = EvaluationRunner(session=session, tenant_id=tenant_id, run_id=run_id)
        events = list(runner._run_grounding())

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


def test_faithfulness_step_yields_faithfulness_done_event():
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

    artifact_query = MagicMock()
    artifact_query.filter.return_value.first.return_value = None
    draft_query = MagicMock()
    draft_query.filter.return_value.all.return_value = [draft_row]
    section_query = MagicMock()
    section_query.filter.return_value.order_by.return_value.all.return_value = [section_row]
    snippet_query = MagicMock()
    snippet_query.join.return_value.filter.return_value.all.return_value = [snippet_row]
    metric_query = MagicMock()
    metric_query.filter.return_value.one_or_none.return_value = None

    session = MagicMock()
    session.query.side_effect = [artifact_query, draft_query, section_query, snippet_query, metric_query]

    with patch("app_services.evaluation_runner.get_llm_client_for_stage", return_value=mock_llm):
        runner = EvaluationRunner(session=session, tenant_id=tenant_id, run_id=run_id)
        events = list(runner._run_faithfulness())

    assert len(events) == 1
    event = events[0]
    assert event["type"] == "evaluation.faithfulness_done"
    assert event["total_claims"] == 2
    assert event["supported_claims"] == 1
    assert event["faithfulness_pct"] == 50
    session.add.assert_called_once()
    session.flush.assert_called_once()


def test_faithfulness_runs_per_section_against_section_evidence():
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

    draft_query = MagicMock()
    draft_query.filter.return_value.all.return_value = [intro_draft, gpu_draft]
    section_query = MagicMock()
    section_query.filter.return_value.order_by.return_value.all.return_value = [intro_section, gpu_section]
    intro_snippet_query = MagicMock()
    intro_snippet_query.join.return_value.filter.return_value.all.return_value = [intro_snippet]
    gpu_snippet_query = MagicMock()
    gpu_snippet_query.join.return_value.filter.return_value.all.return_value = [gpu_snippet]
    metric_query = MagicMock()
    metric_query.filter.return_value.one_or_none.return_value = None

    session = MagicMock()
    session.query.side_effect = [
        MagicMock(filter=MagicMock(return_value=MagicMock(first=MagicMock(return_value=None)))),
        draft_query,
        section_query,
        intro_snippet_query,
        gpu_snippet_query,
        metric_query,
    ]

    with patch("app_services.evaluation_runner.get_llm_client_for_stage", return_value=mock_llm):
        runner = EvaluationRunner(session=session, tenant_id=tenant_id, run_id=run_id)
        events = list(runner._run_faithfulness())

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


def test_faithfulness_prefers_cited_sentences_over_llm_claim_extraction():
    """When a section already contains cited factual sentences, use them directly as traceable claims."""
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

    draft_query = MagicMock()
    draft_query.filter.return_value.all.return_value = [draft_row]
    section_query = MagicMock()
    section_query.filter.return_value.order_by.return_value.all.return_value = [section_row]
    snippet_query = MagicMock()
    snippet_query.join.return_value.filter.return_value.all.return_value = [snippet_row]
    metric_query = MagicMock()
    metric_query.filter.return_value.one_or_none.return_value = None

    session = MagicMock()
    artifact_query = MagicMock()
    artifact_query.filter.return_value.first.return_value = None
    session.query.side_effect = [artifact_query, draft_query, section_query, snippet_query, metric_query]

    mock_llm = MagicMock()
    mock_llm.generate.return_value = json.dumps({
        "verdicts": [
            {"claim_index": 0, "supported": True},
            {"claim_index": 1, "supported": True},
        ]
    })

    with patch("app_services.evaluation_runner.get_llm_client_for_stage", return_value=mock_llm):
        runner = EvaluationRunner(session=session, tenant_id=tenant_id, run_id=run_id)
        events = list(runner._run_faithfulness())

    event = events[0]
    assert event["total_claims"] == 2
    assert event["supported_claims"] == 2
    assert event["faithfulness_pct"] == 100
    assert mock_llm.generate.call_count == 1


def test_faithfulness_uses_artifact_markdown_when_it_contains_citations():
    """Artifact markdown should win over plain draft text because it preserves citation markers."""
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

    artifact_query = MagicMock()
    artifact_query.filter.return_value.first.return_value = artifact_row
    draft_query = MagicMock()
    draft_query.filter.return_value.all.return_value = [draft_row]
    section_query = MagicMock()
    section_query.filter.return_value.order_by.return_value.all.return_value = [section_row]
    snippet_query = MagicMock()
    snippet_query.join.return_value.filter.return_value.all.return_value = [snippet_row]
    metric_query = MagicMock()
    metric_query.filter.return_value.one_or_none.return_value = None

    session = MagicMock()
    session.query.side_effect = [artifact_query, draft_query, section_query, snippet_query, metric_query]

    mock_llm = MagicMock()
    mock_llm.generate.return_value = json.dumps({
        "verdicts": [
            {"claim_index": 0, "supported": True},
            {"claim_index": 1, "supported": True},
        ]
    })

    with patch("app_services.evaluation_runner.get_llm_client_for_stage", return_value=mock_llm):
        runner = EvaluationRunner(session=session, tenant_id=tenant_id, run_id=run_id)
        events = list(runner._run_faithfulness())

    event = events[0]
    assert event["total_claims"] == 2
    assert event["supported_claims"] == 2
    assert event["faithfulness_pct"] == 100
    assert mock_llm.generate.call_count == 1


def test_finalize_step_yields_complete_event_with_issue_counts():
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

    session = MagicMock()
    session.query.return_value.filter.return_value.all.return_value = [review1, review2]
    session.query.return_value.filter.return_value.one_or_none.return_value = None

    runner = EvaluationRunner(session=session, tenant_id=tenant_id, run_id=run_id)
    runner._grounding_pct = 75

    events = list(runner._run_finalize())

    assert len(events) == 1
    event = events[0]
    assert event["type"] == "evaluation.complete"
    assert event["sections_passed"] == 1
    assert event["sections_total"] == 2
    assert event["issues_by_type"]["unsupported"] == 1
    assert event["issues_by_type"]["missing_citation"] == 1
    session.flush.assert_called_once()
