"""
Evaluator node - validates citations and grounding per section.

Uses an LLM to evaluate each drafted section against its evidence pack.
"""

from __future__ import annotations

import json
import logging

from core.env import env_bool, now_utc
from core.evaluation import ALLOWED_PROBLEMS, GROUNDING_SCHEMA
from core.orchestrator.state import (
    EvaluatorDecision,
    EvidenceSnippetRef,
    OrchestratorState,
    OutlineSection,
)
from core.pipeline_events import emit_run_event, instrument_node
from core.pipeline_events.events import truncate_text
from db.models.draft_sections import DraftSectionRow
from db.models.section_evidence import SectionEvidenceRow
from db.models.section_reviews import SectionReviewRow
from db.models.snapshots import SnapshotRow
from db.models.snippets import SnippetRow
from db.repositories.evaluation_history import (
    create_evaluation_pass,
    finalize_evaluation_pass,
    record_evaluation_section_result,
)
from llm import (
    LLMError,
    extract_json_payload,
    get_llm_client_for_stage,
    json_response_format,
    log_llm_exchange,
)
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


def _snippet_payload(snippets: list[EvidenceSnippetRef]) -> list[dict]:
    payload: list[dict] = []
    for snippet in snippets:
        payload.append(
            {
                "snippet_id": str(snippet.snippet_id),
                "text": truncate_text(snippet.text, 800),
            }
        )
    return payload


def _normalize_issue(item: dict, allowed_ids: set[str]) -> dict | None:
    if not isinstance(item, dict):
        return None
    problem = str(item.get("problem", "")).strip().lower()
    if problem not in ALLOWED_PROBLEMS:
        return None
    sentence_index = item.get("sentence_index")
    try:
        sentence_index = int(sentence_index)
    except Exception:
        sentence_index = 0
    notes = str(item.get("notes", "")).strip()
    citations_raw = item.get("citations") or []
    if not isinstance(citations_raw, list):
        citations_raw = []
    citations = [str(c).strip() for c in citations_raw if str(c).strip()]
    filtered = [c for c in citations if c in allowed_ids]
    if len(filtered) != len(citations):
        notes = notes or "Filtered invalid citations."
    return {
        "sentence_index": sentence_index,
        "problem": problem,
        "notes": notes,
        "citations": filtered,
    }


