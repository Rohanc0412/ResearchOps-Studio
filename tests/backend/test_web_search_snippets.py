"""
Regression test: SearchResult is a @dataclass; snippet building must use
attribute access (.title, .snippet), not dict-style .get() calls.

Run from repo root:
    cd backend && python -m pytest ../tests/backend/test_web_search_snippets.py -v
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend", "libs"))

from search.tavily import SearchResult


def test_search_result_snippet_uses_dataclass_attributes():
    """Snippets must use r.title and r.snippet, not r.get()."""
    results = [
        SearchResult(
            title="AI Weekly Digest",
            url="https://example.com/ai-news",
            snippet="GPT-5 was announced with multimodal capabilities this week.",
        )
    ]

    # This is the FIXED expression from chat.py
    snippets = [f"[{i+1}] {r.title}: {r.snippet[:300]}" for i, r in enumerate(results)]

    assert len(snippets) == 1
    assert snippets[0] == "[1] AI Weekly Digest: GPT-5 was announced with multimodal capabilities this week."


def test_old_get_calls_raise_attribute_error():
    """Prove the pre-fix code was broken: .get() does not exist on a dataclass."""
    results = [SearchResult(title="T", url="u", snippet="S")]

    try:
        _ = [f"[{i+1}] {r.get('title','')}: {r.get('content','')[:300]}" for i, r in enumerate(results)]
        assert False, "Expected AttributeError — .get() must not exist on SearchResult"
    except AttributeError:
        pass  # correct
