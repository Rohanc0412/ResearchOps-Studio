from unittest.mock import MagicMock, patch

from nodes.outliner import _section_count_bounds, _collect_keywords, _generate_outline_with_llm


def test_section_count_bounds_no_sources_returns_5_8():
    assert _section_count_bounds([]) == (5, 8)


def test_section_count_bounds_few_sources_unchanged():
    sources = [object()] * 5
    assert _section_count_bounds(sources) == (4, 6)


def test_section_count_bounds_many_sources_unchanged():
    sources = [object()] * 15
    assert _section_count_bounds(sources) == (6, 10)


def test_collect_keywords_no_sources_uses_fallback_text():
    keywords = _collect_keywords([], limit=5, fallback_text="transformer models attention mechanism neural networks")
    assert len(keywords) > 0
    all_words = " ".join(keywords).lower()
    assert any(w in all_words for w in ["transformer", "attention", "neural", "mechanism"])


def test_generate_outline_prompt_question_only_when_no_sources():
    mock_client = MagicMock()
    mock_client.generate.return_value = (
        '{"report_title": "Test", "step_labels": ["a","b","c","d","e","f"], "sections": ['
        '{"section_id": "intro", "title": "Introduction", "goal": "Set context", '
        '"key_points": ["a"], "suggested_evidence_themes": ["b"], "section_order": 1}]}'
    )
    result = _generate_outline_with_llm(
        user_query="What are transformer models?",
        vetted_sources=[],
        llm_client=mock_client,
        run_id="test-run",
    )

    prompt = mock_client.generate.call_args[0][0]
    assert "(no sources available)" not in prompt
    assert "What are transformer models?" in prompt
    assert result is not None
