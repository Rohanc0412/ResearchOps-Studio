"""
Evaluator node - validates citations and grounding per section.

Uses an LLM to evaluate each drafted section against its evidence pack.
"""

from __future__ import annotations

from datetime import datetime
import json

from sqlalchemy.orm import Session

from db.models.draft_sections import DraftSectionRow
from db.models.section_evidence import SectionEvidenceRow
from db.models.section_reviews import SectionReviewRow
from db.models.snippets import SnippetRow
from db.models.snapshots import SnapshotRow
from researchops_core.observability import emit_run_event, instrument_node
from researchops_core.orchestrator.state import (
    EvidenceSnippetRef,
    EvaluatorDecision,
    OrchestratorState,
    OutlineSection,
)
from researchops_llm import LLMError, get_llm_client


_ALLOWED_PROBLEMS = {
    "unsupported",
    "contradicted",
    "missing_citation",
    "invalid_citation",
    "not_in_pack",
    "overstated",
}


def _log_llm_exchange(label: str, section_id: str, content: str) -> None:
    if not content:
        return


def _extract_json_payload(text: str) -> dict | list | None:
    if not text:
        return None
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`").strip()
    start_candidates = [pos for pos in (cleaned.find("{"), cleaned.find("[")) if pos != -1]
    if not start_candidates:
        return None
    start = min(start_candidates)
    end = cleaned.rfind("}") if cleaned[start] == "{" else cleaned.rfind("]")
    if end == -1 or end <= start:
        return None
    snippet = cleaned[start : end + 1]
    try:
        return json.loads(snippet)
    except json.JSONDecodeError:
        return None


def _truncate_text(text: str, max_chars: int) -> str:
    cleaned = text.strip()
    if len(cleaned) <= max_chars:
        return cleaned
    return cleaned[:max_chars].rstrip() + "..."


def _snippet_payload(snippets: list[EvidenceSnippetRef]) -> list[dict]:
    payload: list[dict] = []
    for snippet in snippets:
        payload.append(
            {
                "snippet_id": str(snippet.snippet_id),
                "text": _truncate_text(snippet.text, 800),
            }
        )
    return payload


def _normalize_issue(item: dict, allowed_ids: set[str]) -> dict | None:
    if not isinstance(item, dict):
        return None
    problem = str(item.get("problem", "")).strip().lower()
    if problem not in _ALLOWED_PROBLEMS:
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
    prompt = (
        "Evaluate the drafted section for citation structure and grounding.\n"
        "Return ONLY valid JSON with this schema:\n"
        "{\n"
        '  "section_id": "...",\n'
        '  "verdict": "pass" | "fail",\n'
        '  "issues": [\n'
        "    {\n"
        '      "sentence_index": 0,\n'
        '      "problem": "unsupported|contradicted|missing_citation|invalid_citation|not_in_pack|overstated",\n'
        '      "notes": "...",\n'
        '      "citations": ["snippet_id_1"]\n'
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
        "Rules:\n"
        "- Every factual sentence must have at least one [CITE:...] at the end.\n"
        "- Transitional sentences may be uncited.\n"
        "- Every cited snippet_id must exist and be in the evidence pack.\n"
        "- Verify cited snippets support the sentence.\n"
        "- Never invent snippet_ids.\n"
        "- Do not include markdown, no backticks, no commentary.\n"
    )
    system = "You are a strict citation validator and fact checker for research drafts."
    try:
        _log_llm_exchange("request", section.section_id, prompt)
        response = llm_client.generate(
            prompt,
            system=system,
            max_tokens=1400,
            temperature=0.2,
            response_format="json",
        )
    except LLMError as exc:
        raise ValueError("LLM evaluator failed to respond.") from exc

    _log_llm_exchange("response", section.section_id, response)
    payload = _extract_json_payload(response)
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

    return {
        "section_id": section.section_id,
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
    now = datetime.utcnow()
    if row:
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

    try:
        llm_client = get_llm_client(state.llm_provider, state.llm_model)
    except LLMError as exc:
        raise ValueError("LLM evaluator is required but unavailable.") from exc
    if not llm_client:
        raise ValueError("LLM evaluator is required but no LLM client is configured.")

    pass_count = 0
    fail_count = 0

    for section in outline.sections:
        section_text = draft_sections.get(section.section_id)
        if not section_text:
            raise ValueError(f"Draft section missing for {section.section_id}")

        section_snippets = _load_section_snippets(
            session,
            tenant_id=state.tenant_id,
            run_id=state.run_id,
            section_id=section.section_id,
            state_snippets=state.section_evidence_snippets,
        )

        emit_run_event(
            session=session,
            tenant_id=state.tenant_id,
            run_id=state.run_id,
            event_type="evaluate.section_started",
            stage="evaluate",
            data={"section_id": section.section_id},
        )

        review = _evaluate_section_with_llm(
            llm_client,
            section=section,
            section_text=section_text,
            snippets=section_snippets,
        )

        _persist_section_review(
            session,
            tenant_id=state.tenant_id,
            run_id=state.run_id,
            section_id=section.section_id,
            verdict=review["verdict"],
            issues=review["issues"],
        )

        emit_run_event(
            session=session,
            tenant_id=state.tenant_id,
            run_id=state.run_id,
            event_type="evaluate.section_completed",
            stage="evaluate",
            data={"section_id": section.section_id, "verdict": review["verdict"]},
        )

        if review["verdict"] == "pass":
            pass_count += 1
        else:
            fail_count += 1

    emit_run_event(
        session=session,
        tenant_id=state.tenant_id,
        run_id=state.run_id,
        event_type="evaluate.summary",
        stage="evaluate",
        data={"pass_count": pass_count, "fail_count": fail_count},
    )

    if fail_count > 0:
        state.evaluator_decision = EvaluatorDecision.CONTINUE_REWRITE
        state.evaluation_reason = f"{fail_count} section(s) failed evaluation"
    else:
        state.evaluator_decision = EvaluatorDecision.STOP_SUCCESS
        state.evaluation_reason = "All sections passed evaluation"


    return state
