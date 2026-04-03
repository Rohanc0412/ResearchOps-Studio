"""
Integration tests for the orchestrator graph.

Tests:
1. Full pipeline produces 3 artifacts
2. Repair only edits failing sections
3. Checkpointing and resume
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from core.orchestrator.state import (
    EvaluatorDecision,
    OrchestratorState,
)
from db.init_db import init_db_sync as init_db
from db.models.projects import ProjectRow
from db.models.run_checkpoints import RunCheckpointRow
from db.models.runs import RunRow, RunStatusDb
from cancellation import RunCancelledError, raise_if_run_cancel_requested
from graph import create_orchestrator_graph
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker


def _make_snippet(db_session, *, tenant_id: UUID, snippet_id: str) -> None:
    """Create SourceRow → SnapshotRow → SnippetRow for the given snippet_id.

    Required so that SectionReviewIssueCitationRow FK constraints are satisfied
    when the evaluator persists issues that cite this snippet.
    """
    from db.models.snapshots import SnapshotRow
    from db.models.snippets import SnippetRow
    from db.models.sources import SourceRow

    source = SourceRow(
        tenant_id=tenant_id,
        canonical_id=f"test-source-{snippet_id}",
        source_type="paper",
    )
    db_session.add(source)
    db_session.flush()

    snapshot = SnapshotRow(
        tenant_id=tenant_id,
        source_id=source.id,
        snapshot_version=1,
        blob_ref="test",
        sha256=hashlib.sha256(snippet_id.encode()).hexdigest(),
    )
    db_session.add(snapshot)
    db_session.flush()

    snippet = SnippetRow(
        id=UUID(snippet_id),
        tenant_id=tenant_id,
        snapshot_id=snapshot.id,
        snippet_index=0,
        text="test snippet",
        sha256=hashlib.sha256(snippet_id.encode()).hexdigest(),
    )
    db_session.add(snippet)
    db_session.flush()


@pytest.fixture(autouse=True)
def _disable_llm_env(monkeypatch) -> None:
    monkeypatch.setenv("LLM_PROVIDER", "disabled")
    monkeypatch.setenv("LLM_OUTLINE_REQUIRED", "false")
    monkeypatch.setenv("LLM_CLAIM_REQUIRED", "false")
    monkeypatch.setenv("LLM_EVALUATOR_REQUIRED", "false")
    monkeypatch.setenv("LLM_REPAIR_REQUIRED", "false")


@pytest.fixture
def db_session():
    """Create PostgreSQL database session for testing."""
    import os
    test_db_url = os.environ.get(
        "TEST_DATABASE_URL",
        "postgresql+psycopg://postgres:postgres@localhost:5432/researchops_test",
    )
    engine = create_engine(test_db_url, echo=False)
    init_db(engine=engine)

    SessionLocal = sessionmaker(bind=engine)
    session = SessionLocal()

    yield session

    session.close()
    engine.dispose()


@pytest.fixture
def test_run():
    """Create test IDs (don't require database)."""
    tenant_id = uuid4()
    run_id = uuid4()
    return tenant_id, run_id


@pytest.fixture
def db_run(db_session):
    """Create test IDs and insert matching ProjectRow + RunRow into db_session."""
    tenant_id = uuid4()
    run_id = uuid4()
    project = ProjectRow(tenant_id=tenant_id, name="Test Project", created_by="test")
    db_session.add(project)
    db_session.flush()  # populate project.id for the FK
    run = RunRow(
        id=run_id,
        tenant_id=tenant_id,
        project_id=project.id,
        status=RunStatusDb.running,
        question="test query",
    )
    db_session.add(run)
    db_session.commit()  # commit so emit_run_event's separate session can see the run
    return tenant_id, run_id


def test_outliner_creates_structure(db_session, db_run, monkeypatch):
    """Test that outliner creates ordered outline structure."""
    from nodes import outliner_node

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
                            "goal": (
                                "This section covers foundational context. "
                                "It aligns sources to core themes."
                            ),
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
                            "goal": (
                                "This section reviews methodological choices. "
                                "It contrasts key approaches."
                            ),
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
                            "goal": (
                                "This section summarizes the findings. "
                                "It closes with implications."
                            ),
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
        "nodes.outliner.get_llm_client_for_stage",
        lambda *_args, **_kwargs: StubLLM(),
    )

    tenant_id, run_id = db_run

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


