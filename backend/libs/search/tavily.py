from __future__ import annotations

import os
from dataclasses import dataclass

import httpx

TAVILY_API_URL = "https://api.tavily.com/search"


class SearchNotConfiguredError(RuntimeError):
    """Raised when TAVILY_API_KEY is not set."""


@dataclass
class SearchResult:
    title: str
    url: str
    snippet: str


def search(query: str, *, max_results: int = 5) -> list[SearchResult]:
    """Search the web via Tavily.

    Raises SearchNotConfiguredError if TAVILY_API_KEY is not set.
    Raises httpx.HTTPStatusError on non-2xx responses.
    """
    api_key = os.getenv("TAVILY_API_KEY", "").strip()
    if not api_key:
        raise SearchNotConfiguredError("TAVILY_API_KEY is not set")

    response = httpx.post(
        TAVILY_API_URL,
        json={"api_key": api_key, "query": query, "max_results": max_results},
        timeout=10.0,
    )
    response.raise_for_status()
    data = response.json()
    return [
        SearchResult(
            title=r.get("title", ""),
            url=r.get("url", ""),
            snippet=r.get("content", ""),
        )
        for r in data.get("results", [])[:max_results]
    ]
