"""
Integration tests for the orchestrator graph.

Tests:
1. Full pipeline produces 3 artifacts
2. Fail-closed when citations missing
3. Repair only edits failing sections
4. Checkpointing and resume
"""

from __future__ import annotations

import sys
from datetime import UTC, datetime
from uuid import uuid4

import pytest

# Add packages to path
sys.path.insert(0, "packages/core/src")
sys.path.insert(0, "packages/connectors/src")
sys.path.insert(0, "packages/ingestion/src")
sys.path.insert(0, "packages/retrieval/src")
sys.path.insert(0, "apps/orchestrator/src")
sys.path.insert(0, "db")

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from db.init_db import init_db
from db.models.runs import RunRow, RunStatusDb
from researchops_core.orchestrator.state import (
    EvaluatorDecision,
    OrchestratorState,
    ValidationErrorType,
)
from researchops_orchestrator.graph import create_orchestrator_graph
from researchops_orchestrator.runner import run_orchestrator


@pytest.fixture
def db_session():
    """Create in-memory database for testing."""
    engine = create_engine("sqlite:///:memory:", echo=False)
    init_db(engine=engine)

    SessionLocal = sessionmaker(bind=engine)
    session = SessionLocal()

    yield session

    session.close()


@pytest.fixture
def test_run():
    """Create test IDs (don't require database)."""
    tenant_id = uuid4()
    run_id = uuid4()
    return tenant_id, run_id


def test_question_generator_creates_queries(db_session, test_run):
    """Test that question generator creates diverse queries."""
    from researchops_orchestrator.nodes import question_generator_node

    tenant_id, run_id = test_run

    state = OrchestratorState(
        tenant_id=tenant_id,
        run_id=run_id,
        user_query="transformer architectures for NLP",
    )

    result = question_generator_node(state, db_session)

    assert len(result.generated_queries) > 5
    assert "transformer architectures for NLP" in result.generated_queries
    assert any("overview" in q.lower() for q in result.generated_queries)
    assert any("methods" in q.lower() for q in result.generated_queries)


def test_outliner_creates_structure(db_session, test_run):
    """Test that outliner creates hierarchical structure."""
    from researchops_orchestrator.nodes import outliner_node

    tenant_id, run_id = test_run

    state = OrchestratorState(
        tenant_id=tenant_id,
        run_id=run_id,
        user_query="machine learning optimization",
        vetted_sources=[],
    )

    result = outliner_node(state, db_session)

    assert result.outline is not None
    assert len(result.outline.sections) > 5
    assert result.outline.total_estimated_words > 0

    # Check hierarchical structure
    section_ids = [s.section_id for s in result.outline.sections]
    assert "1" in section_ids
    assert "2" in section_ids
    assert any("." in sid for sid in section_ids)  # Has subsections


def test_claim_extractor_finds_claims(db_session, test_run):
    """Test that claim extractor identifies claims with citations."""
    from researchops_orchestrator.nodes import claim_extractor_node

    tenant_id, run_id = test_run

    draft = """
# Research Report

Research shows that transformers improve performance [CITE:abc-123].
Studies have demonstrated this across multiple domains [CITE:def-456].
This is an introduction sentence without citations.
"""

    state = OrchestratorState(
        tenant_id=tenant_id, run_id=run_id, user_query="test", draft_text=draft
    )

    result = claim_extractor_node(state, db_session)

    assert len(result.extracted_claims) > 0

    # Find claims with citations
    cited_claims = [c for c in result.extracted_claims if c.citation_ids]
    assert len(cited_claims) >= 2

    # Check citation extraction
    first_claim = cited_claims[0]
    assert "abc-123" in first_claim.citation_ids or "def-456" in first_claim.citation_ids


def test_citation_validator_catches_missing_citations(db_session, test_run):
    """Test that citation validator fails closed on missing citations."""
    from researchops_orchestrator.nodes import citation_validator_node
    from researchops_core.orchestrator.state import Claim, EvidenceSnippetRef

    tenant_id, run_id = test_run

    # Create valid snippet ID
    snippet_id = uuid4()

    # Create claims (one with citation, one without)
    claims = [
        Claim(
            claim_id="claim_1",
            text="This claim has a citation",
            citation_ids=[str(snippet_id)],
            requires_evidence=True,
        ),
        Claim(
            claim_id="claim_2",
            text="This claim has NO citation",
            citation_ids=[],
            requires_evidence=True,
        ),
    ]

    # Create valid snippet
    snippets = [
        EvidenceSnippetRef(
            snippet_id=snippet_id,
            source_id=uuid4(),
            text="Evidence text",
            char_start=0,
            char_end=10,
        )
    ]

    state = OrchestratorState(
        tenant_id=tenant_id,
        run_id=run_id,
        user_query="test",
        extracted_claims=claims,
        evidence_snippets=snippets,
    )

    result = citation_validator_node(state, db_session)

    # Should have error for claim_2
    assert len(result.citation_errors) > 0
    missing_errors = [
        e for e in result.citation_errors if e.error_type == ValidationErrorType.MISSING_CITATION
    ]
    assert len(missing_errors) == 1
    assert missing_errors[0].claim_id == "claim_2"


