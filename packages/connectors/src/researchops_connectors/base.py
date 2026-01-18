"""
Base connector interface and shared utilities.

Provides:
- Abstract connector protocol
- Rate limiting
- Retry logic with exponential backoff
- Consistent output format
- Error handling
"""

from __future__ import annotations

import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol
from enum import Enum

import httpx


class SourceType(str, Enum):
    """Type of academic source."""

    PAPER = "paper"
    PREPRINT = "preprint"
    BOOK = "book"
    CHAPTER = "chapter"
    DATASET = "dataset"
    SOFTWARE = "software"
    WEBPAGE = "webpage"
    REPOSITORY = "repository"


@dataclass
class CanonicalIdentifier:
    """Canonical identifier with priority for deduplication."""

    doi: str | None = None
    pubmed_id: str | None = None
    arxiv_id: str | None = None
    openalex_id: str | None = None
    s2_id: str | None = None  # Semantic Scholar
    url: str | None = None

    def get_primary(self) -> tuple[str, str] | None:
        """
        Get primary identifier based on priority.

        Priority: DOI > PubMed > arXiv > OpenAlex/S2 > URL

        Returns:
            (id_type, id_value) or None
        """
        if self.doi:
            return ("doi", self.doi)
        if self.pubmed_id:
            return ("pubmed", self.pubmed_id)
        if self.arxiv_id:
            return ("arxiv", self.arxiv_id)
        if self.openalex_id:
            return ("openalex", self.openalex_id)
        if self.s2_id:
            return ("s2", self.s2_id)
        if self.url:
            return ("url", self.url)
        return None


@dataclass
class RetrievedSource:
    """Standardized format for retrieved sources."""

    # Core identifiers
    canonical_id: CanonicalIdentifier

    # Metadata
    title: str
    authors: list[str]
    year: int | None
    source_type: SourceType

    # Content
    abstract: str | None
    full_text: str | None

    # URLs and references
    url: str | None
    pdf_url: str | None

    # Connector metadata
    connector: str  # Name of connector that retrieved this
    retrieved_at: datetime

    # Additional metadata
    venue: str | None = None  # Journal, conference, etc.
    citations_count: int | None = None
    keywords: list[str] | None = None
    extra_metadata: dict[str, Any] | None = None

    def to_canonical_string(self) -> str:
        """
        Get canonical ID string for deduplication.

        Returns string like "doi:10.1234/abc" or "arxiv:2401.12345"
        """
        primary = self.canonical_id.get_primary()
        if primary:
            id_type, id_value = primary
            return f"{id_type}:{id_value}"
        # Fallback: use title hash if no IDs
        import hashlib
        title_hash = hashlib.md5(self.title.encode()).hexdigest()[:12]
        return f"title_hash:{title_hash}"


class RateLimiter:
    """
    Simple rate limiter with sliding window.

    Ensures we don't exceed API rate limits.
    """

    def __init__(self, max_requests: int, window_seconds: float):
        """
        Initialize rate limiter.

        Args:
            max_requests: Maximum requests allowed in window
            window_seconds: Time window in seconds
        """
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self.requests: list[float] = []

    def acquire(self) -> None:
        """Wait until we can make another request."""
        now = time.time()

        # Remove requests outside the window
        cutoff = now - self.window_seconds
        self.requests = [t for t in self.requests if t > cutoff]

        # If at limit, wait
        if len(self.requests) >= self.max_requests:
            oldest = self.requests[0]
            sleep_time = self.window_seconds - (now - oldest) + 0.1
            if sleep_time > 0:
                time.sleep(sleep_time)
            # Retry acquire
            return self.acquire()

        # Record this request
        self.requests.append(now)


class ConnectorError(Exception):
    """Base exception for connector errors."""

    pass


class RateLimitError(ConnectorError):
    """Raised when rate limit is exceeded."""

    pass


class TimeoutError(ConnectorError):
    """Raised when request times out."""

    pass


