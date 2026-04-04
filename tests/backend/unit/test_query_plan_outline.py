from unittest.mock import MagicMock, patch

from core.orchestrator.state import OutlineModel, OutlineSection
from nodes.retriever import _normalize_intent, _build_query_plan_with_llm


def _make_outline(section_ids: list) -> OutlineModel:
    sections = [
        OutlineSection(
            section_id=sid,
            title=sid.replace("_", " ").title(),
            goal=f"Cover {sid} topics",
            key_points=["point a", "point b"],
            suggested_evidence_themes=["theme1", "theme2"],
            section_order=i + 1,
        )
        for i, sid in enumerate(section_ids)
    ]
    return OutlineModel(sections=sections)


def test_normalize_intent_section_prefix_passes_through():
    assert _normalize_intent("section:intro") == "section:intro"
    assert _normalize_intent("section:methods") == "section:methods"
    assert _normalize_intent("section:background_and_context") == "section:background and context"


def test_normalize_intent_existing_intents_unchanged():
    assert _normalize_intent("survey") == "survey"
    assert _normalize_intent("methods") == "methods"
    assert _normalize_intent("failure mode") == "failure modes"


def test_normalize_intent_unknown_returns_none():
    assert _normalize_intent("garbage") is None
    assert _normalize_intent("") is None


def test_build_query_plan_with_llm_includes_section_queries():
    outline = _make_outline(["intro", "methods", "findings"])
    response = (
        '{"queries": ['
        '{"intent": "survey", "query": "broad overview query"},'
        '{"intent": "methods", "query": "methods query"},'
        '{"intent": "section:intro", "query": "intro targeted query"},'
        '{"intent": "section:methods", "query": "methods section query"},'
        '{"intent": "section:findings", "query": "findings section query"}'
        "]}"
    )
    mock_client = MagicMock()
    mock_client.generate.return_value = response
    with patch("nodes.retriever.get_llm_client_for_stage", return_value=mock_client):
        plans = _build_query_plan_with_llm(
            question="What are recent advances in transformers?",
            max_queries=4,
            llm_provider="openai",
            llm_model="gpt-4o",
            outline=outline,
        )

    intents = [p.intent for p in plans]
    assert "survey" in intents
    assert "section:intro" in intents
    assert "section:methods" in intents
    assert "section:findings" in intents


def test_build_query_plan_with_llm_prompt_contains_section_info():
    outline = _make_outline(["intro", "conclusion"])
    mock_client = MagicMock()
    mock_client.generate.return_value = '{"queries": [{"intent": "survey", "query": "q"}]}'
    with patch("nodes.retriever.get_llm_client_for_stage", return_value=mock_client):
        _build_query_plan_with_llm(
            question="Test question",
            max_queries=4,
            llm_provider="openai",
            llm_model="gpt-4o",
            outline=outline,
        )

    prompt = mock_client.generate.call_args[0][0]
    assert "section:intro" in prompt
    assert "section:conclusion" in prompt
    assert "Cover intro topics" in prompt


def test_build_query_plan_with_llm_no_outline_uses_question_only_prompt():
    mock_client = MagicMock()
    mock_client.generate.return_value = '{"queries": [{"intent": "survey", "query": "q"}]}'
    with patch("nodes.retriever.get_llm_client_for_stage", return_value=mock_client):
        _build_query_plan_with_llm(
            question="Test question",
            max_queries=4,
            llm_provider="openai",
            llm_model="gpt-4o",
            outline=None,
        )

    prompt = mock_client.generate.call_args[0][0]
    assert "section:" not in prompt
