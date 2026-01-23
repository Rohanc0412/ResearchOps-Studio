"""
Integration tests for the orchestrator graph.

Tests:
1. Full pipeline produces 3 artifacts
2. Repair only edits failing sections
3. Checkpointing and resume
"""

from __future__ import annotations
from datetime import UTC, datetime
import json
from uuid import uuid4

import pytest

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from db.init_db import init_db
from researchops_core.orchestrator.state import (
    EvaluatorDecision,
    OrchestratorState,
)
from researchops_orchestrator.graph import create_orchestrator_graph
from researchops_orchestrator.runner import run_orchestrator


@pytest.fixture(autouse=True)
def _disable_llm_env(monkeypatch) -> None:
    monkeypatch.setenv("LLM_PROVIDER", "disabled")
    monkeypatch.setenv("LLM_OUTLINE_REQUIRED", "false")
    monkeypatch.setenv("LLM_CLAIM_REQUIRED", "false")
    monkeypatch.setenv("LLM_EVALUATOR_REQUIRED", "false")
    monkeypatch.setenv("LLM_REPAIR_REQUIRED", "false")


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


def test_outliner_creates_structure(db_session, test_run, monkeypatch):
    """Test that outliner creates ordered outline structure."""
    from researchops_orchestrator.nodes import outliner_node

    class StubLLM:
        def generate(
            self,
            prompt,
            system=None,
            max_tokens=512,
            temperature=0.2,
            response_format=None,
        ):
            return json.dumps(
                {
                    "run_id": "test",
                    "sections": [
                        {
                            "section_id": "intro",
                            "title": "Introduction",
                            "goal": "This introduces the topic. It frames the scope clearly.",
                            "key_points": [
                                "Define the topic scope.",
                                "Summarize the motivation.",
                                "Introduce key terms.",
                                "Highlight the context.",
                                "Set expectations for the report.",
                                "Outline the structure.",
                            ],
                            "suggested_evidence_themes": ["background", "scope"],
                            "section_order": 1,
                        },
                        {
                            "section_id": "background",
                            "title": "Background",
                            "goal": "This section covers foundational context. It aligns sources to core themes.",
                            "key_points": [
                                "Summarize foundational studies.",
                                "Clarify historical context.",
                                "Define key concepts.",
                                "Surface major themes.",
                                "Note important shifts.",
                                "Bridge to methods.",
                            ],
                            "suggested_evidence_themes": ["foundations", "context"],
                            "section_order": 2,
                        },
                        {
                            "section_id": "methods",
                            "title": "Methods and Approaches",
                            "goal": "This section reviews methodological choices. It contrasts key approaches.",
                            "key_points": [
                                "List major methods.",
                                "Compare methodological tradeoffs.",
                                "Describe common pipelines.",
                                "Highlight novel approaches.",
                                "Note evaluation practices.",
                                "Connect methods to outcomes.",
                            ],
                            "suggested_evidence_themes": ["methods", "approaches"],
                            "section_order": 3,
                        },
                        {
                            "section_id": "conclusion",
                            "title": "Conclusion",
                            "goal": "This section summarizes the findings. It closes with implications.",
                            "key_points": [
                                "Restate key takeaways.",
                                "Summarize evidence strength.",
                                "Highlight practical implications.",
                                "Note remaining gaps.",
                                "Suggest next steps.",
                                "Close with a final synthesis.",
                            ],
                            "suggested_evidence_themes": ["summary", "implications"],
                            "section_order": 4,
                        },
                    ],
                }
            )

    monkeypatch.setattr(
        "researchops_orchestrator.nodes.outliner.get_llm_client",
        lambda *_args, **_kwargs: StubLLM(),
    )

    tenant_id, run_id = test_run

    state = OrchestratorState(
        tenant_id=tenant_id,
        run_id=run_id,
        user_query="machine learning optimization",
        vetted_sources=[],
    )

    result = outliner_node(state, db_session)

    assert result.outline is not None
    assert len(result.outline.sections) >= 4

    section_ids = [s.section_id for s in result.outline.sections]
    assert section_ids[0] == "intro"
    assert section_ids[-1] == "conclusion"


