"""
Writer node - drafts the report with inline citations.

Generates per-section drafts with strict [CITE:snippet_id] citations.
Persists each section to draft_sections and assembles the final report.
"""

from __future__ import annotations

import json
import logging
import os

from core.env import env_int, now_utc
from core.orchestrator.state import EvidenceSnippetRef, OrchestratorState, OutlineSection
from core.pipeline_events import emit_run_event, instrument_node
from langfuse.decorators import observe
from core.pipeline_events.events import truncate_text
from db.models.draft_sections import DraftSectionRow
from db.models.section_evidence import SectionEvidenceRow
from llm import (
    LLMError,
    extract_json_payload,
    get_llm_client_for_stage,
    json_response_format,
    log_llm_exchange,
)
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

DRAFT_SECTION_SCHEMA = {
    "type": "object",
    "properties": {
        "section_id": {"type": "string"},
        "section_text": {"type": "string"},
        "section_summary": {"type": "string"},
        "status": {"type": "string"},
    },
    "required": ["section_id", "section_text", "section_summary", "status"],
    "additionalProperties": False,
}



def _load_section_snippet_ids(
    *, session: Session, tenant_id, run_id, section_id: str
) -> set:
    rows = (
        session.query(SectionEvidenceRow.snippet_id)
        .filter(
            SectionEvidenceRow.tenant_id == tenant_id,
            SectionEvidenceRow.run_id == run_id,
            SectionEvidenceRow.section_id == section_id,
        )
        .all()
    )
    snippet_ids = {row[0] for row in rows}
    return snippet_ids


def _build_snippet_payload(snippets: list[EvidenceSnippetRef]) -> list[dict]:
    payload: list[dict] = []
    for snippet in snippets:
        payload.append(
            {
                "snippet_id": str(snippet.snippet_id),
                "text": truncate_text(snippet.text, 400),
            }
        )
    return payload
def _generate_section_with_llm(
    llm_client,
    section: OutlineSection,
    snippets: list[EvidenceSnippetRef],
    *,
    report_title: str,
    section_index: int,
    total_sections: int,
    prev_title: str | None,
    next_title: str | None,
    prior_summary: str | None,
) -> tuple[str, str]:
    snippet_payload = _build_snippet_payload(snippets)
    prompt = (
        "Draft a report section using ONLY the evidence snippets provided.\n"
        "Return ONLY valid JSON with this schema:\n"
        "{\n"
        '  "section_id": "...",\n'
        '  "section_text": "...",\n'
        '  "section_summary": "...",\n'
        '  "status": "ok"\n'
        "}\n\n"
        f"Report Title: {report_title}\n"
        f"Section {section_index} of {total_sections}\n"
        f"Previous Section Title: {prev_title or 'NONE (this is the first section)'}\n"
        f"Current Section ID: {section.section_id}\n"
        f"Current Section Title: {section.title}\n"
        f"Current Section Goal: {section.goal}\n"
        f"Next Section Title: {next_title or 'NONE (this is the last section)'}\n\n"
        "Prior section micro-summary (use this ONLY for narrative continuity, not for facts):\n"
        f"{prior_summary or 'NONE'}\n\n"
        "Rules:\n"
        "- Use ONLY the snippets provided for factual content.\n"
        "- Section length MUST be at least "
        f"{env_int('DRAFT_SECTION_MIN_WORDS', 50, min_value=0)} words.\n"
        "- Every sentence that contains any factual claim MUST end with citation token(s).\n"
        "- If a sentence cannot be supported by the provided snippets, rewrite "
        "it as a non-factual transition.\n"
        "- Citation format: [CITE:snippet_id]\n"
        "- Multiple citations must be separate tokens: [CITE:id1] [CITE:id2]\n"
        "- Use the exact snippet_id values from the evidence list; do NOT "
        "shorten or truncate them.\n"
        "- Citations must appear at the very end of the sentence, after the final punctuation.\n"
        "- No citations spanning multiple sentences.\n"
        "- Narrative transitions may be uncited, but must contain no facts, "
        "names, dates, numbers, or definitions.\n"
        "- Do NOT include headings, bullet lists, or markdown in section_text.\n"
        "- Do NOT include any commentary outside JSON.\n\n"
        "Flow requirements:\n"
        "- Start section_text with 1 to 2 short transition sentences that "
        "connect from the prior micro-summary.\n"
        "- End section_text with 1 short bridge sentence that sets up the next section.\n"
        "- Do NOT repeat long chunks from prior sections.\n\n"
        "Micro-summary requirements (section_summary):\n"
        "- Provide 1 to 3 sentences as plain text.\n"
        "- No citations in section_summary.\n"
        "- No new facts or numbers that are not already stated in section_text.\n"
        "- The summary is for continuity only.\n\n"
        "Evidence snippets (id + text):\n"
        + json.dumps(snippet_payload, indent=2, ensure_ascii=True)
    )
    system = "You draft evidence-grounded sections and respond with strict JSON only."
    log_llm_exchange("request", prompt, stage="draft", section_id=section.section_id, logger=logger)
    try:
        response = llm_client.generate(
            prompt,
            system=system,
            max_tokens=env_int("DRAFT_SECTION_MAX_TOKENS", 1800, min_value=600),
            temperature=0.3,
            response_format=json_response_format("draft_section", DRAFT_SECTION_SCHEMA),
        )
    except LLMError as exc:
        raise ValueError("LLM drafting failed for section.") from exc

    log_llm_exchange("response", response, stage="draft", section_id=section.section_id, logger=logger)
    payload = extract_json_payload(response)
    if not isinstance(payload, dict):
        raise ValueError("LLM draft did not return a JSON object.")

    section_id = str(payload.get("section_id", "")).strip()
    status = str(payload.get("status", "")).strip().lower()
    section_text = payload.get("section_text")
    section_summary = payload.get("section_summary")
    if section_id and section_id != section.section_id:
        raise ValueError(
            f"Draft section_id mismatch: expected {section.section_id} got {section_id}"
        )
    if status and status != "ok":
        raise ValueError(f"Draft status not ok: {status}")
    if not isinstance(section_text, str):
        raise ValueError("Draft section_text must be a string.")
    if not isinstance(section_summary, str):
        raise ValueError("Draft section_summary must be a string.")

    return section_text.strip(), section_summary.strip()