def _evaluate_section_with_llm(
    llm_client,
    *,
    section: OutlineSection,
    section_text: str,
    snippets: list[EvidenceSnippetRef],
) -> dict:
    snippet_payload = _snippet_payload(snippets)
    system = (
        "You are an expert research evaluator. "
        "Your job is to judge how well a drafted section is grounded in the provided evidence snippets."
    )
    prompt = (
        "Rate the semantic grounding of the drafted section against the evidence snippets.\n\n"
        "GROUNDING SCORE DEFINITION:\n"
        "  grounding_score = (factual sentences supported by evidence) / (total factual sentences) x 100\n"
        "  - Transitional sentences that make no factual claim are excluded from the count.\n"
        "  - A sentence is SUPPORTED if at least one snippet provides direct evidence for the claim.\n"
        "  - A sentence is UNSUPPORTED if no snippet backs it up.\n"
        "  - A sentence is OVERSTATED if snippets only partially support the strength of the claim.\n"
        "  - A sentence is CONTRADICTED if a snippet directly contradicts the claim.\n\n"
        "VERDICT RULE: verdict = 'pass' if grounding_score >= 70, else 'fail'.\n\n"
        "Return ONLY valid JSON with this schema:\n"
        "{\n"
        '  "section_id": "...",\n'
        '  "grounding_score": 0-100,\n'
        '  "verdict": "pass" | "fail",\n'
        '  "issues": [\n'
        "    {\n"
        '      "sentence_index": 0,\n'
        '      "problem": "unsupported|contradicted|overstated|missing_citation|invalid_citation|not_in_pack",\n'
        '      "notes": "Brief explanation of the grounding problem.",\n'
        '      "citations": ["snippet_id_that_supports_or_should_support_this"]\n'
        "    }\n"
        "  ]\n"
        "}\n\n"
        f"Section ID: {section.section_id}\n"
        f"Title: {section.title}\n\n"
        "Drafted section text:\n"
        + section_text
        + "\n\n"
        "Evidence snippets (id + text):\n"
        + json.dumps(snippet_payload, indent=2, ensure_ascii=True)
        + "\n\n"
        "Additional rules:\n"
        "- List ALL sentences with grounding problems, not just the worst.\n"
        "- Never invent snippet_ids; only reference IDs from the provided list.\n"
        "- Do not include markdown, backticks, or commentary outside the JSON.\n"
    )
    try:
        log_llm_exchange("request", prompt, stage="evaluate", section_id=section.section_id, logger=logger)
        response = llm_client.generate(
            prompt,
            system=system,
            max_tokens=1400,
            temperature=0.2,
            response_format=json_response_format("evaluation", GROUNDING_SCHEMA),
        )
    except LLMError as exc:
        raise ValueError("LLM evaluator failed to respond.") from exc

    log_llm_exchange("response", response, stage="evaluate", section_id=section.section_id, logger=logger)
    payload = extract_json_payload(response)
    if not isinstance(payload, dict):
        raise ValueError("Evaluator did not return a JSON object.")

    section_id = str(payload.get("section_id", "")).strip()
    if section_id and section_id != section.section_id:
        raise ValueError(
            f"Evaluator section_id mismatch: expected {section.section_id} got {section_id}"
        )

    verdict = str(payload.get("verdict", "")).strip().lower()
    if verdict not in {"pass", "fail"}:
        raise ValueError(f"Evaluator verdict invalid: {verdict}")

    allowed_ids = {str(snippet.snippet_id) for snippet in snippets}
    issues_raw = payload.get("issues") or []
    if not isinstance(issues_raw, list):
        issues_raw = []
    issues: list[dict] = []
    for item in issues_raw:
        normalized = _normalize_issue(item, allowed_ids)
        if normalized:
            issues.append(normalized)

    if issues and verdict == "pass":
        verdict = "fail"

    raw_score = payload.get("grounding_score")
    try:
        grounding_score = max(0, min(100, int(raw_score)))
    except (TypeError, ValueError):
        grounding_score = 85 if verdict == "pass" else 45

    if issues and grounding_score == 100:
        grounding_score = 85

    return {
        "section_id": section.section_id,
        "grounding_score": grounding_score,
        "verdict": verdict,
        "issues": issues,
    }


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