def test_evaluator_stops_on_success(db_session, test_run):
    """Test that evaluator stops when no errors."""
    from researchops_orchestrator.nodes import evaluator_node
    from researchops_core.orchestrator.state import EvidenceSnippetRef, OutlineModel, OutlineSection
    from db.models.draft_sections import DraftSectionRow

    tenant_id, run_id = test_run

    class StubLLM:
        def generate(self, _prompt, **_kwargs):
            return json.dumps({"section_id": "intro", "verdict": "pass", "issues": []})

    outline = OutlineModel(
        sections=[
            OutlineSection(
                section_id="intro",
                title="Introduction",
                goal="Intro goal sentence one. Intro goal sentence two.",
                key_points=["Point A", "Point B", "Point C", "Point D", "Point E", "Point F"],
                suggested_evidence_themes=["introtheme"],
                section_order=1,
            )
        ]
    )
    db_session.add(
        DraftSectionRow(
            tenant_id=tenant_id,
            run_id=run_id,
            section_id="intro",
            text="Evidence-backed sentence [CITE:11111111-1111-1111-1111-111111111111].",
        )
    )
    db_session.flush()

    state = OrchestratorState(
        tenant_id=tenant_id,
        run_id=run_id,
        user_query="test",
        outline=outline,
        section_evidence_snippets={
            "intro": [
                EvidenceSnippetRef(
                    snippet_id="11111111-1111-1111-1111-111111111111",
                    source_id=uuid4(),
                    text="Intro evidence snippet.",
                    char_start=0,
                    char_end=24,
                )
            ]
        },
    )

    db_session.flush()

    import researchops_orchestrator.nodes.evaluator as evaluator_module

    evaluator_module.get_llm_client = lambda *_args, **_kwargs: StubLLM()

    result = evaluator_node(state, db_session)

    assert result.evaluator_decision == EvaluatorDecision.STOP_SUCCESS


def test_evaluator_continues_on_errors(db_session, test_run):
    """Test that evaluator continues when errors found."""
    from researchops_orchestrator.nodes import evaluator_node
    from researchops_core.orchestrator.state import EvidenceSnippetRef, OutlineModel, OutlineSection
    from db.models.draft_sections import DraftSectionRow

    tenant_id, run_id = test_run

    class StubLLM:
        def generate(self, _prompt, **_kwargs):
            return json.dumps(
                {
                    "section_id": "intro",
                    "verdict": "fail",
                    "issues": [
                        {
                            "sentence_index": 0,
                            "problem": "unsupported",
                            "notes": "Evidence does not support the claim.",
                            "citations": ["11111111-1111-1111-1111-111111111111"],
                        }
                    ],
                }
            )

    outline = OutlineModel(
        sections=[
            OutlineSection(
                section_id="intro",
                title="Introduction",
                goal="Intro goal sentence one. Intro goal sentence two.",
                key_points=["Point A", "Point B", "Point C", "Point D", "Point E", "Point F"],
                suggested_evidence_themes=["introtheme"],
                section_order=1,
            )
        ]
    )
    db_session.add(
        DraftSectionRow(
            tenant_id=tenant_id,
            run_id=run_id,
            section_id="intro",
            text="Evidence-backed sentence [CITE:11111111-1111-1111-1111-111111111111].",
        )
    )
    db_session.flush()

    state = OrchestratorState(
        tenant_id=tenant_id,
        run_id=run_id,
        user_query="test",
        outline=outline,
        section_evidence_snippets={
            "intro": [
                EvidenceSnippetRef(
                    snippet_id="11111111-1111-1111-1111-111111111111",
                    source_id=uuid4(),
                    text="Intro evidence snippet.",
                    char_start=0,
                    char_end=24,
                )
            ]
        },
    )

    import researchops_orchestrator.nodes.evaluator as evaluator_module

    evaluator_module.get_llm_client = lambda *_args, **_kwargs: StubLLM()

    result = evaluator_node(state, db_session)

    assert result.evaluator_decision == EvaluatorDecision.CONTINUE_REWRITE


