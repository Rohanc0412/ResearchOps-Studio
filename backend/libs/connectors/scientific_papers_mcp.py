"""
Scientific Papers MCP connector for academic paper retrieval.

Uses the `latest-science-mcp` CLI from the Scientific-Papers-MCP project
to search across multiple academic sources and normalize the results into
the app's `RetrievedSource` model.
"""

from __future__ import annotations

import io
import os
import re
import shlex
import shutil
import subprocess
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Final

from connectors.base import (
    BaseConnector,
    CanonicalIdentifier,
    ConnectorError,
    RetrievedSource,
    SourceType,
)

SEARCHABLE_SOURCES: Final[tuple[str, ...]] = ("openalex", "arxiv", "europepmc", "core")
DEFAULT_COMMAND: Final[str] = "npx -y @futurelab-studio/latest-science-mcp@latest"


@dataclass(frozen=True)
class MCPPaperRecord:
    """Parsed paper result returned by the CLI."""

    source: str
    paper_id: str
    title: str
    authors: list[str]
    published_at: str | None
    pdf_url: str | None
    full_text: str | None = None


class ScientificPapersMCPConnector(BaseConnector):
    """Connector backed by the Scientific-Papers-MCP CLI."""

    def __init__(
        self,
        *,
        command: str | None = None,
        sources: list[str] | None = None,
        max_requests_per_second: float = 0.5,
        timeout_seconds: float = 60.0,
    ) -> None:
        super().__init__(
            max_requests_per_second=max_requests_per_second, timeout_seconds=timeout_seconds
        )
        self._command = (
            command or os.getenv("SCIENTIFIC_PAPERS_MCP_COMMAND") or DEFAULT_COMMAND
        ).strip()
        configured_sources = sources or self._load_sources_from_env()
        self.sources = [source for source in configured_sources if source in SEARCHABLE_SOURCES]
        if not self.sources:
            raise ValueError("ScientificPapersMCPConnector requires at least one searchable source")

    @property
    def name(self) -> str:
        return "scientific-papers-mcp"

    def search(
        self,
        query: str,
        max_results: int = 10,
        year_from: int | None = None,
        year_to: int | None = None,
    ) -> list[RetrievedSource]:
        if not query.strip():
            return []

        records: list[RetrievedSource] = []
        for source in self.sources:
            try:
                cli_output = self._run_search(source=source, query=query, max_results=max_results)
            except ConnectorError:
                continue
            parsed = self._parse_search_output(source=source, output=cli_output)
            for record in parsed:
                normalized = self._to_retrieved_source(record)
                if not self._matches_year_range(normalized.year, year_from, year_to):
                    continue
                records.append(normalized)
        return records

    def get_by_id(self, identifier: str) -> RetrievedSource | None:
        identifier = identifier.strip()
        if not identifier:
            return None

        source, raw_id = self._split_identifier(identifier)
        cli_output = self._run_fetch_content(source=source, paper_id=raw_id)
        parsed = self._parse_fetch_output(source=source, paper_id=raw_id, output=cli_output)
        if not parsed.full_text:
            parsed = self._enrich_record_with_fallback_text(parsed)
        return self._to_retrieved_source(parsed)

    def _load_sources_from_env(self) -> list[str]:
        raw = os.getenv("SCIENTIFIC_PAPERS_MCP_SOURCES", ",".join(SEARCHABLE_SOURCES))
        return [part.strip().lower() for part in raw.split(",") if part.strip()]

    def _run_search(self, *, source: str, query: str, max_results: int) -> str:
        self.rate_limiter.acquire()
        args = self._command_tokens() + [
            "search-papers",
            f"--source={source}",
            f"--query={query}",
            "--field=all",
            f"--count={max_results}",
        ]
        return self._run_command(args)

    def _run_fetch_content(self, *, source: str, paper_id: str) -> str:
        self.rate_limiter.acquire()
        args = self._command_tokens() + [
            "fetch-content",
            f"--source={source}",
            f"--id={paper_id}",
        ]
        return self._run_command(args)

    def _command_tokens(self) -> list[str]:
        tokens = shlex.split(self._command, posix=os.name != "nt")
        if not tokens:
            raise ConnectorError("Scientific-Papers-MCP command is empty")
        tokens[0] = self._resolve_executable(tokens[0])
        return tokens

    def _resolve_executable(self, executable: str) -> str:
        resolved = shutil.which(executable)
        if resolved:
            return resolved
        if os.name == "nt" and not executable.lower().endswith(".cmd"):
            resolved = shutil.which(f"{executable}.cmd")
            if resolved:
                return resolved
        return executable

    def _run_command(self, args: list[str]) -> str:
        try:
            completed = subprocess.run(
                args,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                check=False,
                timeout=self.timeout_seconds,
            )
        except subprocess.TimeoutExpired as exc:
            raise ConnectorError(f"Scientific-Papers-MCP command timed out: {' '.join(args)}") from exc

        if completed.returncode != 0:
            stderr = (completed.stderr or "").strip()
            stdout = (completed.stdout or "").strip()
            detail = stderr or stdout or f"exit code {completed.returncode}"
            raise ConnectorError(f"Scientific-Papers-MCP command failed: {detail}")

        return completed.stdout or ""

    def _parse_search_output(self, *, source: str, output: str) -> list[MCPPaperRecord]:
        body = self._strip_logs(output)
        records: list[MCPPaperRecord] = []
        blocks = re.findall(r"(?ms)^🔍\s+\d+\.\s+.*?(?=^🔍\s+\d+\.|\Z)", body)
        for block in blocks:
            title_match = re.search(r"^🔍\s+\d+\.\s+(?P<title>.+)$", block, flags=re.MULTILINE)
            id_match = re.search(r"^\s+ID:\s+(?P<id>.+)$", block, flags=re.MULTILINE)
            if not title_match or not id_match:
                continue
            authors_match = re.search(r"^\s+Authors:\s*(?P<authors>.*)$", block, flags=re.MULTILINE)
            date_match = re.search(r"^\s+Date:\s+(?P<date>.+)$", block, flags=re.MULTILINE)
            pdf_match = re.search(r"^\s+PDF:\s+(?P<pdf>\S+)$", block, flags=re.MULTILINE)

            authors = self._parse_authors(authors_match.group("authors") if authors_match else "")
            records.append(
                MCPPaperRecord(
                    source=source,
                    paper_id=id_match.group("id").strip(),
                    title=title_match.group("title").strip(),
                    authors=authors,
                    published_at=date_match.group("date").strip() if date_match else None,
                    pdf_url=pdf_match.group("pdf").strip() if pdf_match else None,
                )
            )
        return records

    def _parse_fetch_output(self, *, source: str, paper_id: str, output: str) -> MCPPaperRecord:
        body = self._strip_logs(output)
        title_match = re.search(r"^📄\s+Title:\s+(?P<title>.+)$", body, flags=re.MULTILINE)
        authors_match = re.search(r"^👥\s+Authors:\s*(?P<authors>.*)$", body, flags=re.MULTILINE)
        date_match = re.search(r"^📅\s+Date:\s+(?P<date>.+)$", body, flags=re.MULTILINE)
        pdf_match = re.search(r"^\s+🔗\s+PDF:\s+(?P<pdf>\S+)$", body, flags=re.MULTILINE)
        resolved_id = re.search(r"^🆔\s+ID:\s+(?P<id>.+)$", body, flags=re.MULTILINE)
        full_text = self._extract_full_text(body)

        title = title_match.group("title").strip() if title_match else paper_id
        return MCPPaperRecord(
            source=source,
            paper_id=resolved_id.group("id").strip() if resolved_id else paper_id,
            title=title,
            authors=self._parse_authors(authors_match.group("authors") if authors_match else ""),
            published_at=date_match.group("date").strip() if date_match else None,
            pdf_url=pdf_match.group("pdf").strip() if pdf_match else None,
            full_text=full_text,
        )

    def _strip_logs(self, output: str) -> str:
        lines = output.splitlines()
        start_index = 0
        for index, line in enumerate(lines):
            if line.startswith("Found ") or line.startswith("Paper details from "):
                start_index = index
                break
        return "\n".join(lines[start_index:]).strip()

    def _parse_authors(self, authors: str) -> list[str]:
        if not authors.strip():
            return []
        return [author.strip() for author in authors.split(",") if author.strip()]

    def _extract_full_text(self, body: str) -> str | None:
        match = re.search(
            r"(?ms)^.*?📝\s+Text Content(?:\s+\(\d+\s+characters\))?:\s*\n(?P<text>.+)$",
            body,
        )
        if not match:
            return None
        text = match.group("text").strip()
        return text or None

    def _enrich_record_with_fallback_text(self, record: MCPPaperRecord) -> MCPPaperRecord:
        full_text = self._extract_text_from_urls(record)
        if full_text:
            return MCPPaperRecord(
                source=record.source,
                paper_id=record.paper_id,
                title=record.title,
                authors=record.authors,
                published_at=record.published_at,
                pdf_url=record.pdf_url,
                full_text=full_text,
            )
        return record

    def _extract_text_from_urls(self, record: MCPPaperRecord) -> str | None:
        candidates: list[str] = []
        canonical_url = self._canonical_url_for(record)
        if canonical_url:
            candidates.append(canonical_url)
        if record.pdf_url and record.pdf_url not in candidates:
            candidates.append(record.pdf_url)

        for url in candidates:
            text = self._extract_text_from_url(url)
            if text:
                return text
        return None

    def _extract_text_from_url(self, url: str) -> str | None:
        if not url:
            return None
        try:
            response = self._request_with_retry(
                "GET",
                url,
                headers={"User-Agent": "ResearchOps-Studio/1.0"},
                follow_redirects=True,
            )
        except Exception:
            return None

        content_type = (response.headers.get("content-type") or "").lower()
        if "pdf" in content_type or url.lower().endswith(".pdf"):
            return self._extract_text_from_pdf_bytes(response.content)
        return self._extract_text_from_html(response.text)

    def _extract_text_from_html(self, html: str) -> str | None:
        if not html.strip():
            return None
        try:
            from bs4 import BeautifulSoup
        except Exception:
            return None

        soup = BeautifulSoup(html, "html.parser")
        for tag in soup(["script", "style", "noscript", "svg", "img"]):
            tag.decompose()

        paragraphs = [node.get_text(" ", strip=True) for node in soup.find_all(["p", "li"])]
        text = "\n\n".join(part for part in paragraphs if part)
        if not text:
            body = soup.body.get_text(" ", strip=True) if soup.body else soup.get_text(" ", strip=True)
            text = body
        return self._normalize_text(text)

    def _extract_text_from_pdf_bytes(self, pdf_bytes: bytes) -> str | None:
        if not pdf_bytes:
            return None
        try:
            import pdfplumber
        except Exception:
            return None

        pages: list[str] = []
        try:
            with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
                for page in pdf.pages:
                    text = page.extract_text() or ""
                    if text.strip():
                        pages.append(text)
        except Exception:
            return None
        return self._normalize_text("\n\n".join(pages))

    def _normalize_text(self, text: str | None) -> str | None:
        if not text:
            return None
        normalized = re.sub(r"\n{3,}", "\n\n", text)
        normalized = re.sub(r"[ \t]{2,}", " ", normalized)
        normalized = normalized.strip()
        if not normalized:
            return None
        max_chars = self._fallback_text_max_chars()
        if len(normalized) > max_chars:
            normalized = normalized[:max_chars].rstrip()
        return normalized

    def _fallback_text_max_chars(self) -> int:
        raw = os.getenv("SCIENTIFIC_PAPERS_MCP_FALLBACK_TEXT_MAX_CHARS", "200000")
        try:
            value = int(raw)
        except ValueError:
            value = 200000
        return max(1000, value)

    def _to_retrieved_source(self, record: MCPPaperRecord) -> RetrievedSource:
        year = self._extract_year(record.published_at)
        canonical_id = CanonicalIdentifier(url=self._canonical_url_for(record))
        normalized_id = record.paper_id

        if record.source == "arxiv" and normalized_id:
            canonical_id.arxiv_id = normalized_id
        elif record.source == "openalex" and normalized_id.upper().startswith("W"):
            canonical_id.openalex_id = normalized_id
        elif normalized_id.startswith("10."):
            canonical_id.doi = normalized_id

        return RetrievedSource(
            canonical_id=canonical_id,
            title=record.title,
            authors=record.authors,
            year=year,
            source_type=self._source_type_for(record.source),
            abstract=None,
            full_text=record.full_text,
            url=self._canonical_url_for(record),
            pdf_url=record.pdf_url,
            connector=record.source,
            retrieved_at=datetime.now(UTC),
            extra_metadata={
                "source": record.source,
                "source_id": record.paper_id,
                "published_at": record.published_at,
                "retrieval_backend": "scientific-papers-mcp",
            },
        )

    def _canonical_url_for(self, record: MCPPaperRecord) -> str | None:
        if record.source == "arxiv":
            return f"https://arxiv.org/abs/{record.paper_id}"
        if record.source == "openalex" and record.paper_id:
            return f"https://openalex.org/{record.paper_id}"
        return record.pdf_url

    def _extract_year(self, published_at: str | None) -> int | None:
        if not published_at:
            return None
        match = re.search(r"\b(19|20)\d{2}\b", published_at)
        return int(match.group(0)) if match else None

    def _matches_year_range(self, year: int | None, year_from: int | None, year_to: int | None) -> bool:
        if year is None:
            return True
        if year_from is not None and year < year_from:
            return False
        if year_to is not None and year > year_to:
            return False
        return True

    def _split_identifier(self, identifier: str) -> tuple[str, str]:
        if ":" in identifier:
            source, raw_id = identifier.split(":", 1)
            source = source.strip().lower()
            raw_id = raw_id.strip()
            if source in SEARCHABLE_SOURCES and raw_id:
                return source, raw_id
        if re.fullmatch(r"\d{4}\.\d{4,5}(v\d+)?", identifier):
            return "arxiv", identifier
        if identifier.upper().startswith("W"):
            return "openalex", identifier
        raise ConnectorError(
            "ScientificPapersMCPConnector.get_by_id requires a source-prefixed identifier or a known arXiv/OpenAlex id"
        )

    def _source_type_for(self, source: str) -> SourceType:
        if source == "arxiv":
            return SourceType.PREPRINT
        return SourceType.PAPER
