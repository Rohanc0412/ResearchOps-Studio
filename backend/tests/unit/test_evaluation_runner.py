from __future__ import annotations

import json
from unittest.mock import MagicMock, patch
from uuid import uuid4


def _make_session_with_drafts_and_snippets(tenant_id, run_id, section_id):
    """Returns a mock SQLAlchemy session pre-loaded with one draft section and one snippet."""
    session = MagicMock()

    # draft_sections query
    draft_row = MagicMock()
    draft_row.section_id = section_id
    draft_row.text = "The model achieved 95% accuracy on the test set."
    session.query.return_value.filter.return_value.all.return_value = [draft_row]

    # section_evidence / snippets join query
    snippet_row = MagicMock()
    snippet_row.id = uuid4()
    snippet_row.text = "Evaluation results show 95% accuracy on held-out test data."
    snippet_row.char_start = 0
    snippet_row.char_end = 60
    snippet_row.source_id = uuid4()
    session.query.return_value.join.return_value.join.return_value.filter.return_value.all.return_value = [snippet_row]

    # section_reviews query (for overwrite)
    session.query.return_value.filter.return_value.one_or_none.return_value = None

    # run_sections query (for titles)
    sec_row = MagicMock()
    sec_row.section_id = section_id
    sec_row.title = "Results"
    sec_row.section_order = 0
    session.query.return_value.filter.return_value.order_by.return_value.all.return_value = [sec_row]

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