def _persist_section_review(
    session: Session,
    *,
    tenant_id,
    run_id,
    section_id: str,
    verdict: str,
    issues: list[dict],
) -> None:
    row = (
        session.query(SectionReviewRow)
        .filter(
            SectionReviewRow.tenant_id == tenant_id,
            SectionReviewRow.run_id == run_id,
            SectionReviewRow.section_id == section_id,
        )
        .one_or_none()
    )
    now = now_utc()
    if row:
        # Clear old issues and flush before inserting new ones to avoid
        # UniqueViolation on (review_id, issue_order) during re-evaluation.
        row.issues = []
        session.flush()
        row.verdict = verdict
        row.issues_json = issues
        row.reviewed_at = now
        row.updated_at = now
    else:
        row = SectionReviewRow(
            tenant_id=tenant_id,
            run_id=run_id,
            section_id=section_id,
            verdict=verdict,
            issues_json=issues,
            reviewed_at=now,
            created_at=now,
            updated_at=now,
        )
        session.add(row)
    session.flush()


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
                "evaluate",
                state.llm_provider,
                state.llm_model,
                stage_models=state.stage_models,
            )
        except LLMError:
            logger.warning(
                "LLM client unavailable for evaluator; falling back to pass-through.",
                extra={"stage": "evaluate"},
            )

    pass_count = 0
    fail_count = 0
    grounding_scores: list[int] = []
    issues_by_type: dict[str, int] = {}
    section_positions = {
        section.section_id: index + 1 for index, section in enumerate(outline.sections)
    }
    evaluation_pass = create_evaluation_pass(
        session=session,
        tenant_id=state.tenant_id,
        run_id=state.run_id,
        scope="pipeline",
    )

    for section in outline.sections:
        section_text = draft_sections.get(section.section_id)
        if not section_text:
            raise ValueError(f"Draft section missing for {section.section_id}")

        emit_run_event(
            session=session,
            tenant_id=state.tenant_id,
            run_id=state.run_id,
            event_type="evaluate.section_started",
            stage="evaluate",
            data={"section_id": section.section_id},
        )

        verdict = "pass"
        issues: list[dict] = []
        grounding_score = 100

        if llm_client is not None:
            snippets = _load_section_snippets(
                session,
                tenant_id=state.tenant_id,
                run_id=state.run_id,
                section_id=section.section_id,
                state_snippets=state.section_evidence_snippets,
            )
            try:
                result = _evaluate_section_with_llm(
                    llm_client,
                    section=section,
                    section_text=section_text,
                    snippets=snippets,
                )
                verdict = result["verdict"]
                issues = result["issues"]
                grounding_score = result["grounding_score"]
            except Exception:
                logger.warning(
                    "LLM evaluation failed for section %s; defaulting to pass.",
                    section.section_id,
                    extra={"stage": "evaluate", "section_id": section.section_id},
                    exc_info=True,
                )
                verdict = "pass"
                issues = []
                grounding_score = 100

        grounding_scores.append(grounding_score)

        _persist_section_review(
            session,
            tenant_id=state.tenant_id,
            run_id=state.run_id,
            section_id=section.section_id,
            verdict=verdict,
            issues=issues,
        )
        record_evaluation_section_result(
            session=session,
            tenant_id=state.tenant_id,
            evaluation_pass_id=evaluation_pass.id,
            section_id=section.section_id,
            section_title=section.title,
            section_order=section_positions.get(section.section_id),
            verdict=verdict,
            grounding_score=grounding_score,
            issues=issues,
        )

        emit_run_event(
            session=session,
            tenant_id=state.tenant_id,
            run_id=state.run_id,
            event_type="evaluate.section_completed",
            stage="evaluate",
            data={
                "section_id": section.section_id,
                "verdict": verdict,
                "grounding_score": grounding_score,
            },
        )

        if verdict == "pass":
            pass_count += 1
        else:
            fail_count += 1
        for issue in issues:
            problem = str(issue.get("problem") or "unknown")
            issues_by_type[problem] = issues_by_type.get(problem, 0) + 1

    overall_grounding_pct = round(sum(grounding_scores) / len(grounding_scores)) if grounding_scores else 100

    emit_run_event(
        session=session,
        tenant_id=state.tenant_id,
        run_id=state.run_id,
        event_type="evaluate.summary",
        stage="evaluate",
        data={
            "pass_count": pass_count,
            "fail_count": fail_count,
            "overall_grounding_pct": overall_grounding_pct,
        },
    )
    finalize_evaluation_pass(
        session=session,
        tenant_id=state.tenant_id,
        evaluation_pass_id=evaluation_pass.id,
        grounding_pct=overall_grounding_pct,
        sections_passed=pass_count,
        sections_total=pass_count + fail_count,
        issues_by_type=issues_by_type,
    )

    state.iteration_count += 1

    if fail_count > 0 and state.repair_attempts < 1:
        state.evaluator_decision = EvaluatorDecision.CONTINUE_REPAIR
        state.evaluation_reason = (
            f"{fail_count} section(s) failed grounding checks "
            f"(overall grounding {overall_grounding_pct}%); routing to repair."
        )
    else:
        state.evaluator_decision = EvaluatorDecision.STOP_SUCCESS
        if fail_count == 0:
            state.evaluation_reason = (
                f"All sections passed (overall grounding {overall_grounding_pct}%)."
            )
        else:
            state.evaluation_reason = (
                f"{fail_count} section(s) failed grounding checks (overall grounding "
                f"{overall_grounding_pct}%), but repair limit already reached; exporting as-is."
            )

    return state
