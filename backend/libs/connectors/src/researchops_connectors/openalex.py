"""
OpenAlex connector for academic paper retrieval.

OpenAlex is a free, open catalog of scholarly works.
API: https://docs.openalex.org/
Rate limit: 10 requests/second (polite pool)
"""

from __future__ import annotations

from datetime import datetime
from urllib.parse import quote

from researchops_connectors.base import (
    BaseConnector,
    CanonicalIdentifier,
    ConnectorError,
    RetrievedSource,
    SourceType,
)


class OpenAlexConnector(BaseConnector):
    """
    Connector for OpenAlex API.

    Features:
    - Free, no API key required
    - Comprehensive metadata
    - Fast response times
    - Good coverage of recent papers
    """

    BASE_URL = "https://api.openalex.org"

    def __init__(self, email: str | None = None, **kwargs):
        """
        Initialize OpenAlex connector.

        Args:
            email: Your email (for polite pool - 10 req/s vs 1 req/s)
            **kwargs: Additional arguments for BaseConnector
        """
        # Default: 10 req/s if email provided, 1 req/s otherwise
        max_rps = 9.0 if email else 0.9  # Slightly under limit for safety
        super().__init__(max_requests_per_second=max_rps, **kwargs)
        self.email = email

    @property
    def name(self) -> str:
        return "openalex"

    def search(
        self,
        query: str,
        max_results: int = 10,
        year_from: int | None = None,
        year_to: int | None = None,
    ) -> list[RetrievedSource]:
        """
        Search OpenAlex for papers matching query.

        Args:
            query: Search query string
            max_results: Maximum number of results
            year_from: Filter from this year
            year_to: Filter to this year

        Returns:
            List of retrieved sources
        """
        # Build search URL
        search_query = quote(query)
        url = f"{self.BASE_URL}/works?search={search_query}&per-page={min(max_results, 200)}"

        # Add year filters
        filters = []
        if year_from:
            filters.append(f"from_publication_date:{year_from}-01-01")
        if year_to:
            filters.append(f"to_publication_date:{year_to}-12-31")

        if filters:
            url += "&filter=" + ",".join(filters)

        # Add email for polite pool
        if self.email:
            url += f"&mailto={self.email}"

        # Make request
        response = self._request_with_retry("GET", url)
        data = response.json()

        # Parse results
        sources = []
        for work in data.get("results", []):
            source = self._parse_work(work)
            if source:
                sources.append(source)

        return sources[:max_results]

    def get_by_id(self, identifier: str) -> RetrievedSource | None:
        """
        Get work by OpenAlex ID or DOI.

        Args:
            identifier: OpenAlex ID (W123456) or DOI

        Returns:
            Retrieved source or None
        """
        # OpenAlex accepts both IDs and DOIs
        if identifier.startswith("W"):
            url = f"{self.BASE_URL}/works/{identifier}"
        elif identifier.startswith("10."):
            # DOI
            url = f"{self.BASE_URL}/works/doi:{identifier}"
        else:
            url = f"{self.BASE_URL}/works/{identifier}"

        if self.email:
            url += f"?mailto={self.email}"

        try:
            response = self._request_with_retry("GET", url)
            work = response.json()
            return self._parse_work(work)
        except ConnectorError:
            return None

    def _parse_work(self, work: dict) -> RetrievedSource | None:
        """Parse OpenAlex work JSON to RetrievedSource."""
        try:
            # Extract identifiers
            openalex_id = work.get("id", "").split("/")[-1] if work.get("id") else None
            doi = work.get("doi", "").replace("https://doi.org/", "") if work.get("doi") else None

            # Extract basic metadata
            title = work.get("title", "")
            if not title:
                return None

            # Authors
            authorships = work.get("authorships", [])
            authors = []
            for authorship in authorships:
                author = authorship.get("author", {})
                display_name = author.get("display_name")
                if display_name:
                    authors.append(display_name)

            # Year
            pub_year = work.get("publication_year")

            # Abstract (inverted index format)
            abstract_inverted = work.get("abstract_inverted_index")
            abstract = None
            if abstract_inverted:
                abstract = self._reconstruct_abstract(abstract_inverted)

            # Source type
            work_type = work.get("type", "").lower()
            source_type = self._map_work_type(work_type)

            # URLs
            url = work.get("id")  # OpenAlex URL
            pdf_url = work.get("open_access", {}).get("oa_url")

            # Venue
            venue = None
            host_venue = work.get("primary_location", {}).get("source", {})
            if host_venue:
                venue = host_venue.get("display_name")

            # Citations
            citations_count = work.get("cited_by_count")

            # Keywords (from concepts)
            keywords = []
            concepts = work.get("concepts", [])
            for concept in concepts[:5]:  # Top 5
                if concept.get("score", 0) > 0.3:
                    keywords.append(concept.get("display_name"))

            return RetrievedSource(
                canonical_id=CanonicalIdentifier(
                    doi=doi,
                    openalex_id=openalex_id,
                ),
                title=title,
                authors=authors,
                year=pub_year,
                source_type=source_type,
                abstract=abstract,
                full_text=None,  # OpenAlex doesn't provide full text
                url=url,
                pdf_url=pdf_url,
                connector=self.name,
                retrieved_at=datetime.utcnow(),
                venue=venue,
                citations_count=citations_count,
                keywords=keywords,
                extra_metadata={"openalex_work": work},
            )

        except Exception as e:
            # Skip malformed results
            return None

    def _reconstruct_abstract(self, inverted_index: dict) -> str:
        """
        Reconstruct abstract from inverted index format.

        OpenAlex stores abstracts as {"word": [positions]}.
        """
        if not inverted_index:
            return ""

        # Flatten to (position, word) pairs
        pairs = []
        for word, positions in inverted_index.items():
            for pos in positions:
                pairs.append((pos, word))

        # Sort by position and join
        pairs.sort(key=lambda x: x[0])
        return " ".join(word for _, word in pairs)

    def _map_work_type(self, work_type: str) -> SourceType:
        """Map OpenAlex work type to our SourceType."""
        mapping = {
            "article": SourceType.PAPER,
            "book-chapter": SourceType.CHAPTER,
            "book": SourceType.BOOK,
            "dataset": SourceType.DATASET,
            "preprint": SourceType.PREPRINT,
            "repository": SourceType.REPOSITORY,
        }
        return mapping.get(work_type, SourceType.PAPER)
