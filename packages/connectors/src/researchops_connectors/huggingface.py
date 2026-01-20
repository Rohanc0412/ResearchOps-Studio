"""
Hugging Face connector for model and dataset retrieval.

API: https://huggingface.co/docs/hub/api
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


class HuggingFaceConnector(BaseConnector):
    """
    Connector for Hugging Face Hub models or datasets.

    Args:
        repo_type: "model", "dataset", or "space"
    """

    BASE_URL = "https://huggingface.co/api"

    def __init__(self, token: str | None = None, repo_type: str = "model", **kwargs):
        max_rps = 1.0
        super().__init__(max_requests_per_second=max_rps, **kwargs)
        self.token = token
        self.repo_type = repo_type
        self._headers = {"User-Agent": "ResearchOps"}
        if token:
            self._headers["Authorization"] = f"Bearer {token}"

    @property
    def name(self) -> str:
        return "huggingface"

    def search(
        self,
        query: str,
        max_results: int = 10,
        year_from: int | None = None,
        year_to: int | None = None,
    ) -> list[RetrievedSource]:
        """
        Search Hugging Face Hub for models/datasets.
        """
        endpoint = self._endpoint_for_repo_type()
        params: dict[str, str | int] = {
            "search": query,
            "limit": min(max_results, 50),
        }
        response = self._request_with_retry(
            "GET",
            f"{self.BASE_URL}/{endpoint}",
            params=params,
            headers=self._headers,
        )
        items = response.json() or []

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
        Get model/dataset by ID or URL.
        """
        repo_id = self._normalize_repo_id(identifier)
        endpoint = self._endpoint_for_repo_type()
        url = f"{self.BASE_URL}/{endpoint}/{repo_id}"
        try:
            response = self._request_with_retry("GET", url, headers=self._headers)
            return self._parse_repo(response.json())
        except ConnectorError:
            return None

    def _endpoint_for_repo_type(self) -> str:
        if self.repo_type == "dataset":
            return "datasets"
        if self.repo_type == "space":
            return "spaces"
        return "models"

    def _normalize_repo_id(self, identifier: str) -> str:
        repo_id = identifier.strip()
        if repo_id.startswith("http://") or repo_id.startswith("https://"):
            parsed = urlparse(repo_id)
            parts = [p for p in parsed.path.split("/") if p]
            if parts and parts[0] in {"models", "datasets", "spaces"}:
                parts = parts[1:]
            repo_id = "/".join(parts)
        return repo_id

    def _parse_repo(self, item: dict) -> RetrievedSource | None:
        try:
            repo_id = item.get("modelId") or item.get("id") or ""
            if not repo_id:
                return None

            url = self._url_for_repo(repo_id)
            title = item.get("cardData", {}).get("pretty_name") if isinstance(item.get("cardData"), dict) else None
            title = title or repo_id

            author = item.get("author")
            if not author and "/" in repo_id:
                author = repo_id.split("/")[0]
            authors = [author] if author else []

            last_modified = item.get("lastModified")
            year = int(last_modified[:4]) if isinstance(last_modified, str) and len(last_modified) >= 4 else None

            abstract = None
            if isinstance(item.get("cardData"), dict):
                abstract = item.get("cardData", {}).get("summary")
            abstract = abstract or item.get("description")

            tags = item.get("tags") or None
            likes = item.get("likes")
            downloads = item.get("downloads")

            return RetrievedSource(
                canonical_id=CanonicalIdentifier(url=url),
                title=title,
                authors=authors,
                year=year,
                source_type=self._source_type(),
                abstract=abstract,
                full_text=None,
                url=url,
                pdf_url=None,
                connector=self.name,
                retrieved_at=datetime.utcnow(),
                venue="Hugging Face",
                citations_count=likes if isinstance(likes, int) else None,
                keywords=tags,
                extra_metadata={
                    "downloads": downloads,
                    "likes": likes,
                    "pipeline_tag": item.get("pipeline_tag"),
                },
            )
        except Exception:
            return None

    def _url_for_repo(self, repo_id: str) -> str:
        if self.repo_type == "dataset":
            return f"https://huggingface.co/datasets/{repo_id}"
        if self.repo_type == "space":
            return f"https://huggingface.co/spaces/{repo_id}"
        return f"https://huggingface.co/{repo_id}"

    def _source_type(self) -> SourceType:
        if self.repo_type == "dataset":
            return SourceType.DATASET
        return SourceType.SOFTWARE
