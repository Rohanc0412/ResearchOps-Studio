"""Integration tests for pgvector retrieval."""

from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from db.init_db import init_db
from researchops_ingestion import StubEmbeddingProvider, ingest_source
from researchops_retrieval import get_snippet_with_context, search_snippets


@pytest.fixture
def sqlite_engine():
    """Create a temporary SQLite database for testing."""
    engine = create_engine("sqlite:///:memory:", echo=False)
    init_db(engine=engine)
    return engine


@pytest.fixture
def session(sqlite_engine):
    """Create a test session."""
    SessionLocal = sessionmaker(bind=sqlite_engine)
    session = SessionLocal()
    try:
        yield session
    finally:
        session.rollback()
        session.close()


@pytest.fixture
def test_tenant_id():
    """Fixed tenant ID for tests."""
    return uuid4()


@pytest.fixture
def embedding_provider():
    """Stub embedding provider for tests."""
    return StubEmbeddingProvider()


@pytest.fixture
def ingested_data(session, test_tenant_id, embedding_provider):
    """Ingest some test data for retrieval tests."""
    results = []

    # Ingest multiple sources
    results.append(
        ingest_source(
            session=session,
            tenant_id=test_tenant_id,
            canonical_id="test:ml",
            source_type="paper",
            raw_content="Machine learning is a subset of artificial intelligence. "
            "It focuses on training algorithms to learn from data. "
            "Deep learning uses neural networks with multiple layers.",
            embedding_provider=embedding_provider,
            title="Machine Learning Basics",
            max_chunk_chars=100,
        )
    )

    results.append(
        ingest_source(
            session=session,
            tenant_id=test_tenant_id,
            canonical_id="test:python",
            source_type="webpage",
            raw_content="Python is a high-level programming language. "
            "It is widely used for data science and machine learning. "
            "Python has excellent libraries like NumPy and pandas.",
            embedding_provider=embedding_provider,
            title="Python Programming",
            max_chunk_chars=100,
        )
    )

    results.append(
        ingest_source(
            session=session,
            tenant_id=test_tenant_id,
            canonical_id="test:cooking",
            source_type="webpage",
            raw_content="Cooking is the art of preparing food. "
            "You can use various techniques like baking and frying. "
            "Fresh ingredients make better dishes.",
            embedding_provider=embedding_provider,
            title="Cooking Guide",
            max_chunk_chars=100,
        )
    )

    session.commit()
    return results


class TestSnippetSearch:
    """Test semantic search for snippets."""

    def test_search_returns_results(self, session, test_tenant_id, embedding_provider, ingested_data):
        """Test that search returns results."""
        # Search for "machine learning"
        query_embedding = embedding_provider.embed_texts(["machine learning"])[0]

        results = search_snippets(
            session=session,
            tenant_id=test_tenant_id,
            query_embedding=query_embedding,
            embedding_model=embedding_provider.model_name,
            limit=10,
        )

        # Should return some results
        assert len(results) > 0

    def test_search_respects_limit(self, session, test_tenant_id, embedding_provider, ingested_data):
        """Test that search respects limit parameter."""
        query_embedding = embedding_provider.embed_texts(["test"])[0]

        results = search_snippets(
            session=session,
            tenant_id=test_tenant_id,
            query_embedding=query_embedding,
            embedding_model=embedding_provider.model_name,
            limit=2,
        )

        # Should not return more than limit
        assert len(results) <= 2

    def test_search_results_have_metadata(self, session, test_tenant_id, embedding_provider, ingested_data):
        """Test that search results include source metadata."""
        query_embedding = embedding_provider.embed_texts(["machine learning"])[0]

        results = search_snippets(
            session=session,
            tenant_id=test_tenant_id,
            query_embedding=query_embedding,
            embedding_model=embedding_provider.model_name,
            limit=5,
        )

        # All results should have required fields
        for result in results:
            assert "snippet_id" in result
            assert "snippet_text" in result
            assert "similarity" in result
            assert "source_id" in result
            assert "source_title" in result
            assert "source_type" in result
            assert "snapshot_id" in result

    def test_search_similarity_scores(self, session, test_tenant_id, embedding_provider, ingested_data):
        """Test that similarity scores are in valid range."""
        query_embedding = embedding_provider.embed_texts(["python"])[0]

        results = search_snippets(
            session=session,
            tenant_id=test_tenant_id,
            query_embedding=query_embedding,
            embedding_model=embedding_provider.model_name,
            limit=10,
        )

        # Similarity scores should be in [0, 1]
        for result in results:
            assert 0.0 <= result["similarity"] <= 1.0

    def test_search_min_similarity_filter(self, session, test_tenant_id, embedding_provider, ingested_data):
        """Test that min_similarity parameter filters results."""
        query_embedding = embedding_provider.embed_texts(["machine learning"])[0]

        # Search with high min_similarity
        results = search_snippets(
            session=session,
            tenant_id=test_tenant_id,
            query_embedding=query_embedding,
            embedding_model=embedding_provider.model_name,
            limit=10,
            min_similarity=0.9,
        )

        # All results should meet threshold
        for result in results:
            assert result["similarity"] >= 0.9

    def test_search_multi_tenant_isolation(self, session, embedding_provider, ingested_data):
        """Test that search respects tenant isolation."""
        tenant1 = test_tenant_id = uuid4()
        tenant2 = uuid4()

        # Ingest for tenant1
        ingest_source(
            session=session,
            tenant_id=tenant1,
            canonical_id="tenant1:doc",
            source_type="test",
            raw_content="Tenant 1 content",
            embedding_provider=embedding_provider,
        )

        # Ingest for tenant2
        ingest_source(
            session=session,
            tenant_id=tenant2,
            canonical_id="tenant2:doc",
            source_type="test",
            raw_content="Tenant 2 content",
            embedding_provider=embedding_provider,
        )

        session.commit()

        # Search for tenant1
        query_embedding = embedding_provider.embed_texts(["content"])[0]
        results1 = search_snippets(
            session=session,
            tenant_id=tenant1,
            query_embedding=query_embedding,
            embedding_model=embedding_provider.model_name,
            limit=10,
        )

        # Search for tenant2
        results2 = search_snippets(
            session=session,
            tenant_id=tenant2,
            query_embedding=query_embedding,
            embedding_model=embedding_provider.model_name,
            limit=10,
        )

        # Results should not overlap
        snippet_ids1 = {r["snippet_id"] for r in results1}
        snippet_ids2 = {r["snippet_id"] for r in results2}
        assert snippet_ids1.isdisjoint(snippet_ids2)


