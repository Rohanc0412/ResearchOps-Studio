from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from connectors.base import CanonicalIdentifier, RetrievedSource, SourceType
from core.orchestrator.state import OrchestratorState
from db.init_db import init_db
from db.models.projects import ProjectRow
from db.models.runs import RunRow, RunStatusDb
from db.models.snippet_embeddings import SnippetEmbeddingRow
from db.models.snippets import SnippetRow
from db.models.snapshots import SnapshotRow
from db.models.source_embeddings import SourceEmbeddingRow
import researchops_orchestrator.nodes.retriever as retriever_module


@pytest.fixture
def db_session():
    engine = create_engine("sqlite:///:memory:", echo=False)
    init_db(engine=engine)
    SessionLocal = sessionmaker(bind=engine)
    session = SessionLocal()
    try:
        yield session
    finally:
        session.rollback()
        session.close()


class StubEmbedClient:
    model_name = "stub-embed"
    dimensions = 4

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        vectors: list[list[float]] = []
        for text in texts:
            size = float(max(len(text), 1))
            vectors.append([size, size / 2.0, size / 3.0, 1.0])
        return vectors


def _make_source(
    *,
    connector: str,
    paper_id: str,
    title: str,
    full_text: str | None = None,
) -> RetrievedSource:
    canonical = CanonicalIdentifier(url=f"https://example.org/{paper_id}")
    if connector == "openalex":
        canonical.openalex_id = paper_id
    elif connector == "arxiv":
        canonical.arxiv_id = paper_id
        canonical.url = f"https://arxiv.org/abs/{paper_id}"

    return RetrievedSource(
        canonical_id=canonical,
        title=title,
        authors=["Alice Smith"],
        year=2024,
        source_type=SourceType.PAPER if connector != "arxiv" else SourceType.PREPRINT,
        abstract=None,
        full_text=full_text,
        url=canonical.url,
        pdf_url=f"https://example.org/{paper_id}.pdf",
        connector=connector,
        retrieved_at=datetime.now(UTC),
        extra_metadata={
            "source": connector,
            "source_id": paper_id,
            "published_at": "2024-01-01",
            "retrieval_backend": "scientific-papers-mcp",
        },
    )


def _insert_run(session):
    tenant_id = uuid4()
    project = ProjectRow(tenant_id=tenant_id, name="Test Project", description=None, created_by="tester")
    session.add(project)
    session.flush()
    run_id = uuid4()
    session.add(
        RunRow(
            id=run_id,
            tenant_id=tenant_id,
            project_id=project.id,
            status=RunStatusDb.running,
            current_stage="retrieve",
            question="retrieval augmented generation",
            output_type="report",
        )
    )
    session.commit()
    return tenant_id, project.id, run_id


def test_retriever_ingests_selected_papers(db_session, monkeypatch):
    tenant_id, project_id, run_id = _insert_run(db_session)
    search_source = _make_source(connector="openalex", paper_id="W123", title="Search Result")
    fetched_source = _make_source(
        connector="openalex",
        paper_id="W123",
        title="Fetched Result",
        full_text="Paragraph one. " * 120,
    )

    class FakeConnector:
        def __init__(self):
            self.sources = ["openalex"]

        def search(self, query: str, max_results: int):
            return [search_source]

        def get_by_id(self, identifier: str):
            assert identifier == "openalex:W123"
            return fetched_source

    monkeypatch.setattr(retriever_module, "ScientificPapersMCPConnector", FakeConnector)
    monkeypatch.setattr(
        retriever_module,
        "_build_query_plan",
        lambda **kwargs: ([retriever_module.QueryPlan(intent="survey", query="retrieval augmented generation")], False),
    )
    monkeypatch.setattr(retriever_module, "_get_embed_client", lambda llm_provider: StubEmbedClient())
    monkeypatch.setenv("RETRIEVER_MIN_SOURCES", "1")
    monkeypatch.setenv("RETRIEVER_MAX_SOURCES", "1")
    monkeypatch.setenv("RETRIEVER_MCP_MAX_PER_SOURCE", "1")

    state = OrchestratorState(
        tenant_id=tenant_id,
        run_id=run_id,
        project_id=project_id,
        user_query="retrieval augmented generation",
    )

    result = retriever_module.retriever_node(state, db_session)

    assert len(result.retrieved_sources) == 1
    assert db_session.query(SourceEmbeddingRow).count() == 1
    assert db_session.query(SnapshotRow).count() == 1
    assert db_session.query(SnippetRow).count() > 1
    assert db_session.query(SnippetEmbeddingRow).count() == db_session.query(SnippetRow).count()

    # Re-running with identical content should not create a second snapshot.
    result = retriever_module.retriever_node(state, db_session)
    assert len(result.retrieved_sources) == 1
    assert db_session.query(SnapshotRow).count() == 1


def test_retriever_continues_when_selected_ingestion_fails(db_session, monkeypatch):
    tenant_id, project_id, run_id = _insert_run(db_session)
    search_sources = [
        _make_source(connector="openalex", paper_id="W123", title="Good Search Result"),
        _make_source(connector="arxiv", paper_id="2401.12345", title="Bad Search Result"),
    ]

    class FakeConnector:
        def __init__(self):
            self.sources = ["openalex", "arxiv"]

        def search(self, query: str, max_results: int):
            return list(search_sources)

        def get_by_id(self, identifier: str):
            if identifier == "openalex:W123":
                return _make_source(
                    connector="openalex",
                    paper_id="W123",
                    title="Fetched Good Result",
                    full_text="Usable content. " * 90,
                )
            raise RuntimeError("fetch failed")

    monkeypatch.setattr(retriever_module, "ScientificPapersMCPConnector", FakeConnector)
    monkeypatch.setattr(
        retriever_module,
        "_build_query_plan",
        lambda **kwargs: ([retriever_module.QueryPlan(intent="survey", query="retrieval augmented generation")], False),
    )
    monkeypatch.setattr(retriever_module, "_get_embed_client", lambda llm_provider: StubEmbedClient())
    monkeypatch.setenv("RETRIEVER_MIN_SOURCES", "2")
    monkeypatch.setenv("RETRIEVER_MAX_SOURCES", "2")
    monkeypatch.setenv("RETRIEVER_MCP_MAX_PER_SOURCE", "2")

    state = OrchestratorState(
        tenant_id=tenant_id,
        run_id=run_id,
        project_id=project_id,
        user_query="retrieval augmented generation",
    )

    result = retriever_module.retriever_node(state, db_session)

    assert len(result.retrieved_sources) == 2
    assert db_session.query(SnapshotRow).count() == 2
    assert db_session.query(SnippetRow).count() > 0
