"""
Crossref connector for scholarly metadata retrieval.

API: https://api.crossref.org/
Rate limit: public, please be polite and include a mailto if possible.
"""

from __future__ import annotations

import re
from datetime import datetime
from urllib.parse import quote

from researchops_connectors.base import (
    BaseConnector,
    CanonicalIdentifier,
    ConnectorError,
    RetrievedSource,
    SourceType,
)


class CrossrefConnector(BaseConnector):
    """
    Connector for Crossref works API.

    Features:
    - DOI-first metadata
    - Strong coverage of published literature
    """

    BASE_URL = "https://api.crossref.org"

    def __init__(self, email: str | None = None, **kwargs):
        """
        Initialize Crossref connector.

        Args:
            email: Optional email for polite pool
            **kwargs: Additional arguments for BaseConnector
        """
        super().__init__(max_requests_per_second=1.0, **kwargs)
        self.email = email

    @property
    def name(self) -> str:
        return "crossref"

    def search(
        self,
        query: str,
        max_results: int = 10,
        year_from: int | None = None,
        year_to: int | None = None,
    ) -> list[RetrievedSource]:
        """
        Search Crossref for works matching query.
        """
        params: dict[str, str | int] = {
            "query": query,
            "rows": min(max_results, 100),
        }
        filters = []
        if year_from:
            filters.append(f"from-pub-date:{year_from}-01-01")
        if year_to:
            filters.append(f"until-pub-date:{year_to}-12-31")
        if filters:
            params["filter"] = ",".join(filters)
        if self.email:
            params["mailto"] = self.email

        headers = {"User-Agent": f"ResearchOps/0.1 ({self.email})"} if self.email else {}
        response = self._request_with_retry(
            "GET",
            f"{self.BASE_URL}/works",
            params=params,
            headers=headers,
        )
        data = response.json()

        items = data.get("message", {}).get("items", [])
        sources: list[RetrievedSource] = []
        for item in items:
            source = self._parse_work(item)
            if source:
                sources.append(source)

        return sources[:max_results]

    def get_by_id(self, identifier: str) -> RetrievedSource | None:
        """
        Get work by DOI.
        """
        doi = identifier.replace("doi:", "").strip()
        url = f"{self.BASE_URL}/works/{quote(doi)}"
        headers = {"User-Agent": f"ResearchOps/0.1 ({self.email})"} if self.email else {}
        try:
            response = self._request_with_retry("GET", url, headers=headers)
            item = response.json().get("message", {})
            return self._parse_work(item)
        except ConnectorError:
            return None

    def _parse_work(self, item: dict) -> RetrievedSource | None:
        """Parse Crossref work JSON to RetrievedSource."""
        try:
            titles = item.get("title") or []
            title = titles[0] if titles else ""
            if not title:
                return None

            doi = item.get("DOI")
            url = item.get("URL")

            authors = []
            for author in item.get("author", []) or []:
                given = author.get("given", "").strip()
                family = author.get("family", "").strip()
                name = " ".join([n for n in [given, family] if n])
                if name:
                    authors.append(name)

            year = self._extract_year(item)
            abstract = item.get("abstract")
            if abstract:
                abstract = re.sub(r"<[^>]+>", "", abstract).strip()

            venue = None
            container = item.get("container-title") or []
            if container:
                venue = container[0]

            citations_count = item.get("is-referenced-by-count")
            keywords = item.get("subject") or None

            source_type = self._map_work_type(item.get("type", ""))

            return RetrievedSource(
                canonical_id=CanonicalIdentifier(
                    doi=doi,
                    url=url,
                ),
                title=title,
                authors=authors,
                year=year,
                source_type=source_type,
                abstract=abstract,
                full_text=None,
                url=url,
                pdf_url=None,
                connector=self.name,
                retrieved_at=datetime.utcnow(),
                venue=venue,
                citations_count=citations_count,
                keywords=keywords,
                extra_metadata={"crossref": item},
            )
        except Exception:
            return None

    def _extract_year(self, item: dict) -> int | None:
        """Extract publication year from Crossref fields."""
        for key in ("issued", "published-print", "published-online", "created"):
            date_parts = item.get(key, {}).get("date-parts") if item.get(key) else None
            if date_parts and isinstance(date_parts, list) and date_parts[0]:
                year = date_parts[0][0]
                if isinstance(year, int):
                    return year
        return None

    def _map_work_type(self, work_type: str) -> SourceType:
        mapping = {
            "journal-article": SourceType.PAPER,
            "book": SourceType.BOOK,
            "book-chapter": SourceType.CHAPTER,
            "proceedings-article": SourceType.PAPER,
            "dataset": SourceType.DATASET,
            "report": SourceType.PAPER,
        }
        return mapping.get(work_type, SourceType.PAPER)
