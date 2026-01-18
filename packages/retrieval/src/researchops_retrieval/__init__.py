"""
pgvector-based semantic search for evidence snippets.

Provides:
- Cosine similarity search
- Multi-tenant safe queries
- Snippet context retrieval
"""

from __future__ import annotations

from researchops_retrieval.search import SearchResult, get_snippet_with_context, search_snippets

__all__ = [
    "search_snippets",
    "get_snippet_with_context",
    "SearchResult",
]

