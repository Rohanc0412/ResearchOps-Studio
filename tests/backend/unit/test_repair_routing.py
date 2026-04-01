from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from core.orchestrator.state import EvidenceSnippetRef, EvaluatorDecision, OrchestratorState, OutlineModel, OutlineSection
from db.repositories.evaluation_history import list_evaluation_pass_history_sync as list_evaluation_pass_history
from db.init_db import init_db_sync as init_db
from db.models.draft_sections import DraftSectionRow
from db.models.projects import ProjectRow
from db.models.runs import RunRow, RunStatusDb
from db.models.section_reviews import SectionReviewRow
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker


@pytest.fixture()
def db_session():
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


def _make_snippet(db_session, *, tenant_id: UUID, snippet_id: str) -> None:
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

    db_session.add(
        SnippetRow(
            id=UUID(snippet_id),
            tenant_id=tenant_id,
            snapshot_id=snapshot.id,
            snippet_index=0,
            text="test snippet",
            sha256=hashlib.sha256(snippet_id.encode()).hexdigest(),
        )
    )
    db_session.flush()


def _make_run(db_session, *, tenant_id: UUID, run_id: UUID) -> None:
    project = ProjectRow(
        tenant_id=tenant_id,
        name=f"proj-{run_id}",
        created_by="tester",
    )
    db_session.add(project)
    db_session.flush()
    db_session.add(
        RunRow(
            id=run_id,
            tenant_id=tenant_id,
            project_id=project.id,
            status=RunStatusDb.running,
            question="test",
        )
    )
    db_session.commit()


def test_evaluator_routes_any_failed_section_to_repair(db_session, monkeypatch):
    from nodes.evaluator import evaluator_node
    import nodes.evaluator as evaluator_module

    tenant_id = uuid4()
    run_id = uuid4()
    _make_run(db_session, tenant_id=tenant_id, run_id=run_id)

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

    monkeypatch.setattr(evaluator_module, "get_llm_client_for_stage", lambda *_args, **_kwargs: StubLLM())
    monkeypatch.setattr(evaluator_module, "emit_run_event", lambda **_kwargs: None)
    _make_snippet(db_session, tenant_id=tenant_id, snippet_id="11111111-1111-1111-1111-111111111111")
    _make_snippet(db_session, tenant_id=tenant_id, snippet_id="22222222-2222-2222-2222-222222222222")

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

    result = evaluator_node.__wrapped__(state, db_session)

    assert result.evaluator_decision == EvaluatorDecision.CONTINUE_REPAIR


def test_evaluator_persists_pipeline_faithfulness_metrics(db_session, monkeypatch):
    from nodes.evaluator import evaluator_node
    import nodes.evaluator as evaluator_module

    tenant_id = uuid4()
    run_id = uuid4()
    snippet_id = "11111111-1111-1111-1111-111111111111"
    _make_run(db_session, tenant_id=tenant_id, run_id=run_id)

    class StubLLM:
        def generate(self, prompt, **_kwargs):
            if "Rate the semantic grounding of the drafted section" in prompt:
                return json.dumps(
                    {
                        "section_id": "intro",
                        "grounding_score": 90,
                        "verdict": "pass",
                        "issues": [],
                    }
                )
            if "For each numbered claim" in prompt:
                return json.dumps({"verdicts": [{"claim_index": 0, "supported": True}]})
            return json.dumps({"claims": ["Intro sentence."]})

    monkeypatch.setattr(evaluator_module, "get_llm_client_for_stage", lambda *_args, **_kwargs: StubLLM())
    monkeypatch.setattr(evaluator_module, "emit_run_event", lambda **_kwargs: None)
    _make_snippet(db_session, tenant_id=tenant_id, snippet_id=snippet_id)

    outline = OutlineModel(
        sections=[
            OutlineSection(
                section_id="intro",
                title="Introduction",
                goal="Intro goal sentence one. Intro goal sentence two.",
                key_points=["A", "B", "C", "D", "E", "F"],
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
            text=f"Intro sentence [CITE:{snippet_id}].",
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
                    snippet_id=snippet_id,
                    source_id=uuid4(),
                    text="Intro evidence snippet.",
                    char_start=0,
                    char_end=24,
                )
            ]
        },
    )

    evaluator_node.__wrapped__(state, db_session)

    history = list_evaluation_pass_history(
        session=db_session,
        tenant_id=tenant_id,
        run_id=run_id,
    )
    assert len(history) == 1
    assert history[0]["grounding_pct"] == 90
    assert history[0]["faithfulness_pct"] == 100


