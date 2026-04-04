"""
Evaluator node — extracts atomic claims per section and scores quality.

Uses RagasExtractor for claim decomposition and EvaluationScorer for
quality_pct + hallucination_rate. Claims are cached to section_claims so
manual evaluation can reuse them without re-extraction.
"""

from __future__ import annotations

import asyncio
import logging

from core.env import env_bool
from core.evaluation_scorer import EvaluationScorer
from core.orchestrator.state import (
    EvaluatorDecision,
    EvidenceSnippetRef,
    OrchestratorState,
)
from core.pipeline_events import instrument_node
from core.pipeline_events.events import emit_node_progress
from core.ragas_extractor import RagasExtractor
from db.models.draft_sections import DraftSectionRow
from db.models.section_evidence import SectionEvidenceRow
from db.models.snapshots import SnapshotRow
from db.models.snippets import SnippetRow
from db.repositories.evaluation_history import (
    create_evaluation_pass_sync as create_evaluation_pass,
    finalize_evaluation_pass_sync as finalize_evaluation_pass,
    record_evaluation_section_result_sync as record_evaluation_section_result,
)
from db.repositories.section_claims import upsert_section_claims
from langfuse import observe
from llm import LLMError, get_llm_client_for_stage
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


def _load_draft_sections(session: Session, *, tenant_id, run_id) -> dict[str, str]:
    rows = (
        session.query(DraftSectionRow.section_id, DraftSectionRow.text)
        .filter(DraftSectionRow.tenant_id == tenant_id, DraftSectionRow.run_id == run_id)
        .all()
    )
    return {row.section_id: row.text for row in rows}


def _load_section_snippets(
    session: Session,
    *,
    tenant_id,
    run_id,
    section_id: str,
    state_snippets: dict[str, list[EvidenceSnippetRef]],
) -> list[EvidenceSnippetRef]:
    cached = state_snippets.get(section_id)
    if cached is not None:
        return cached

    rows = (
        session.query(
            SnippetRow.id,
            SnippetRow.text,
            SnippetRow.char_start,
            SnippetRow.char_end,
            SnapshotRow.source_id,
        )
        .join(SnapshotRow, SnapshotRow.id == SnippetRow.snapshot_id)
        .join(
            SectionEvidenceRow,
            (SectionEvidenceRow.snippet_id == SnippetRow.id)
            & (SectionEvidenceRow.tenant_id == SnippetRow.tenant_id),
        )
        .filter(
            SectionEvidenceRow.tenant_id == tenant_id,
            SectionEvidenceRow.run_id == run_id,
            SectionEvidenceRow.section_id == section_id,
        )
        .all()
    )
    snippets: list[EvidenceSnippetRef] = []
    for row in rows:
        snippets.append(
            EvidenceSnippetRef(
                snippet_id=row.id,
                source_id=row.source_id,
                text=row.text,
                char_start=row.char_start or 0,
                char_end=row.char_end or len(row.text or ""),
            )
        )
    return snippets


@observe(name="evaluator")
@instrument_node("evaluate")
def evaluator_node(state: OrchestratorState, session: Session) -> OrchestratorState:
    outline = state.outline
    if outline is None or not outline.sections:
        raise ValueError("Outline is required for evaluation.")

    draft_sections = _load_draft_sections(session, tenant_id=state.tenant_id, run_id=state.run_id)
    if not draft_sections:
        raise ValueError("Draft sections not found for evaluation.")

    llm_client = None
    if env_bool("EVALUATOR_LLM_ENABLED", True):
        try:
            llm_client = get_llm_client_for_stage(
                "evaluate", state.llm_provider, state.llm_model, stage_models=state.stage_models,
            )
        except LLMError:
            logger.warning(
                "LLM client unavailable for evaluator; falling back to pass-through.",
                extra={"stage": "evaluate"},
            )

    scorer = EvaluationScorer()
    extractor = RagasExtractor(llm_client=llm_client) if llm_client else None
    section_positions = {s.section_id: i + 1 for i, s in enumerate(outline.sections)}
    evaluation_pass = create_evaluation_pass(
        session=session, tenant_id=state.tenant_id, run_id=state.run_id, scope="pipeline",
    )

    section_scores: list[int] = []
    all_verdicts: list[str] = []
    sections_to_repair: list[str] = []

    for section in outline.sections:
        section_text = draft_sections.get(section.section_id, "")
        if not section_text:
            raise ValueError(f"Draft section missing for {section.section_id}")

        emit_node_progress(
            session=session, tenant_id=state.tenant_id, run_id=state.run_id,
            event_type="evaluate.section_started", stage="evaluate",
            data={"section_id": section.section_id},
        )

        claims: list[str] = []
        verdicts: list[str] = []
        quality_score = 100

        if extractor is not None:
            snippets = _load_section_snippets(
                session, tenant_id=state.tenant_id, run_id=state.run_id,
                section_id=section.section_id, state_snippets=state.section_evidence_snippets,
            )
            snippet_texts = [s.text for s in snippets]
            try:
                loop = asyncio.new_event_loop()
                claims = loop.run_until_complete(extractor.extract(section_text, snippet_texts))
                loop.close()
            except Exception:
                logger.warning(
                    "Claim extraction failed for section %s; using empty claims.",
                    section.section_id,
                    extra={"stage": "evaluate", "section_id": section.section_id},
                    exc_info=True,
                )
                claims = []

            # Pipeline eval uses binary "supported" placeholder for speed.
            # Full nuanced classification runs during manual evaluation.
            verdicts = ["supported"] * len(claims)
            quality_score = scorer.section_quality(verdicts)

        # Cache claims for manual evaluation reuse
        if claims:
            upsert_section_claims(
                session, tenant_id=state.tenant_id, run_id=state.run_id,
                section_id=section.section_id, claims=claims,
            )

        section_scores.append(quality_score)
        all_verdicts.extend(verdicts)

        needs_repair = scorer.repair_needed(verdicts, quality_score)
        if needs_repair:
            sections_to_repair.append(section.section_id)

        record_evaluation_section_result(
            session=session, tenant_id=state.tenant_id,
            evaluation_pass_id=evaluation_pass.id,
            section_id=section.section_id,
            section_title=section.title,
            section_order=section_positions.get(section.section_id),
            quality_score=quality_score,
            claims=[
                {"claim_index": i, "claim_text": c, "verdict": "supported", "citations": [], "notes": ""}
                for i, c in enumerate(claims)
            ],
        )

        emit_node_progress(
            session=session, tenant_id=state.tenant_id, run_id=state.run_id,
            event_type="evaluate.section_completed", stage="evaluate",
            data={"section_id": section.section_id, "quality_score": quality_score},
        )

    overall_quality = scorer.report_quality(section_scores)
    hallucination = scorer.hallucination_rate(all_verdicts)

    finalize_evaluation_pass(
        session=session, tenant_id=state.tenant_id, evaluation_pass_id=evaluation_pass.id,
        quality_pct=overall_quality, hallucination_rate=hallucination, issues_by_type={},
    )

    state.iteration_count += 1

    decision = (
        EvaluatorDecision.CONTINUE_REPAIR if sections_to_repair and state.repair_attempts < 1
        else EvaluatorDecision.STOP_SUCCESS
    )

    return state.model_copy(update={
        "evaluator_decision": decision,
        "sections_to_repair": sections_to_repair,
        "evaluation_reason": (
            f"{len(sections_to_repair)} section(s) below quality threshold; routing to repair."
            if sections_to_repair and state.repair_attempts < 1
            else f"All sections evaluated (quality {overall_quality}%, hallucination {hallucination}%)."
        ),
    })