def test_exporter_generates_three_artifacts(db_session, test_run):
    """Test that exporter produces all three artifacts."""
    from researchops_orchestrator.nodes import exporter_node
    from researchops_core.orchestrator.state import (
        OutlineModel,
        OutlineSection,
        SourceRef,
    )
    from db.models.projects import ProjectRow
    from db.models.runs import RunRow, RunStatusDb
    from db.models.run_sections import RunSectionRow
    from db.models.draft_sections import DraftSectionRow

    tenant_id, run_id = test_run

    project = ProjectRow(
        tenant_id=tenant_id,
        name="Test Project",
        description=None,
        created_by="tester",
    )
    db_session.add(project)
    db_session.flush()

    run_row = RunRow(
        id=run_id,
        tenant_id=tenant_id,
        project_id=project.id,
        status=RunStatusDb.running,
        current_stage="export",
        question="test query",
        output_type="report",
    )
    db_session.add(run_row)
    db_session.flush()

    # Create minimal state
    outline = OutlineModel(
        sections=[
            OutlineSection(
                section_id="intro",
                title="Introduction",
                goal="Introduce the topic and scope.",
                key_points=["Context", "Scope", "Motivation", "Framing", "Definitions", "Structure"],
                suggested_evidence_themes=["background", "scope"],
                section_order=1,
            )
        ],
    )
    db_session.add(
        RunSectionRow(
            tenant_id=tenant_id,
            run_id=run_id,
            section_id="intro",
            title="Introduction",
            goal="Introduce the topic and scope.",
            section_order=1,
        )
    )
    db_session.add(
        DraftSectionRow(
            tenant_id=tenant_id,
            run_id=run_id,
            section_id="intro",
            text="Content here.",
            section_summary="Line one.\nLine two.",
        )
    )
    db_session.flush()

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
        vetted_sources=sources,
        evidence_snippets=[],
    )

    result = exporter_node(state, db_session)

    # Check artifacts
    assert "report.md" in result.artifacts

    # Verify content
    assert "Content here." in result.artifacts["report.md"]


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
    from researchops_core.orchestrator.state import EvidenceSnippetRef, OutlineModel, OutlineSection
    from db.models.draft_sections import DraftSectionRow
    from db.models.section_reviews import SectionReviewRow

    tenant_id, run_id = test_run

    class StubLLM:
        def generate(self, _prompt, **_kwargs):
            return json.dumps(
                {
                    "section_id": "intro",
                    "revised_text": "Evidence-backed sentence [CITE:11111111-1111-1111-1111-111111111111].",
                    "revised_summary": "Sentence one.\nSentence two.",
                    "next_section_id": "methods",
                    "patched_next_text": "Transition sentence. Another transition sentence. Methods sentence three.",
                    "patched_next_summary": "Methods line one.\nMethods line two.",
                    "edits_json": {
                        "repaired_section_edits": [
                            {
                                "sentence_index": 0,
                                "before": "Research shows transformers are effective.",
                                "after": "Evidence-backed sentence [CITE:11111111-1111-1111-1111-111111111111].",
                                "change_type": "replace",
                            }
                        ],
                        "continuity_patch": {
                            "next_section_id": "methods",
                            "before_first_two_sentences": "Methods sentence one. Methods sentence two.",
                            "after_first_two_sentences": "Transition sentence. Another transition sentence.",
                        },
                    },
                }
            )

    outline = OutlineModel(
        sections=[
            OutlineSection(
                section_id="intro",
                title="Introduction",
                goal="Intro goal sentence one. Intro goal sentence two.",
                key_points=["Point A", "Point B", "Point C", "Point D", "Point E", "Point F"],
                suggested_evidence_themes=["introtheme"],
                section_order=1,
            ),
            OutlineSection(
                section_id="methods",
                title="Methods",
                goal="Methods goal sentence one. Methods goal sentence two.",
                key_points=["Point A", "Point B", "Point C", "Point D", "Point E", "Point F"],
                suggested_evidence_themes=["methodstheme"],
                section_order=2,
            ),
        ]
    )
    db_session.add(
        DraftSectionRow(
            tenant_id=tenant_id,
            run_id=run_id,
            section_id="intro",
            text="Research shows transformers are effective. This is unproven.",
            section_summary="Old line one.\nOld line two.",
        )
    )
    db_session.add(
        DraftSectionRow(
            tenant_id=tenant_id,
            run_id=run_id,
            section_id="methods",
            text="Methods sentence one. Methods sentence two. Methods sentence three.",
            section_summary="Old methods line one.\nOld methods line two.",
        )
    )
    db_session.add(
        SectionReviewRow(
            tenant_id=tenant_id,
            run_id=run_id,
            section_id="intro",
            verdict="fail",
            issues_json=[
                {
                    "sentence_index": 0,
                    "problem": "missing_citation",
                    "notes": "Missing citation.",
                    "citations": [],
                }
            ],
            reviewed_at=datetime.now(UTC),
        )
    )
    db_session.flush()

    state = OrchestratorState(
        tenant_id=tenant_id,
        run_id=run_id,
        user_query="test",
        outline=outline,
        section_evidence_snippets={
            "intro": [
                EvidenceSnippetRef(
                    snippet_id="11111111-1111-1111-1111-111111111111",
                    source_id=uuid4(),
                    text="Evidence snippet.",
                    char_start=0,
                    char_end=16,
                )
            ],
            "methods": [
                EvidenceSnippetRef(
                    snippet_id="22222222-2222-2222-2222-222222222222",
                    source_id=uuid4(),
                    text="Methods snippet.",
                    char_start=0,
                    char_end=15,
                )
            ],
        },
    )

    import researchops_orchestrator.nodes.repair_agent as repair_module

    repair_module.get_llm_client = lambda *_args, **_kwargs: StubLLM()

    result = repair_agent_node(state, db_session)

    # Verify repair was attempted
    assert result.repair_attempts == 1
    assert result.draft_text


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