def test_repair_agent_repairs_last_section_without_next_section(db_session, monkeypatch):
    from nodes.repair_agent import repair_agent_node
    import nodes.repair_agent as repair_module

    tenant_id = uuid4()
    run_id = uuid4()
    _make_run(db_session, tenant_id=tenant_id, run_id=run_id)

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

    monkeypatch.setattr(repair_module, "get_llm_client_for_stage", lambda *_args, **_kwargs: StubLLM())
    _make_snippet(db_session, tenant_id=tenant_id, snippet_id="11111111-1111-1111-1111-111111111111")

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

    result = repair_agent_node.__wrapped__(state, db_session)

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


def test_repair_agent_requires_next_section_patch_for_non_final_section(db_session, monkeypatch):
    from nodes.repair_agent import repair_agent_node
    import nodes.repair_agent as repair_module

    tenant_id = uuid4()
    run_id = uuid4()
    _make_run(db_session, tenant_id=tenant_id, run_id=run_id)

    class StubLLM:
        def generate(self, _prompt, **_kwargs):
            return json.dumps(
                {
                    "section_id": "intro",
                    "revised_text": "Intro fixed with evidence [CITE:11111111-1111-1111-1111-111111111111].",
                    "revised_summary": "Fixed intro.\nStill concise.",
                    "next_section_id": "",
                    "patched_next_text": "",
                    "patched_next_summary": "",
                    "edits_json": {
                        "repaired_section_edits": [
                            {
                                "sentence_index": 0,
                                "before": "Unsupported intro sentence.",
                                "after": "Intro fixed with evidence [CITE:11111111-1111-1111-1111-111111111111].",
                                "change_type": "replace",
                            }
                        ],
                        "continuity_patch": None,
                    },
                }
            )

    monkeypatch.setattr(repair_module, "get_llm_client_for_stage", lambda *_args, **_kwargs: StubLLM())
    _make_snippet(db_session, tenant_id=tenant_id, snippet_id="11111111-1111-1111-1111-111111111111")
    _make_snippet(db_session, tenant_id=tenant_id, snippet_id="22222222-2222-2222-2222-222222222222")

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
                section_id="next",
                title="Next",
                goal="Next goal sentence one. Next goal sentence two.",
                key_points=["A", "B", "C", "D", "E", "F"],
                suggested_evidence_themes=["nexttheme"],
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
                text="Unsupported intro sentence.",
                section_summary="Old intro summary.",
            ),
            DraftSectionRow(
                tenant_id=tenant_id,
                run_id=run_id,
                section_id="next",
                text="Next section opening. Next section detail.",
                section_summary="Old next summary.",
            ),
            SectionReviewRow(
                tenant_id=tenant_id,
                run_id=run_id,
                section_id="intro",
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
                    char_end=21,
                )
            ],
            "next": [
                EvidenceSnippetRef(
                    snippet_id="22222222-2222-2222-2222-222222222222",
                    source_id=uuid4(),
                    text="Next evidence snippet.",
                    char_start=0,
                    char_end=20,
                )
            ],
        },
    )

    with pytest.raises(ValueError, match="must include a next-section continuity patch"):
        repair_agent_node.__wrapped__(state, db_session)
