"""
Evidence ingestion pipeline for ResearchOps Studio.

Provides:
- Text sanitization with prompt injection defense
- Stable chunking with character offsets
- Embedding generation with pluggable providers
- Full ingestion orchestration
"""

from __future__ import annotations

from researchops_ingestion.chunking import Chunk, chunk_text, rechunk_with_size
from researchops_ingestion.embeddings import EmbeddingProvider, StubEmbeddingProvider
from researchops_ingestion.pipeline import (
    IngestionResult,
    create_or_get_source,
    create_snapshot,
    ingest_snapshot,
    ingest_source,
)
from researchops_ingestion.sanitize import SanitizationResult, sanitize_text

__all__ = [
    # Sanitization
    "sanitize_text",
    "SanitizationResult",
    # Chunking
    "chunk_text",
    "rechunk_with_size",
    "Chunk",
    # Embeddings
    "EmbeddingProvider",
    "StubEmbeddingProvider",
    # Pipeline
    "ingest_source",
    "ingest_snapshot",
    "create_or_get_source",
    "create_snapshot",
    "IngestionResult",
]

