from __future__ import annotations

import subprocess

import httpx
import pytest

from connectors import ScientificPapersMCPConnector
from connectors.base import ConnectorError, SourceType


def test_search_parses_cli_results(monkeypatch):
    calls: list[list[str]] = []

    def fake_run(args, **kwargs):
        calls.append(args)
        source = next(part.split("=", 1)[1] for part in args if part.startswith("--source="))
        stdout = (
            f'Found 1 papers from {source} for query "test query" in all field:\n\n'
            "🔍 1. Example Paper\n"
            "   ID: W123\n"
            "   Authors: Alice Smith, Bob Jones\n"
            "   Date: 2024-06-01\n"
            "   PDF: https://example.com/paper.pdf\n"
            "   📝 No text content available\n"
        )
        return subprocess.CompletedProcess(args=args, returncode=0, stdout=stdout, stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)

    connector = ScientificPapersMCPConnector(command="latest-science-mcp", sources=["openalex", "arxiv"])
    results = connector.search("test query", max_results=1)

    assert len(results) == 2
    assert [result.connector for result in results] == ["openalex", "arxiv"]
    assert results[0].canonical_id.openalex_id == "W123"
    assert results[0].year == 2024
    assert results[0].authors == ["Alice Smith", "Bob Jones"]
    assert results[0].source_type == SourceType.PAPER
    assert results[1].source_type == SourceType.PREPRINT
    assert calls[0][0] == "latest-science-mcp"
    assert "search-papers" in calls[0]


def test_get_by_id_infers_openalex(monkeypatch):
    def fake_run(args, **kwargs):
        stdout = (
            "Paper details from openalex:\n\n"
            "📄 Title: Sample Work\n"
            "🆔 ID: W2101234009\n"
            "👥 Authors: Jane Doe\n"
            "📅 Date: 2020-01-02\n"
            "   🔗 PDF: https://example.com/work.pdf\n"
        )
        return subprocess.CompletedProcess(args=args, returncode=0, stdout=stdout, stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)

    connector = ScientificPapersMCPConnector(command="latest-science-mcp", sources=["openalex"])
    result = connector.get_by_id("W2101234009")

    assert result is not None
    assert result.connector == "openalex"
    assert result.canonical_id.openalex_id == "W2101234009"
    assert result.url == "https://openalex.org/W2101234009"


def test_get_by_id_parses_full_text(monkeypatch):
    def fake_run(args, **kwargs):
        stdout = (
            "Paper details from arxiv:\n\n"
            "📄 Title: Sample Work\n"
            "🆔 ID: 2401.12345\n"
            "👥 Authors: Jane Doe\n"
            "📅 Date: 2024-01-02\n"
            "   🔗 PDF: https://example.com/work.pdf\n"
            "\n"
            "📝 Text Content (42 characters):\n"
            "First line of the paper.\n"
            "Second line of the paper.\n"
        )
        return subprocess.CompletedProcess(args=args, returncode=0, stdout=stdout, stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)

    connector = ScientificPapersMCPConnector(command="latest-science-mcp", sources=["arxiv"])
    result = connector.get_by_id("2401.12345")

    assert result is not None
    assert result.full_text is not None
    assert "First line of the paper." in result.full_text
    assert "Second line of the paper." in result.full_text


def test_get_by_id_falls_back_to_html_extraction(monkeypatch):
    def fake_run(args, **kwargs):
        stdout = (
            "Paper details from openalex:\n\n"
            "📄 Title: Sample Work\n"
            "🆔 ID: W2101234009\n"
            "👥 Authors: Jane Doe\n"
            "📅 Date: 2020-01-02\n"
            "   🔗 PDF: https://example.com/work.pdf\n"
        )
        return subprocess.CompletedProcess(args=args, returncode=0, stdout=stdout, stderr="")

    def fake_request(method, url, **kwargs):
        html = "<html><body><p>Paragraph one.</p><p>Paragraph two.</p></body></html>"
        return httpx.Response(200, text=html, headers={"content-type": "text/html"})

    monkeypatch.setattr(subprocess, "run", fake_run)

    connector = ScientificPapersMCPConnector(command="latest-science-mcp", sources=["openalex"])
    monkeypatch.setattr(connector, "_request_with_retry", fake_request)
    result = connector.get_by_id("W2101234009")

    assert result is not None
    assert result.full_text is not None
    assert "Paragraph one." in result.full_text
    assert "Paragraph two." in result.full_text


def test_get_by_id_falls_back_to_pdf_extraction(monkeypatch):
    def fake_run(args, **kwargs):
        stdout = (
            "Paper details from core:\n\n"
            "📄 Title: Sample Work\n"
            "🆔 ID: 123\n"
            "👥 Authors: Jane Doe\n"
            "📅 Date: 2020-01-02\n"
            "   🔗 PDF: https://example.com/work.pdf\n"
        )
        return subprocess.CompletedProcess(args=args, returncode=0, stdout=stdout, stderr="")

    class FakePage:
        def extract_text(self):
            return "PDF first page text."

    class FakePdf:
        pages = [FakePage()]

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    def fake_request(method, url, **kwargs):
        return httpx.Response(200, content=b"%PDF-1.4 fake", headers={"content-type": "application/pdf"})

    monkeypatch.setattr(subprocess, "run", fake_run)

    connector = ScientificPapersMCPConnector(command="latest-science-mcp", sources=["core"])
    monkeypatch.setattr(connector, "_request_with_retry", fake_request)
    monkeypatch.setattr("pdfplumber.open", lambda *_args, **_kwargs: FakePdf())
    result = connector.get_by_id("core:123")

    assert result is not None
    assert result.full_text == "PDF first page text."


def test_get_by_id_raises_on_cli_failure(monkeypatch):
    def fake_run(args, **kwargs):
        return subprocess.CompletedProcess(args=args, returncode=1, stdout="", stderr="boom")

    monkeypatch.setattr(subprocess, "run", fake_run)

    connector = ScientificPapersMCPConnector(command="latest-science-mcp", sources=["openalex"])

    with pytest.raises(ConnectorError, match="boom"):
        connector.get_by_id("W123")


def test_search_continues_when_one_source_fails(monkeypatch):
    def fake_run(args, **kwargs):
        source = next(part.split("=", 1)[1] for part in args if part.startswith("--source="))
        if source == "openalex":
            return subprocess.CompletedProcess(args=args, returncode=1, stdout="", stderr="boom")
        stdout = (
            f'Found 1 papers from {source} for query "test query" in all field:\n\n'
            "🔍 1. Example Paper\n"
            "   ID: 2401.12345\n"
            "   Authors: Alice Smith\n"
            "   Date: 2024-01-01\n"
            "   PDF: https://arxiv.org/pdf/2401.12345.pdf\n"
            "   📝 No text content available\n"
        )
        return subprocess.CompletedProcess(args=args, returncode=0, stdout=stdout, stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)

    connector = ScientificPapersMCPConnector(command="latest-science-mcp", sources=["openalex", "arxiv"])
    results = connector.search("test query", max_results=1)

    assert len(results) == 1
    assert results[0].connector == "arxiv"
