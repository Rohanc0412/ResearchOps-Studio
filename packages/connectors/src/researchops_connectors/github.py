"""
GitHub connector for software repository retrieval.

API: https://api.github.com/
Rate limit: search API is limited; use token for higher limits.
"""

from __future__ import annotations

from datetime import datetime
from urllib.parse import urlparse

from researchops_connectors.base import (
    BaseConnector,
    CanonicalIdentifier,
    ConnectorError,
    RetrievedSource,
    SourceType,
)


class GitHubConnector(BaseConnector):
    """
    Connector for GitHub repository search.

    Features:
    - Repository metadata (stars, topics)
    - Source URLs for deduplication
    """

    BASE_URL = "https://api.github.com"

    def __init__(self, token: str | None = None, **kwargs):
        """
        Initialize GitHub connector.

        Args:
            token: Optional GitHub token for higher rate limits
            **kwargs: Additional arguments for BaseConnector
        """
        max_rps = 0.5 if token else 0.15
        super().__init__(max_requests_per_second=max_rps, **kwargs)
        self.token = token
        self._headers = {
            "Accept": "application/vnd.github+json",
            "User-Agent": "ResearchOps",
        }
        if token:
            self._headers["Authorization"] = f"Bearer {token}"

    @property
    def name(self) -> str:
        return "github"

    def search(
        self,
        query: str,
        max_results: int = 10,
        year_from: int | None = None,
        year_to: int | None = None,
    ) -> list[RetrievedSource]:
        """
        Search GitHub repositories by query.
        """
        search_query = f"{query} in:name,description,readme"
        params: dict[str, str | int] = {
            "q": search_query,
            "per_page": min(max_results, 50),
            "sort": "stars",
            "order": "desc",
        }

        response = self._request_with_retry(
            "GET",
            f"{self.BASE_URL}/search/repositories",
            params=params,
            headers=self._headers,
        )
        data = response.json()
        items = data.get("items", [])

        sources: list[RetrievedSource] = []
        for item in items:
            source = self._parse_repo(item)
            if source:
                if year_from and source.year and source.year < year_from:
                    continue
                if year_to and source.year and source.year > year_to:
                    continue
                sources.append(source)

        return sources[:max_results]

    def get_by_id(self, identifier: str) -> RetrievedSource | None:
        """
        Get repository by full name (owner/repo) or URL.
        """
        repo = identifier.strip()
        if repo.startswith("http://") or repo.startswith("https://"):
            parsed = urlparse(repo)
            parts = [p for p in parsed.path.split("/") if p]
            if len(parts) >= 2:
                repo = f"{parts[0]}/{parts[1]}"

        url = f"{self.BASE_URL}/repos/{repo}"
        try:
            response = self._request_with_retry("GET", url, headers=self._headers)
            return self._parse_repo(response.json())
        except ConnectorError:
            return None

    def _parse_repo(self, item: dict) -> RetrievedSource | None:
        try:
            full_name = item.get("full_name") or ""
            if not full_name:
                return None

            owner = item.get("owner") or {}
            owner_name = owner.get("login")
            authors = [owner_name] if owner_name else []

            created_at = item.get("created_at")
            year = int(created_at[:4]) if isinstance(created_at, str) and len(created_at) >= 4 else None

            url = item.get("html_url")
            description = item.get("description")
            topics = item.get("topics") or None

            stars = item.get("stargazers_count")
            forks = item.get("forks_count")
            language = item.get("language")
            license_name = (item.get("license") or {}).get("name")

            return RetrievedSource(
                canonical_id=CanonicalIdentifier(url=url),
                title=full_name,
                authors=authors,
                year=year,
                source_type=SourceType.REPOSITORY,
                abstract=description,
                full_text=None,
                url=url,
                pdf_url=None,
                connector=self.name,
                retrieved_at=datetime.utcnow(),
                venue="GitHub",
                citations_count=stars if isinstance(stars, int) else None,
                keywords=topics,
                extra_metadata={
                    "stars": stars,
                    "forks": forks,
                    "language": language,
                    "license": license_name,
                },
            )
        except Exception:
            return None
