from __future__ import annotations

import unittest.mock as mock

import pytest


def test_search_raises_when_key_missing(monkeypatch):
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)
    from search.tavily import SearchNotConfiguredError, search
    with pytest.raises(SearchNotConfiguredError):
        search("test query")


def test_search_returns_results(monkeypatch):
    monkeypatch.setenv("TAVILY_API_KEY", "test-key")
    fake_response = {
        "results": [
            {"title": "Result 1", "url": "https://example.com/1", "content": "Snippet 1"},
            {"title": "Result 2", "url": "https://example.com/2", "content": "Snippet 2"},
        ]
    }
    mock_resp = mock.MagicMock()
    mock_resp.json.return_value = fake_response
    mock_resp.raise_for_status.return_value = None

    with mock.patch("httpx.post", return_value=mock_resp) as mock_post:
        from search.tavily import search, SearchResult
        results = search("AI research")

    assert len(results) == 2
    assert results[0] == SearchResult(title="Result 1", url="https://example.com/1", snippet="Snippet 1")
    assert results[1] == SearchResult(title="Result 2", url="https://example.com/2", snippet="Snippet 2")
    mock_post.assert_called_once()
    call_kwargs = mock_post.call_args
    assert call_kwargs[1]["json"]["query"] == "AI research"
    assert call_kwargs[1]["json"]["api_key"] == "test-key"


def test_search_respects_max_results(monkeypatch):
    monkeypatch.setenv("TAVILY_API_KEY", "test-key")
    fake_response = {
        "results": [
            {"title": f"Result {i}", "url": f"https://example.com/{i}", "content": f"Snippet {i}"}
            for i in range(10)
        ]
    }
    mock_resp = mock.MagicMock()
    mock_resp.json.return_value = fake_response
    mock_resp.raise_for_status.return_value = None

    with mock.patch("httpx.post", return_value=mock_resp) as mock_post:
        from search.tavily import search
        results = search("query", max_results=3)

    assert len(results) == 3
    call_kwargs = mock_post.call_args
    assert call_kwargs[1]["json"]["max_results"] == 3