class ConnectorProtocol(Protocol):
    """Protocol that all connectors must implement."""

    @property
    def name(self) -> str:
        """Connector name."""
        ...

    @property
    def rate_limiter(self) -> RateLimiter:
        """Rate limiter for this connector."""
        ...

    def search(
        self,
        query: str,
        max_results: int = 10,
        year_from: int | None = None,
        year_to: int | None = None,
    ) -> list[RetrievedSource]:
        """
        Search for sources matching query.

        Args:
            query: Search query string
            max_results: Maximum number of results to return
            year_from: Filter results from this year onwards
            year_to: Filter results up to this year

        Returns:
            List of retrieved sources
        """
        ...

    def get_by_id(self, identifier: str) -> RetrievedSource | None:
        """
        Retrieve source by identifier.

        Args:
            identifier: Source identifier (DOI, arXiv ID, etc.)

        Returns:
            Retrieved source or None if not found
        """
        ...


class BaseConnector(ABC):
    """
    Base class for all connectors.

    Provides:
    - Rate limiting
    - Retry logic with exponential backoff
    - HTTP client with timeout
    - Error handling
    """

    def __init__(
        self,
        max_requests_per_second: float = 1.0,
        timeout_seconds: float = 30.0,
        max_retries: int = 3,
    ):
        """
        Initialize base connector.

        Args:
            max_requests_per_second: Rate limit (requests per second)
            timeout_seconds: Request timeout
            max_retries: Maximum number of retries on failure
        """
        self.rate_limiter = RateLimiter(
            max_requests=int(max_requests_per_second),
            window_seconds=1.0,
        )
        self.timeout_seconds = timeout_seconds
        self.max_retries = max_retries
        self.client = httpx.Client(timeout=timeout_seconds)

    @property
    @abstractmethod
    def name(self) -> str:
        """Connector name."""
        pass

    def _request_with_retry(
        self,
        method: str,
        url: str,
        **kwargs: Any,
    ) -> httpx.Response:
        """
        Make HTTP request with retry logic.

        Args:
            method: HTTP method (GET, POST, etc.)
            url: Request URL
            **kwargs: Additional arguments to pass to httpx

        Returns:
            Response object

        Raises:
            TimeoutError: If request times out
            RateLimitError: If rate limit is exceeded
            ConnectorError: For other errors
        """
        for attempt in range(self.max_retries):
            try:
                # Respect rate limit
                self.rate_limiter.acquire()

                # Make request
                response = self.client.request(method, url, **kwargs)

                # Check for rate limit response
                if response.status_code == 429:
                    retry_after = int(response.headers.get("Retry-After", 60))
                    if attempt < self.max_retries - 1:
                        time.sleep(retry_after)
                        continue
                    raise RateLimitError(f"Rate limit exceeded for {url}")

                # Raise for other HTTP errors
                response.raise_for_status()

                return response

            except httpx.TimeoutException as e:
                if attempt < self.max_retries - 1:
                    # Exponential backoff
                    sleep_time = 2 ** attempt
                    time.sleep(sleep_time)
                    continue
                raise TimeoutError(f"Request to {url} timed out") from e

            except httpx.HTTPStatusError as e:
                if attempt < self.max_retries - 1 and e.response.status_code >= 500:
                    # Retry server errors
                    sleep_time = 2 ** attempt
                    time.sleep(sleep_time)
                    continue
                raise ConnectorError(f"HTTP error {e.response.status_code}: {url}") from e

            except Exception as e:
                raise ConnectorError(f"Unexpected error fetching {url}: {e}") from e

        raise ConnectorError(f"Max retries exceeded for {url}")

    @abstractmethod
    def search(
        self,
        query: str,
        max_results: int = 10,
        year_from: int | None = None,
        year_to: int | None = None,
    ) -> list[RetrievedSource]:
        """Search for sources matching query."""
        pass

    @abstractmethod
    def get_by_id(self, identifier: str) -> RetrievedSource | None:
        """Retrieve source by identifier."""
        pass

    def __del__(self):
        """Clean up HTTP client."""
        if hasattr(self, "client"):
            self.client.close()