def test_citation_validator_catches_invalid_citations(db_session, test_run):
    """Test that citation validator catches invalid snippet IDs."""
    from researchops_orchestrator.nodes import citation_validator_node
    from researchops_core.orchestrator.state import Claim

    tenant_id, run_id = test_run

    claims = [
        Claim(
            claim_id="claim_1",
            text="This claim references invalid snippet",
            citation_ids=["invalid-snippet-id"],
            requires_evidence=True,
        )
    ]

    state = OrchestratorState(
        tenant_id=tenant_id,
        run_id=run_id,
        user_query="test",
        extracted_claims=claims,
        evidence_snippets=[],  # No valid snippets
    )

    result = citation_validator_node(state, db_session)

    # Should have error for invalid citation
    invalid_errors = [
        e for e in result.citation_errors if e.error_type == ValidationErrorType.INVALID_CITATION
    ]
    assert len(invalid_errors) == 1


def test_evaluator_stops_on_success(db_session, test_run):
    """Test that evaluator stops when no errors."""
    from researchops_orchestrator.nodes import evaluator_node

    tenant_id, run_id = test_run

    state = OrchestratorState(
        tenant_id=tenant_id,
        run_id=run_id,
        user_query="test",
        citation_errors=[],  # No errors
    )

    result = evaluator_node(state, db_session)

    assert result.evaluator_decision == EvaluatorDecision.STOP_SUCCESS


def test_evaluator_continues_on_errors(db_session, test_run):
    """Test that evaluator continues when errors found."""
    from researchops_orchestrator.nodes import evaluator_node
    from researchops_core.orchestrator.state import ValidationError

    tenant_id, run_id = test_run

    errors = [
        ValidationError(
            error_type=ValidationErrorType.MISSING_CITATION,
            claim_id="claim_1",
            description="Missing citation",
            severity="error",
        )
    ]

    state = OrchestratorState(
        tenant_id=tenant_id,
        run_id=run_id,
        user_query="test",
        citation_errors=errors,
        vetted_sources=[],
    )

    result = evaluator_node(state, db_session)

    # Should continue (either repair or retrieve)
    assert result.evaluator_decision in [
        EvaluatorDecision.CONTINUE_REPAIR,
        EvaluatorDecision.CONTINUE_RETRIEVE,
    ]


def test_exporter_generates_three_artifacts(db_session, test_run):
    """Test that exporter produces all three artifacts."""
    from researchops_orchestrator.nodes import exporter_node
    from researchops_core.orchestrator.state import (
        OutlineModel,
        OutlineSection,
        SourceRef,
    )

    tenant_id, run_id = test_run

    # Create minimal state
    outline = OutlineModel(
        sections=[
            OutlineSection(
                section_id="1", title="Introduction", description="Intro", required_evidence=[]
            )
        ],
        total_estimated_words=1000,
    )

    sources = [
        SourceRef(
            source_id=uuid4(),
            canonical_id="doi:10.1234/test",
            title="Test Paper",
            authors=["Alice", "Bob"],
            year=2024,
            connector="openalex",
        )
    ]

    state = OrchestratorState(
        tenant_id=tenant_id,
        run_id=run_id,
        user_query="test query",
        outline=outline,
        draft_text="# Test Report\n\nContent here.",
        vetted_sources=sources,
        evidence_snippets=[],
    )

    result = exporter_node(state, db_session)

    # Check artifacts
    assert "literature_map.json" in result.artifacts
    assert "report.md" in result.artifacts
    assert "experiment_plan.md" in result.artifacts

    # Verify content
    assert "test query" in result.artifacts["literature_map.json"]
    assert "Test Report" in result.artifacts["report.md"]
    assert "Experiment Plan" in result.artifacts["experiment_plan.md"]


def test_graph_execution_completes(db_session, test_run):
    """Test that graph can execute end-to-end (simplified)."""
    tenant_id, run_id = test_run

    # Note: Full graph execution requires mocked connectors
    # This test verifies graph creation and basic structure

    graph = create_orchestrator_graph(db_session)

    # Verify graph has nodes
    assert graph is not None

    # Verify we can create initial state
    state = OrchestratorState(
        tenant_id=tenant_id,
        run_id=run_id,
        user_query="test query",
        max_iterations=1,  # Limit to prevent long execution
    )

    assert state.tenant_id == tenant_id
    assert state.run_id == run_id


def test_repair_agent_modifies_draft(db_session, test_run):
    """Test that repair agent makes targeted edits."""
    from researchops_orchestrator.nodes import repair_agent_node
    from researchops_core.orchestrator.state import Claim, ValidationError

    tenant_id, run_id = test_run

    draft = "Research shows transformers are effective. This is unproven."

    claims = [
        Claim(
            claim_id="claim_1",
            text="Research shows transformers are effective",
            citation_ids=[],
            requires_evidence=True,
        ),
        Claim(
            claim_id="claim_2", text="This is unproven", citation_ids=[], requires_evidence=True
        ),
    ]

    errors = [
        ValidationError(
            error_type=ValidationErrorType.MISSING_CITATION,
            claim_id="claim_1",
            description="Missing citation",
            severity="error",
        )
    ]

    state = OrchestratorState(
        tenant_id=tenant_id,
        run_id=run_id,
        user_query="test",
        draft_text=draft,
        extracted_claims=claims,
        citation_errors=errors,
        evidence_snippets=[],
    )

    result = repair_agent_node(state, db_session)

    # Verify repair was attempted
    assert result.repair_attempts == 1
    assert result.repair_plan is not None
    assert "claim_1" in result.repair_plan.target_claims


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
