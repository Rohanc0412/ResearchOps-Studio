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
    """Chunk text content."""

    char_start: int
    """Start position in original text (0-indexed)."""

    char_end: int
    """End position in original text (exclusive)."""

    token_count: int
    """Approximate token count (words * 1.3 heuristic)."""


def _approximate_tokens(text: str) -> int:
    """
    Approximate token count using word count * 1.3 heuristic.

    This is a conservative estimate:
    - "hello world" = 2 words → ~3 tokens
    - Most English text: 1 word ≈ 1.3 tokens

    For production, use tiktoken or similar for accurate counts.
    """
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
    1. Split on paragraph boundaries (double newlines) when possible
    2. Fall back to sentence boundaries
    3. Fall back to hard character limit
    4. Include overlap between chunks for context continuity

    Args:
        text: Sanitized text to chunk
        max_chars: Maximum characters per chunk (default 1000)
        overlap_chars: Characters to overlap between chunks (default 100)

    Returns:
        List of chunks with text, offsets, and token counts

    Example:
        >>> text = "Hello world. This is a test. " * 50
        >>> chunks = chunk_text(text, max_chars=100, overlap_chars=20)
        >>> len(chunks) > 1
        True
        >>> chunks[0]["char_start"]
        0
        >>> chunks[1]["char_start"] > chunks[0]["char_start"]
        True
    """
    if not text:
        return []

    if len(text) <= max_chars:
        # Text fits in single chunk
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
        # Calculate end position
        end = min(start + max_chars, len(text))

        # If this isn't the last chunk, try to break at a natural boundary
        if end < len(text):
            # Look for paragraph break (double newline) in last 20% of chunk
            search_start = start + int(max_chars * 0.8)
            search_region = text[search_start:end]
            para_break = search_region.rfind("\n\n")

            if para_break != -1:
                # Found paragraph break
                end = search_start + para_break + 2  # Include the newlines
            else:
                # Look for sentence break (period, question, exclamation + space/newline)
                sentence_pattern = r"[.!?][\s\n]+"
                matches = list(re.finditer(sentence_pattern, text[search_start:end]))
                if matches:
                    # Use the last sentence boundary found
                    last_match = matches[-1]
                    end = search_start + last_match.end()
                # Otherwise, use hard character limit

        # Extract chunk text
        chunk_text = text[start:end]

        # Create chunk
        chunks.append(
            Chunk(
                text=chunk_text,
                char_start=start,
                char_end=end,
                token_count=_approximate_tokens(chunk_text),
            )
        )

        # Move start position for next chunk (with overlap)
        if end < len(text):
            start = max(start + 1, end - overlap_chars)
        else:
            break

    return chunks


def rechunk_with_size(
    text: str,
    target_tokens: int = 500,
    overlap_tokens: int = 50,
) -> list[Chunk]:
    """
    Chunk text targeting a specific token count (using word-based approximation).

    Args:
        text: Sanitized text to chunk
        target_tokens: Target tokens per chunk (default 500)
        overlap_tokens: Tokens to overlap between chunks (default 50)

    Returns:
        List of chunks targeting the specified token count

    Example:
        >>> text = "word " * 1000
        >>> chunks = rechunk_with_size(text, target_tokens=100, overlap_tokens=10)
        >>> all(50 <= c["token_count"] <= 150 for c in chunks)  # Allow some variance
        True
    """
    # Convert tokens to approximate characters (tokens * 0.77 ≈ words, words * 5 ≈ chars)
    # This gives us: tokens * 4 ≈ characters (conservative estimate)
    max_chars = int(target_tokens * 4)
    overlap_chars = int(overlap_tokens * 4)

    return chunk_text(text, max_chars=max_chars, overlap_chars=overlap_chars)
