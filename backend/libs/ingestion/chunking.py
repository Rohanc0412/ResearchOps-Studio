"""
Stable text chunking with character offsets.

This module provides:
- Deterministic chunking (same input = same chunks)
- Character offset tracking for snippet localization
- Configurable chunk size and overlap
- Token-aware chunking (approximate)
"""

from __future__ import annotations

import re
from typing import TypedDict


class Chunk(TypedDict):
    """A single text chunk with metadata."""

    text: str
    char_start: int
    char_end: int
    token_count: int


def _approximate_tokens(text: str) -> int:
    """Approximate token count using word count * 1.3 heuristic."""
    words = len(re.findall(r"\b\w+\b", text))
    return int(words * 1.3)


def chunk_text(
    text: str,
    max_chars: int = 1000,
    overlap_chars: int = 100,
) -> list[Chunk]:
    """
    Split text into overlapping chunks with stable character offsets.

    Chunking strategy:
    1. Split on paragraph boundaries when possible
    2. Fall back to sentence boundaries
    3. Fall back to a hard character limit
    4. Include overlap between chunks for context continuity
    """
    if not text:
        return []

    if len(text) <= max_chars:
        return [
            Chunk(
                text=text,
                char_start=0,
                char_end=len(text),
                token_count=_approximate_tokens(text),
            )
        ]

    chunks: list[Chunk] = []
    start = 0

    while start < len(text):
        end = min(start + max_chars, len(text))

        if end < len(text):
            search_start = start + int(max_chars * 0.8)
            search_region = text[search_start:end]
            para_break = search_region.rfind("\n\n")

            if para_break != -1:
                end = search_start + para_break + 2
            else:
                sentence_pattern = r"[.!?][\s\n]+"
                matches = list(re.finditer(sentence_pattern, text[search_start:end]))
                if matches:
                    end = search_start + matches[-1].end()

        chunk_value = text[start:end]
        chunks.append(
            Chunk(
                text=chunk_value,
                char_start=start,
                char_end=end,
                token_count=_approximate_tokens(chunk_value),
            )
        )

        if end < len(text):
            start = max(start + 1, end - overlap_chars)
        else:
            break

    return chunks