def _persist_draft_section(
    session: Session,
    *,
    tenant_id,
    run_id,
    section_id: str,
    text: str,
    section_summary: str | None,
) -> None:
    row = (
        session.query(DraftSectionRow)
        .filter(
            DraftSectionRow.tenant_id == tenant_id,
            DraftSectionRow.run_id == run_id,
            DraftSectionRow.section_id == section_id,
        )
        .one_or_none()
    )
    now = now_utc()
    if row:
        row.text = text
        row.section_summary = section_summary
        row.updated_at = now
    else:
        row = DraftSectionRow(
            tenant_id=tenant_id,
            run_id=run_id,
            section_id=section_id,
            text=text,
            section_summary=section_summary,
            created_at=now,
            updated_at=now,
        )
        session.add(row)
    session.flush()


@observe(name="writer")
@instrument_node("draft")
def writer_node(state: OrchestratorState, session: Session) -> OrchestratorState:
    """
    Draft the report with inline citations, section by section.
    """
    outline = state.outline
    if not outline:
        raise ValueError("Outline not found in state")

    evidence_snippets = state.evidence_snippets
    section_evidence_snippets = state.section_evidence_snippets

    try:
        llm_client = get_llm_client_for_stage("draft", state.llm_provider, state.llm_model, stage_models=state.stage_models)
    except LLMError as exc:
        raise ValueError("LLM drafting is required but the LLM client is unavailable.") from exc
    if not llm_client:
        raise ValueError("LLM drafting is required but no LLM client is configured.")


    report_title = (state.outline and state.outline.report_title) or f"Research Report: {state.user_query}"
    draft_lines: list[str] = [f"# {report_title}", ""]
    drafted_sections: list[tuple[OutlineSection, str, str]] = []
    prior_summary: str | None = None

    for i, section in enumerate(outline.sections):
        if i % 3 == 0:
            emit_run_event(
                session=session,
                tenant_id=state.tenant_id,
                run_id=state.run_id,
                event_type="progress",
                stage="draft",
                data={
                    "section_index": i + 1,
                    "total_sections": len(outline.sections),
                    "section_id": section.section_id,
                },
            )

        section_snippets = section_evidence_snippets.get(section.section_id)
        if section_snippets is None:
            allowed_snippet_ids = _load_section_snippet_ids(
                session=session,
                tenant_id=state.tenant_id,
                run_id=state.run_id,
                section_id=section.section_id,
            )
            if allowed_snippet_ids:
                section_snippets = [
                    s for s in evidence_snippets if s.snippet_id in allowed_snippet_ids
                ]
            else:
                section_snippets = []

        emit_run_event(
            session=session,
            tenant_id=state.tenant_id,
            run_id=state.run_id,
            event_type="draft.section_started",
            stage="draft",
            data={"section_id": section.section_id, "snippet_count": len(section_snippets)},
        )

        prev_title = outline.sections[i - 1].title if i > 0 else None
        next_title = outline.sections[i + 1].title if i + 1 < len(outline.sections) else None
        section_text, section_summary = _generate_section_with_llm(
            llm_client,
            section,
            section_snippets,
            report_title=report_title,
            section_index=i + 1,
            total_sections=len(outline.sections),
            prev_title=prev_title,
            next_title=next_title,
            prior_summary=prior_summary,
        )
        _persist_draft_section(
            session,
            tenant_id=state.tenant_id,
            run_id=state.run_id,
            section_id=section.section_id,
            text=section_text,
            section_summary=section_summary,
        )

        emit_run_event(
            session=session,
            tenant_id=state.tenant_id,
            run_id=state.run_id,
            event_type="draft.section_completed",
            stage="draft",
            data={"section_id": section.section_id, "status": "ok"},
        )

        drafted_sections.append((section, section_text, section_summary))
        prior_summary = section_summary

    include_summary_comments = (
        os.getenv("DRAFT_INCLUDE_SUMMARY_COMMENTS", "").strip().lower()
        in {"1", "true", "yes", "on"}
    )
    for section, section_text, section_summary in drafted_sections:
        draft_lines.append(f"## {section.section_order}. {section.title}")
        draft_lines.append("")
        if section_text:
            draft_lines.append(section_text)
        draft_lines.append("")
        if include_summary_comments and section_summary:
            draft_lines.append("<!-- section_summary:")
            draft_lines.append(section_summary)
            draft_lines.append("-->")
            draft_lines.append("")

    draft_text = "\n".join(draft_lines).strip() + "\n"

    state.draft_text = draft_text
    state.draft_version += 1

    return state
