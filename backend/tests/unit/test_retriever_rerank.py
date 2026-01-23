from __future__ import annotations

from datetime import datetime
from uuid import uuid4

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from db.init_db import init_db
from researchops_connectors.base import CanonicalIdentifier, RetrievedSource, SourceType
from researchops_orchestrator.nodes import retriever as retriever_module


@pytest.fixture
def session():
    engine = create_engine("sqlite:///:memory:", echo=False)
    init_db(engine=engine)
    SessionLocal = sessionmaker(bind=engine)
    session = SessionLocal()
    try:
        yield session
    finally:
        session.rollback()
        session.close()


def _make_source(*, doi: str, title: str, abstract: str | None) -> RetrievedSource:
    return RetrievedSource(
        canonical_id=CanonicalIdentifier(doi=doi),
        title=title,
        authors=["Test Author"],
        year=2024,
        source_type=SourceType.PAPER,
        abstract=abstract,
        full_text=None,
        url=None,
        pdf_url=None,
        connector="openalex",
        retrieved_at=datetime.utcnow(),
    )


def test_bm25_tokenize_filters_and_lowercases():
    tokens = retriever_module._bm25_tokenize("Hello, WORLD! AI 2024.")
    assert tokens == ["hello", "world", "2024"]


def test_bm25_scoring_orders_sources(session, monkeypatch):
    class StubEmbedClient:
        def __init__(self):
            self.model_name = "stub"

        def embed_texts(self, texts: list[str]) -> list[list[float]]:
            return [[1.0, 0.0, 0.0] for _ in texts]

    monkeypatch.setattr(retriever_module, "_get_embed_client", lambda _provider: StubEmbedClient())
    sources = [
        _make_source(
            doi="10.1000/1",
            title="Neural networks for vision",
            abstract="Deep learning approaches for image understanding.",
        ),
        _make_source(
            doi="10.1000/2",
            title="Quantum entanglement in physics",
            abstract="Qubits and entanglement experiments.",
        ),
    ]
    query_plan = [retriever_module.QueryPlan(intent="methods", query="neural network vision")]
    ranked = retriever_module._rank_sources(
        sources,
        query_plan,
        session=session,
        tenant_id=uuid4(),
        query_text="neural network vision",
        llm_provider="hosted",
        stats={},
    )
    assert ranked[0].source.title == "Neural networks for vision"
    assert ranked[0].intent == "methods"


def test_cosine_similarity_orders_correctly():
    same = retriever_module._cosine_similarity([1.0, 0.0], [1.0, 0.0])
    orthogonal = retriever_module._cosine_similarity([1.0, 0.0], [0.0, 1.0])
    assert same > orthogonal


def test_embedding_cache_upsert_only_on_hash_change(session):
    tenant_id = uuid4()
    source = _make_source(doi="10.1000/3", title="Cache test", abstract="Embedding cache test.")
    text = retriever_module._embedding_text_for_source(source)
    text_hash = retriever_module._embedding_text_hash(text)
    canonical_id = source.to_canonical_string()

    embedding = [0.1, 0.2, 0.3]
    existing, updated = retriever_module._upsert_source_embedding(
        session,
        tenant_id=tenant_id,
        canonical_id=canonical_id,
        embedding_model="stub",
        embedding_vector=embedding,
        text_hash=text_hash,
        existing=None,
    )
    assert updated is True

    second_embedding = [0.9, 0.8, 0.7]
    existing_after, updated_after = retriever_module._upsert_source_embedding(
        session,
        tenant_id=tenant_id,
        canonical_id=canonical_id,
        embedding_model="stub",
        embedding_vector=second_embedding,
        text_hash=text_hash,
        existing=existing,
    )
    assert updated_after is False
    assert existing_after.embedding_json == embedding


def test_rerank_embeds_only_topk(session, monkeypatch):
    class StubEmbedClient:
        def __init__(self):
            self.model_name = "stub"
            self.calls: list[list[str]] = []

        def embed_texts(self, texts: list[str]) -> list[list[float]]:
            self.calls.append(list(texts))
            return [[1.0, 0.0, 0.0] for _ in texts]

    stub = StubEmbedClient()
    monkeypatch.setenv("RETRIEVER_RERANK_TOPK", "2")
    monkeypatch.setattr(retriever_module, "_get_embed_client", lambda _provider: stub)

    sources = [
        _make_source(doi=f"10.1000/{i}", title=f"Title {i}", abstract="Test abstract")
        for i in range(5)
    ]
    query_plan = [retriever_module.QueryPlan(intent="survey", query="test abstract")]
    retriever_module._rank_sources(
        sources,
        query_plan,
        session=session,
        tenant_id=uuid4(),
        query_text="test abstract",
        llm_provider="hosted",
        stats={},
    )
    assert len(stub.calls) == 2
    assert len(stub.calls[0]) == 1
    assert len(stub.calls[1]) == 2


def test_rerank_fallback_when_embedding_fails(session, monkeypatch):
    class FailingEmbedClient:
        def __init__(self):
            self.model_name = "stub"

        def embed_texts(self, texts: list[str]) -> list[list[float]]:
            raise retriever_module.EmbedError("boom")

    monkeypatch.setattr(retriever_module, "_get_embed_client", lambda _provider: FailingEmbedClient())

    sources = [
        _make_source(doi="10.1000/10", title="Fallback A", abstract="Alpha"),
        _make_source(doi="10.1000/11", title="Fallback B", abstract="Beta"),
    ]
    query_plan = [retriever_module.QueryPlan(intent="survey", query="alpha beta")]
    stats: dict[str, int | bool] = {}
    with pytest.raises(retriever_module.EmbedError):
        retriever_module._rank_sources(
            sources,
            query_plan,
            session=session,
            tenant_id=uuid4(),
            query_text="alpha beta",
            llm_provider="hosted",
            stats=stats,
        )
