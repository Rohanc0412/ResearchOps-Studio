from __future__ import annotations

import json
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from core.orchestrator.state import EvidenceSnippetRef, EvaluatorDecision, OrchestratorState, OutlineModel, OutlineSection
from db.init_db import init_db
from db.models.draft_sections import DraftSectionRow
from db.models.section_reviews import SectionReviewRow
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker


@pytest.fixture()
def db_session():
    engine = create_engine("sqlite:///:memory:", echo=False)
    init_db(engine=engine)
    SessionLocal = sessionmaker(bind=engine)
    session = SessionLocal()
    yield session
    session.close()


def test_evaluator_routes_any_failed_section_to_repair(db_session, monkeypatch):
    from nodes.evaluator import evaluator_node
    import nodes.evaluator as evaluator_module

    tenant_id = uuid4()
    run_id = uuid4()

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


def test_repair_agent_repairs_last_section_without_next_section(db_session, monkeypatch):
    from nodes.repair_agent import repair_agent_node
    import nodes.repair_agent as repair_module

    tenant_id = uuid4()
    run_id = uuid4()

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
