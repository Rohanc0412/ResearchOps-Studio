"""
Academic source connectors for ResearchOps Studio.

Provides:
- Base connector interface with rate limiting
- OpenAlex connector (free, comprehensive)
- arXiv connector (preprints)
- Deduplication with canonical ID priority
"""

from __future__ import annotations

from connectors.arxiv import ArXivConnector
from connectors.base import (
    BaseConnector,
    CanonicalIdentifier,
    ConnectorError,
    ConnectorProtocol,
    RateLimitError,
    RateLimiter,
    RetrievedSource,
    SourceType,
    TimeoutError,
)
from connectors.dedup import (
    DeduplicationStats,
    deduplicate_sources,
    filter_by_existing_ids,
)
from connectors.openalex import OpenAlexConnector

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
    "OpenAlexConnector",
    "ArXivConnector",
    # Deduplication
    "deduplicate_sources",
    "filter_by_existing_ids",
    "DeduplicationStats",
]

