"""
Academic source connectors for ResearchOps Studio.

Provides:
- Base connector interface with rate limiting
- Scientific Papers MCP connector for multi-source retrieval
- Deduplication with canonical ID priority
"""

from __future__ import annotations

from connectors.base import (
    BaseConnector,
    CanonicalIdentifier,
    ConnectorError,
    ConnectorProtocol,
    RateLimiter,
    RateLimitError,
    RetrievedSource,
    SourceType,
    TimeoutError,
)
from connectors.dedup import (
    DeduplicationStats,
    deduplicate_sources,
    filter_by_existing_ids,
)
from connectors.scientific_papers_mcp import ScientificPapersMCPConnector

__all__ = [
    # Base classes
    "BaseConnector",
    "ConnectorProtocol",
    "CanonicalIdentifier",
    "RetrievedSource",
    "SourceType",
    "RateLimiter",
    # Errors
    "ConnectorError",
    "RateLimitError",
    "TimeoutError",
    # Connectors
    "ScientificPapersMCPConnector",
    # Deduplication
    "deduplicate_sources",
    "filter_by_existing_ids",
    "DeduplicationStats",
]

