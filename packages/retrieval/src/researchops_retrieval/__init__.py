"""
Placeholder retrieval interfaces (hybrid search + reranking).
"""

from __future__ import annotations


def retrieve(query: str) -> list[dict]:
    raise NotImplementedError("retrieval is a placeholder in Part 2")

