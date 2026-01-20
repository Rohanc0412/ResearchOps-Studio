"""
arXiv connector for preprint retrieval.

arXiv is a free distribution service for scholarly articles.
API: https://arxiv.org/help/api/
Rate limit: 1 request per 3 seconds (recommended)
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from datetime import datetime
from urllib.parse import quote

from researchops_connectors.base import (
    BaseConnector,
    CanonicalIdentifier,
    ConnectorError,
    RetrievedSource,
    SourceType,
)


class ArXivConnector(BaseConnector):
    """
    Connector for arXiv API.

    Features:
    - Free, no API key required
    - Preprints before publication
    - Full text available
    - Math, physics, CS, biology coverage
    """

    BASE_URL = "https://export.arxiv.org/api/query"

    def __init__(self, **kwargs):
        """Initialize arXiv connector."""
        # Respect arXiv rate limit: 1 request per 3 seconds
        super().__init__(max_requests_per_second=0.3, **kwargs)

    @property
    def name(self) -> str:
        return "arxiv"

    def search(
        self,
        query: str,
        max_results: int = 10,
        year_from: int | None = None,
        year_to: int | None = None,
    ) -> list[RetrievedSource]:
        """
        Search arXiv for preprints matching query.

        Args:
            query: Search query string
            max_results: Maximum number of results
            year_from: Filter from this year
            year_to: Filter to this year

        Returns:
            List of retrieved sources
        """
        # Build query
        search_query = f"all:{quote(query)}"

        # Add year filters (arXiv uses submittedDate)
        if year_from or year_to:
            # Note: arXiv API doesn't support year filtering directly
            # We'll filter in post-processing
            pass

        url = f"{self.BASE_URL}?search_query={search_query}&max_results={max_results}&sortBy=relevance"

        # Make request
        response = self._request_with_retry("GET", url)

        # Parse Atom XML
        sources = self._parse_feed(response.text, year_from, year_to)

        return sources[:max_results]

    def get_by_id(self, identifier: str) -> RetrievedSource | None:
        """
        Get paper by arXiv ID.

        Args:
            identifier: arXiv ID (e.g., "2401.12345" or "arxiv:2401.12345")

        Returns:
            Retrieved source or None
        """
        # Clean arXiv ID
        arxiv_id = identifier.replace("arxiv:", "").strip()

        url = f"{self.BASE_URL}?id_list={arxiv_id}"

        try:
            response = self._request_with_retry("GET", url)
            sources = self._parse_feed(response.text)
            return sources[0] if sources else None
        except (ConnectorError, IndexError):
            return None

    def _parse_feed(
        self,
        xml_text: str,
        year_from: int | None = None,
        year_to: int | None = None,
    ) -> list[RetrievedSource]:
        """Parse arXiv Atom feed XML."""
        sources = []

        try:
            root = ET.fromstring(xml_text)

            # Namespace
            ns = {
                "atom": "http://www.w3.org/2005/Atom",
                "arxiv": "http://arxiv.org/schemas/atom",
            }

            # Parse each entry
            for entry in root.findall("atom:entry", ns):
                source = self._parse_entry(entry, ns)
                if source:
                    # Filter by year if specified
                    if year_from and source.year and source.year < year_from:
                        continue
                    if year_to and source.year and source.year > year_to:
                        continue
                    sources.append(source)

        except ET.ParseError:
            pass

        return sources

    def _parse_entry(self, entry: ET.Element, ns: dict) -> RetrievedSource | None:
        """Parse single arXiv entry."""
        try:
            # Title
            title_elem = entry.find("atom:title", ns)
            title = title_elem.text.strip() if title_elem is not None else None
            if not title:
                return None

            # arXiv ID
            id_elem = entry.find("atom:id", ns)
            arxiv_url = id_elem.text if id_elem is not None else None
            arxiv_id = arxiv_url.split("/")[-1] if arxiv_url else None

            # Authors
            authors = []
            for author in entry.findall("atom:author", ns):
                name_elem = author.find("atom:name", ns)
                if name_elem is not None:
                    authors.append(name_elem.text)

            # Abstract
            summary_elem = entry.find("atom:summary", ns)
            abstract = summary_elem.text.strip() if summary_elem is not None else None

            # Published date (year)
            published_elem = entry.find("atom:published", ns)
            year = None
            if published_elem is not None:
                pub_date = published_elem.text
                year = int(pub_date[:4])

            # PDF URL
            pdf_url = None
            for link in entry.findall("atom:link", ns):
                if link.get("title") == "pdf":
                    pdf_url = link.get("href")
                    break

            # Categories (for keywords)
            categories = []
            for cat in entry.findall("atom:category", ns):
                term = cat.get("term")
                if term:
                    categories.append(term)

            # DOI (if available)
            doi_elem = entry.find("arxiv:doi", ns)
            doi = doi_elem.text if doi_elem is not None else None

            return RetrievedSource(
                canonical_id=CanonicalIdentifier(
                    doi=doi,
                    arxiv_id=arxiv_id,
                ),
                title=title,
                authors=authors,
                year=year,
                source_type=SourceType.PREPRINT,
                abstract=abstract,
                full_text=None,  # Could fetch PDF, but not in this implementation
                url=arxiv_url,
                pdf_url=pdf_url,
                connector=self.name,
                retrieved_at=datetime.utcnow(),
                venue="arXiv",
                keywords=categories[:5],  # Top 5 categories
                extra_metadata={
                    "categories": categories,
                },
            )

        except Exception:
            return None
