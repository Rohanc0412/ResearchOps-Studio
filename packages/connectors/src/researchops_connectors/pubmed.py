"""
PubMed connector for biomedical literature retrieval.

API: https://eutils.ncbi.nlm.nih.gov/entrez/eutils/
Rate limit: 3 requests/second without API key (per NCBI guidelines).
"""

from __future__ import annotations

import re
from datetime import datetime

from researchops_connectors.base import (
    BaseConnector,
    CanonicalIdentifier,
    ConnectorError,
    RetrievedSource,
    SourceType,
)


class PubMedConnector(BaseConnector):
    """
    Connector for NCBI PubMed E-utilities.

    Features:
    - PubMed ID canonicalization
    - Optional DOI extraction via esummary
    """

    BASE_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"

    def __init__(self, email: str | None = None, api_key: str | None = None, tool: str = "researchops", **kwargs):
        """
        Initialize PubMed connector.

        Args:
            email: Optional email per NCBI requirements
            api_key: Optional API key for higher rate limit
            tool: Tool name for NCBI tracking
            **kwargs: Additional arguments for BaseConnector
        """
        max_rps = 10.0 if api_key else 3.0
        super().__init__(max_requests_per_second=max_rps, **kwargs)
        self.email = email
        self.api_key = api_key
        self.tool = tool

    @property
    def name(self) -> str:
        return "pubmed"

    def search(
        self,
        query: str,
        max_results: int = 10,
        year_from: int | None = None,
        year_to: int | None = None,
    ) -> list[RetrievedSource]:
        """
        Search PubMed for papers matching query.
        """
        term = query
        if year_from or year_to:
            start = year_from or 0
            end = year_to or 9999
            term = f"{query} AND ({start}:{end}[dp])"

        params: dict[str, str | int] = {
            "db": "pubmed",
            "term": term,
            "retmax": min(max_results, 200),
            "retmode": "json",
            "sort": "relevance",
            "tool": self.tool,
        }
        if self.email:
            params["email"] = self.email
        if self.api_key:
            params["api_key"] = self.api_key

        response = self._request_with_retry("GET", f"{self.BASE_URL}/esearch.fcgi", params=params)
        data = response.json()
        ids = data.get("esearchresult", {}).get("idlist", [])
        if not ids:
            return []

        return self._summarize(ids)

    def get_by_id(self, identifier: str) -> RetrievedSource | None:
        """
        Get paper by PubMed ID.
        """
        pmid = identifier.replace("pubmed:", "").strip()
        try:
            sources = self._summarize([pmid])
            return sources[0] if sources else None
        except ConnectorError:
            return None

    def _summarize(self, ids: list[str]) -> list[RetrievedSource]:
        params: dict[str, str | int] = {
            "db": "pubmed",
            "id": ",".join(ids),
            "retmode": "json",
            "tool": self.tool,
        }
        if self.email:
            params["email"] = self.email
        if self.api_key:
            params["api_key"] = self.api_key

        response = self._request_with_retry("GET", f"{self.BASE_URL}/esummary.fcgi", params=params)
        data = response.json()
        result = data.get("result", {})

        sources: list[RetrievedSource] = []
        for uid in result.get("uids", []):
            doc = result.get(uid, {})
            source = self._parse_summary(uid, doc)
            if source:
                sources.append(source)
        return sources

    def _parse_summary(self, uid: str, doc: dict) -> RetrievedSource | None:
        try:
            title = doc.get("title", "").strip().rstrip(".")
            if not title:
                return None

            authors = [a.get("name") for a in doc.get("authors", []) if a.get("name")]
            year = self._parse_year(doc.get("pubdate", ""))
            venue = doc.get("fulljournalname") or doc.get("source")
            url = f"https://pubmed.ncbi.nlm.nih.gov/{uid}/"

            doi = None
            for aid in doc.get("articleids", []) or []:
                if aid.get("idtype") == "doi":
                    doi = aid.get("value")
                    break

            citations_count = doc.get("pmcrefcount")
            if isinstance(citations_count, str) and citations_count.isdigit():
                citations_count = int(citations_count)

            return RetrievedSource(
                canonical_id=CanonicalIdentifier(
                    doi=doi,
                    pubmed_id=uid,
                    url=url,
                ),
                title=title,
                authors=authors,
                year=year,
                source_type=SourceType.PAPER,
                abstract=None,
                full_text=None,
                url=url,
                pdf_url=None,
                connector=self.name,
                retrieved_at=datetime.utcnow(),
                venue=venue,
                citations_count=citations_count if isinstance(citations_count, int) else None,
                keywords=None,
                extra_metadata={"pubmed_summary": doc},
            )
        except Exception:
            return None

    def _parse_year(self, pubdate: str) -> int | None:
        match = re.search(r"(19|20)\\d{2}", pubdate or "")
        if match:
            return int(match.group(0))
        return None