class TestSnippetContext:
    """Test snippet context retrieval."""

    def test_get_snippet_with_context(self, session, test_tenant_id, embedding_provider):
        """Test retrieving snippet with surrounding context."""
        # Ingest content with multiple chunks
        result = ingest_source(
            session=session,
            tenant_id=test_tenant_id,
            canonical_id="test:context",
            source_type="test",
            raw_content="Chunk 1 text. " * 20 + "Chunk 2 text. " * 20 + "Chunk 3 text. " * 20,
            embedding_provider=embedding_provider,
            max_chunk_chars=200,
            overlap_chars=20,
        )

        session.commit()

        # Get middle snippet
        if len(result.snippets) >= 3:
            middle_snippet = result.snippets[1]

            context = get_snippet_with_context(
                session=session,
                tenant_id=test_tenant_id,
                snippet_id=middle_snippet.id,
                context_snippets=1,
            )

            # Should have snippet, source, snapshot
            assert "snippet" in context
            assert "source" in context
            assert "snapshot" in context

            # Should have context before and after
            assert "context_before" in context
            assert "context_after" in context

            # Context should not be empty (we have 3+ snippets)
            assert len(context["context_before"]) > 0
            assert len(context["context_after"]) > 0

    def test_get_snippet_nonexistent(self, session, test_tenant_id):
        """Test that getting nonexistent snippet raises error."""
        fake_snippet_id = uuid4()

        with pytest.raises(ValueError, match="not found"):
            get_snippet_with_context(
                session=session,
                tenant_id=test_tenant_id,
                snippet_id=fake_snippet_id,
                context_snippets=1,
            )

    def test_get_snippet_context_tenant_isolation(self, session, embedding_provider):
        """Test that snippet context respects tenant isolation."""
        tenant1 = uuid4()
        tenant2 = uuid4()

        # Ingest for tenant1
        result1 = ingest_source(
            session=session,
            tenant_id=tenant1,
            canonical_id="test:t1",
            source_type="test",
            raw_content="Tenant 1 content",
            embedding_provider=embedding_provider,
        )

        session.commit()

        snippet_id = result1.snippets[0].id

        # Tenant 2 should not be able to access tenant 1's snippet
        with pytest.raises(ValueError, match="not found"):
            get_snippet_with_context(
                session=session,
                tenant_id=tenant2,
                snippet_id=snippet_id,
                context_snippets=1,
            )

    def test_snippet_context_includes_metadata(self, session, test_tenant_id, embedding_provider):
        """Test that context includes source and snapshot metadata."""
        result = ingest_source(
            session=session,
            tenant_id=test_tenant_id,
            canonical_id="test:meta",
            source_type="paper",
            raw_content="Test content",
            embedding_provider=embedding_provider,
            title="Test Title",
            authors=["Author 1"],
            year=2024,
        )

        session.commit()

        context = get_snippet_with_context(
            session=session,
            tenant_id=test_tenant_id,
            snippet_id=result.snippets[0].id,
            context_snippets=0,
        )

        # Source metadata should be included
        assert context["source"]["title"] == "Test Title"
        assert context["source"]["authors"] == ["Author 1"]
        assert context["source"]["year"] == 2024

        # Snapshot metadata should be included
        assert context["snapshot"]["version"] == 1
        assert "sha256" in context["snapshot"]
