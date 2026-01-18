"""Unit tests for text chunking."""

from __future__ import annotations

import pytest

from researchops_ingestion.chunking import chunk_text, rechunk_with_size


class TestChunkText:
    """Test chunk_text function."""

    def test_empty_string(self):
        """Test chunking empty string."""
        chunks = chunk_text("")
        assert chunks == []

    def test_short_text_single_chunk(self):
        """Test that short text fits in single chunk."""
        text = "Hello world!"
        chunks = chunk_text(text, max_chars=100)
        assert len(chunks) == 1
        assert chunks[0]["text"] == text
        assert chunks[0]["char_start"] == 0
        assert chunks[0]["char_end"] == len(text)
        assert chunks[0]["token_count"] > 0

    def test_long_text_multiple_chunks(self):
        """Test that long text is split into multiple chunks."""
        text = "Hello. " * 100  # 700 characters
        chunks = chunk_text(text, max_chars=200, overlap_chars=20)
        assert len(chunks) > 1

    def test_chunk_offsets_are_sequential(self):
        """Test that chunk offsets progress sequentially."""
        text = "word " * 500
        chunks = chunk_text(text, max_chars=300, overlap_chars=50)

        for i in range(len(chunks) - 1):
            # Each chunk should start at or after the previous one
            assert chunks[i + 1]["char_start"] >= chunks[i]["char_start"]
            # Overlap should exist
            assert chunks[i + 1]["char_start"] < chunks[i]["char_end"]

    def test_chunks_have_overlap(self):
        """Test that consecutive chunks have overlap."""
        text = "word " * 500
        chunks = chunk_text(text, max_chars=300, overlap_chars=50)

        for i in range(len(chunks) - 1):
            overlap_start = chunks[i + 1]["char_start"]
            overlap_end = chunks[i]["char_end"]
            overlap_size = overlap_end - overlap_start
            # Should have some overlap (allowing for boundary adjustments)
            assert overlap_size > 0

    def test_paragraph_boundary_splitting(self):
        """Test that chunking prefers paragraph boundaries."""
        text = "Paragraph one.\n\nParagraph two.\n\nParagraph three."
        chunks = chunk_text(text, max_chars=30, overlap_chars=5)

        # Should split at paragraph boundaries when possible
        # This is a heuristic test - exact behavior depends on lengths
        assert all("\n\n" not in chunk["text"][1:-1] or len(chunk["text"]) > 30 for chunk in chunks)

    def test_sentence_boundary_splitting(self):
        """Test that chunking prefers sentence boundaries."""
        text = "Sentence one. Sentence two. Sentence three. Sentence four."
        chunks = chunk_text(text, max_chars=30, overlap_chars=5)

        # Most chunks should end with sentence-ending punctuation
        # (when not hitting hard limit)
        for chunk in chunks[:-1]:  # Exclude last chunk
            # Should end with period or have hit max length
            assert chunk["text"].rstrip().endswith(".") or len(chunk["text"]) >= 25

    def test_token_count_approximation(self):
        """Test that token count is reasonable."""
        text = "hello world test example"
        chunks = chunk_text(text, max_chars=100)

        # 4 words should give ~5-6 tokens (words * 1.3)
        assert 4 <= chunks[0]["token_count"] <= 10

    def test_deterministic_chunking(self):
        """Test that same input produces same chunks."""
        text = "word " * 500
        chunks1 = chunk_text(text, max_chars=300, overlap_chars=50)
        chunks2 = chunk_text(text, max_chars=300, overlap_chars=50)

        assert len(chunks1) == len(chunks2)
        for c1, c2 in zip(chunks1, chunks2):
            assert c1["text"] == c2["text"]
            assert c1["char_start"] == c2["char_start"]
            assert c1["char_end"] == c2["char_end"]

    def test_no_missing_text(self):
        """Test that all text is covered by chunks."""
        text = "The quick brown fox jumps over the lazy dog. " * 50
        chunks = chunk_text(text, max_chars=200, overlap_chars=20)

        # First chunk should start at 0
        assert chunks[0]["char_start"] == 0

        # Last chunk should end at text length
        assert chunks[-1]["char_end"] == len(text)

        # No gaps between chunks (accounting for overlap)
        for i in range(len(chunks) - 1):
            # Next chunk should start before current chunk ends (overlap)
            assert chunks[i + 1]["char_start"] <= chunks[i]["char_end"]

    def test_unicode_handling(self):
        """Test chunking with Unicode characters."""
        text = "Hello 世界! " * 100
        chunks = chunk_text(text, max_chars=50, overlap_chars=10)

        # Should handle Unicode without crashing
        assert len(chunks) > 1
        # All chunks should contain valid text
        assert all(len(chunk["text"]) > 0 for chunk in chunks)

    def test_chunk_boundaries_respect_char_offsets(self):
        """Test that char_start and char_end correctly index into original text."""
        text = "ABCDEFGHIJKLMNOPQRSTUVWXYZ" * 20
        chunks = chunk_text(text, max_chars=100, overlap_chars=10)

        for chunk in chunks:
            # Extract using offsets should match chunk text
            extracted = text[chunk["char_start"] : chunk["char_end"]]
            assert extracted == chunk["text"]


class TestRechunkWithSize:
    """Test rechunk_with_size function."""

    def test_token_based_chunking(self):
        """Test chunking based on target token count."""
        text = "word " * 1000
        chunks = rechunk_with_size(text, target_tokens=100, overlap_tokens=10)

        # Most chunks should be roughly 100 tokens (allow some variance)
        for chunk in chunks:
            # Token count should be in reasonable range around target
            assert 50 <= chunk["token_count"] <= 200

    def test_empty_string(self):
        """Test rechunking empty string."""
        chunks = rechunk_with_size("")
        assert chunks == []

    def test_deterministic(self):
        """Test that rechunking is deterministic."""
        text = "word " * 500
        chunks1 = rechunk_with_size(text, target_tokens=100, overlap_tokens=10)
        chunks2 = rechunk_with_size(text, target_tokens=100, overlap_tokens=10)

        assert len(chunks1) == len(chunks2)
        for c1, c2 in zip(chunks1, chunks2):
            assert c1["text"] == c2["text"]
