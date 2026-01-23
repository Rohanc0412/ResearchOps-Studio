"""
Academic source connectors for ResearchOps Studio.

Provides:
- Base connector interface with rate limiting
- OpenAlex connector (free, comprehensive)
- arXiv connector (preprints)
- Deduplication with canonical ID priority
"""

from __future__ import annotations

from researchops_connectors.arxiv import ArXivConnector
from researchops_connectors.base import (
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
from researchops_connectors.dedup import (
    DeduplicationStats,
    deduplicate_sources,
    filter_by_existing_ids,
)
from researchops_connectors.openalex import OpenAlexConnector

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