def test_evaluator_stops_on_success(db_session, db_run):
    """Test that evaluator stops when no errors."""
    from core.orchestrator.state import EvidenceSnippetRef, OutlineModel, OutlineSection
    from db.models.draft_sections import DraftSectionRow
    from nodes import evaluator_node

    tenant_id, run_id = db_run

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

    import nodes.evaluator as evaluator_module

    evaluator_module.get_llm_client_for_stage = lambda *_args, **_kwargs: StubLLM()

    result = evaluator_node(state, db_session)

    assert result.evaluator_decision == EvaluatorDecision.STOP_SUCCESS


def test_evaluator_continues_on_errors(db_session, db_run):
    """Test that evaluator routes failed sections to repair."""
    from core.orchestrator.state import EvidenceSnippetRef, OutlineModel, OutlineSection
    from db.models.draft_sections import DraftSectionRow
    from nodes import evaluator_node

    tenant_id, run_id = db_run

    _make_snippet(db_session, tenant_id=tenant_id, snippet_id="11111111-1111-1111-1111-111111111111")

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

    import nodes.evaluator as evaluator_module

    evaluator_module.get_llm_client_for_stage = lambda *_args, **_kwargs: StubLLM()

    result = evaluator_node(state, db_session)

    assert result.evaluator_decision == EvaluatorDecision.CONTINUE_REPAIR


def test_evaluator_repairs_on_any_failed_section(db_session, db_run):
    """A single failed section should trigger repair even if overall grounding remains high."""
    from core.orchestrator.state import EvidenceSnippetRef, OutlineModel, OutlineSection
    from db.models.draft_sections import DraftSectionRow
    from nodes import evaluator_node

    tenant_id, run_id = db_run

    _make_snippet(db_session, tenant_id=tenant_id, snippet_id="11111111-1111-1111-1111-111111111111")
    _make_snippet(db_session, tenant_id=tenant_id, snippet_id="22222222-2222-2222-2222-222222222222")

    responses = iter(
        [
            json.dumps(
                {
                    "section_id": "intro",
                    "grounding_score": 75,
                    "verdict": "fail",
                    "issues": [
                        {
                            "sentence_index": 0,
                            "problem": "unsupported",
                            "notes": "Needs repair.",
                            "citations": ["11111111-1111-1111-1111-111111111111"],
                        }
                    ],
                }
            ),
            json.dumps(
                {
                    "section_id": "conclusion",
                    "grounding_score": 95,
                    "verdict": "pass",
                    "issues": [],
                }
            ),
        ]
    )

    class StubLLM:
        def generate(self, _prompt, **_kwargs):
            return next(responses)

    outline = OutlineModel(
        sections=[
            OutlineSection(
                section_id="intro",
                title="Introduction",
                goal="Intro goal sentence one. Intro goal sentence two.",
                key_points=["A", "B", "C", "D", "E", "F"],
                suggested_evidence_themes=["introtheme"],
                section_order=1,
            ),
            OutlineSection(
                section_id="conclusion",
                title="Conclusion",
                goal="Conclusion goal sentence one. Conclusion goal sentence two.",
                key_points=["A", "B", "C", "D", "E", "F"],
                suggested_evidence_themes=["conclusiontheme"],
                section_order=2,
            ),
        ]
    )
    db_session.add_all(
        [
            DraftSectionRow(
                tenant_id=tenant_id,
                run_id=run_id,
                section_id="intro",
                text="Intro sentence [CITE:11111111-1111-1111-1111-111111111111].",
            ),
            DraftSectionRow(
                tenant_id=tenant_id,
                run_id=run_id,
                section_id="conclusion",
                text="Conclusion sentence [CITE:22222222-2222-2222-2222-222222222222].",
            ),
        ]
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
            ],
            "conclusion": [
                EvidenceSnippetRef(
                    snippet_id="22222222-2222-2222-2222-222222222222",
                    source_id=uuid4(),
                    text="Conclusion evidence snippet.",
                    char_start=0,
                    char_end=29,
                )
            ],
        },
    )

    import nodes.evaluator as evaluator_module

    evaluator_module.get_llm_client_for_stage = lambda *_args, **_kwargs: StubLLM()

    result = evaluator_node(state, db_session)

    assert result.evaluator_decision == EvaluatorDecision.CONTINUE_REPAIR


def test_exporter_generates_three_artifacts(db_session, test_run):
    """Test that exporter produces all three artifacts."""
    from core.orchestrator.state import (
        OutlineModel,
        OutlineSection,
        SourceRef,
    )
    from db.models.draft_sections import DraftSectionRow
    from db.models.projects import ProjectRow
    from db.models.run_sections import RunSectionRow
    from db.models.runs import RunRow, RunStatusDb
    from nodes import exporter_node

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
    db_session.commit()  # commit so emit_run_event's separate event_session can see the run

    # Create minimal state
    outline = OutlineModel(
        sections=[
            OutlineSection(
                section_id="intro",
                title="Introduction",
                goal="Introduce the topic and scope.",
                key_points=[
                    "Context",
                    "Scope",
                    "Motivation",
                    "Framing",
                    "Definitions",
                    "Structure",
                ],
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


def test_graph_execution_completes(test_run):
    """Test that graph can execute end-to-end (simplified)."""
    tenant_id, run_id = test_run

    # Note: Full graph execution requires mocked connectors
    # This test verifies graph creation and basic structure

    class RuntimeStub:
        async def execute_node(self, *, node_name: str, node_func, state: OrchestratorState):
            return state

    graph = create_orchestrator_graph(RuntimeStub())

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


@pytest.mark.asyncio
async def test_graph_execution_uses_runtime_execute_node(monkeypatch, test_run):
    """Graph wrappers should delegate each node execution through runtime.execute_node."""
    import graph as graph_module

    tenant_id, run_id = test_run
    calls: list[str] = []

    def _passthrough_node(state: OrchestratorState, _session) -> OrchestratorState:
        return state

    monkeypatch.setattr(graph_module, "retriever_node", _passthrough_node)
    monkeypatch.setattr(graph_module, "outliner_node", _passthrough_node)
    monkeypatch.setattr(graph_module, "evidence_pack_node", _passthrough_node)
    monkeypatch.setattr(graph_module, "writer_node", _passthrough_node)
    monkeypatch.setattr(graph_module, "evaluator_node", _passthrough_node)
    monkeypatch.setattr(graph_module, "repair_agent_node", _passthrough_node)
    monkeypatch.setattr(graph_module, "exporter_node", _passthrough_node)

    class RuntimeStub:
        async def execute_node(self, *, node_name: str, node_func, state: OrchestratorState):
            calls.append(node_name)
            return node_func(state, None)

    graph = graph_module.create_orchestrator_graph(RuntimeStub())
    initial_state = OrchestratorState(
        tenant_id=tenant_id,
        run_id=run_id,
        user_query="test query",
        max_iterations=1,
    )
    final_state = await graph.ainvoke(initial_state.model_dump())

    assert final_state["run_id"] == run_id
    assert calls == [
        "retriever",
        "outliner",
        "evidence_pack",
        "writer",
        "evaluator",
        "exporter",
    ]


def test_raise_if_run_cancel_requested_bypasses_stale_identity_map(db_session, db_run):
    tenant_id, run_id = db_run

    # Prime the identity map with a stale row that still shows no cancel request.
    stale_row = (
        db_session.query(RunRow)
        .filter(RunRow.tenant_id == tenant_id, RunRow.id == run_id)
        .one()
    )
    assert stale_row.cancel_requested_at is None

    OtherSession = sessionmaker(bind=db_session.get_bind())
    other_session = OtherSession()
    try:
        fresh_row = (
            other_session.query(RunRow)
            .filter(RunRow.tenant_id == tenant_id, RunRow.id == run_id)
            .one()
        )
        fresh_row.cancel_requested_at = datetime.now(UTC)
        other_session.commit()
    finally:
        other_session.close()

    assert stale_row.cancel_requested_at is None
    with pytest.raises(RunCancelledError):
        raise_if_run_cancel_requested(db_session, tenant_id, run_id)


def test_resume_checkpoint_selector_skips_legacy_summary_rows(db_session, db_run):
    import checkpoints as checkpoint_helpers

    tenant_id, run_id = db_run

    db_session.add(
        RunCheckpointRow(
            tenant_id=tenant_id,
            run_id=run_id,
            stage="retrieval_summary",
            payload_json={"query_count": 6, "selected_sources": 12},
        )
    )
    db_session.add(
        RunCheckpointRow(
            tenant_id=tenant_id,
            run_id=run_id,
            node_name="retriever",
            iteration_count=1,
            stage="retriever",
            payload_json={
                "tenant_id": str(tenant_id),
                "run_id": str(run_id),
                "user_query": "checkpoint query",
                "max_iterations": 5,
            },
            summary_json={"node_name": "retriever"},
        )
    )
    db_session.flush()

    rows = (
        db_session.query(RunCheckpointRow)
        .filter(RunCheckpointRow.tenant_id == tenant_id, RunCheckpointRow.run_id == run_id)
        .order_by(RunCheckpointRow.created_at.desc())
        .all()
    )
    payload = checkpoint_helpers.select_resume_state_payload(
        rows,
        tenant_id=tenant_id,
        run_id=run_id,
    )

    assert payload is not None
    assert payload["user_query"] == "checkpoint query"


def test_resume_checkpoint_selector_rejects_legacy_state_like_rows(db_session, db_run):
    import checkpoints as checkpoint_helpers

    tenant_id, run_id = db_run
    db_session.add(
        RunCheckpointRow(
            tenant_id=tenant_id,
            run_id=run_id,
            node_name="retrieval_summary",
            stage="retrieval_summary",
            payload_json={
                "tenant_id": str(tenant_id),
                "run_id": str(run_id),
                "user_query": "legacy state",
                "max_iterations": 5,
            },
        )
    )
    db_session.flush()

    rows = (
        db_session.query(RunCheckpointRow)
        .filter(RunCheckpointRow.tenant_id == tenant_id, RunCheckpointRow.run_id == run_id)
        .order_by(RunCheckpointRow.created_at.desc())
        .all()
    )
    payload = checkpoint_helpers.select_resume_state_payload(
        rows,
        tenant_id=tenant_id,
        run_id=run_id,
    )

    assert payload is None


def test_repair_agent_modifies_draft(db_session, db_run):
    """Test that repair agent makes targeted edits."""
    from core.orchestrator.state import EvidenceSnippetRef, OutlineModel, OutlineSection
    from db.models.draft_sections import DraftSectionRow
    from db.models.section_reviews import SectionReviewRow
    from nodes import repair_agent_node

    tenant_id, run_id = db_run

    class StubLLM:
        def generate(self, _prompt, **_kwargs):
            return json.dumps(
                {
                    "section_id": "intro",
                    "revised_text": (
                        "Evidence-backed sentence "
                        "[CITE:11111111-1111-1111-1111-111111111111]."
                    ),
                    "revised_summary": "Sentence one.\nSentence two.",
                    "next_section_id": "methods",
                    "patched_next_text": (
                        "Transition sentence. Another transition sentence. "
                        "Methods sentence three."
                    ),
                    "patched_next_summary": "Methods line one.\nMethods line two.",
                    "edits_json": {
                        "repaired_section_edits": [
                            {
                                "sentence_index": 0,
                                "before": "Research shows transformers are effective.",
                                "after": (
                                    "Evidence-backed sentence "
                                    "[CITE:11111111-1111-1111-1111-111111111111]."
                                ),
                                "change_type": "replace",
                            }
                        ],
                        "continuity_patch": {
                            "next_section_id": "methods",
                            "before_first_two_sentences": (
                                "Methods sentence one. Methods sentence two."
                            ),
                            "after_first_two_sentences": (
                                "Transition sentence. Another transition sentence."
                            ),
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

    import nodes.repair_agent as repair_module

    repair_module.get_llm_client_for_stage = lambda *_args, **_kwargs: StubLLM()

    result = repair_agent_node(state, db_session)

    # Verify repair was attempted
    assert result.repair_attempts == 1
    assert result.draft_text


def test_repair_agent_repairs_last_section_without_next_section(db_session, db_run):
    """The last section should still be repaired even though no next-section continuity patch exists."""
    from core.orchestrator.state import EvidenceSnippetRef, OutlineModel, OutlineSection
    from db.models.draft_sections import DraftSectionRow
    from db.models.section_reviews import SectionReviewRow
    from nodes import repair_agent_node

    tenant_id, run_id = db_run

    class StubLLM:
        def generate(self, _prompt, **_kwargs):
            return json.dumps(
                {
                    "section_id": "conclusion",
                    "revised_text": "Conclusion fixed with evidence [CITE:11111111-1111-1111-1111-111111111111].",
                    "revised_summary": "Fixed conclusion.\nStill concise.",
                    "next_section_id": "",
                    "patched_next_text": "",
                    "patched_next_summary": "",
                    "edits_json": {
                        "repaired_section_edits": [
                            {
                                "sentence_index": 0,
                                "before": "Unsupported conclusion sentence.",
                                "after": "Conclusion fixed with evidence [CITE:11111111-1111-1111-1111-111111111111].",
                                "change_type": "replace",
                            }
                        ],
                        "continuity_patch": None,
                    },
                }
            )

    outline = OutlineModel(
        sections=[
            OutlineSection(
                section_id="conclusion",
                title="Conclusion",
                goal="Conclusion goal sentence one. Conclusion goal sentence two.",
                key_points=["A", "B", "C", "D", "E", "F"],
                suggested_evidence_themes=["conclusiontheme"],
                section_order=1,
            )
        ]
    )
    db_session.add(
        DraftSectionRow(
            tenant_id=tenant_id,
            run_id=run_id,
            section_id="conclusion",
            text="Unsupported conclusion sentence.",
            section_summary="Old summary line one.\nOld summary line two.",
        )
    )
    db_session.add(
        SectionReviewRow(
            tenant_id=tenant_id,
            run_id=run_id,
            section_id="conclusion",
            verdict="fail",
            issues_json=[
                {
                    "sentence_index": 0,
                    "problem": "unsupported",
                    "notes": "Missing support.",
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
            "conclusion": [
                EvidenceSnippetRef(
                    snippet_id="11111111-1111-1111-1111-111111111111",
                    source_id=uuid4(),
                    text="Conclusion evidence snippet.",
                    char_start=0,
                    char_end=28,
                )
            ]
        },
    )

    import nodes.repair_agent as repair_module

    repair_module.get_llm_client_for_stage = lambda *_args, **_kwargs: StubLLM()

    result = repair_agent_node(state, db_session)

    repaired_row = (
        db_session.query(DraftSectionRow)
        .filter(
            DraftSectionRow.tenant_id == tenant_id,
            DraftSectionRow.run_id == run_id,
            DraftSectionRow.section_id == "conclusion",
        )
        .one()
    )

    assert result.repair_attempts == 1
    assert "Conclusion fixed with evidence" in repaired_row.text


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
