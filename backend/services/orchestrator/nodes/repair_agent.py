"""
RepairAgent node - repairs failed sections and patches continuity.

Uses an LLM to repair only failing sentences in a section and to
patch the first two sentences of the next section for continuity when
that next section is not already scheduled for its own repair pass.
"""

from __future__ import annotations

import json
import logging
import re

from core.env import now_utc
from core.orchestrator.state import (
    EvidenceSnippetRef,
    OrchestratorState,
    OutlineSection,
)
from core.pipeline_events import instrument_node
from db.models.draft_sections import DraftSectionRow
from db.models.section_evidence import SectionEvidenceRow
from db.models.section_reviews import SectionReviewRow
from db.models.snapshots import SnapshotRow
from db.models.snippets import SnippetRow
from langfuse.decorators import observe
from llm import (
    LLMError,
    extract_json_payload,
    get_llm_client_for_stage,
    json_response_format,
    log_llm_exchange,
)
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

REPAIR_SCHEMA = {
    "type": "object",
    "properties": {
        "section_id": {"type": "string"},
        "revised_text": {"type": "string"},
        "revised_summary": {"type": "string"},
        "self_check": {
            "type": "object",
            "properties": {
                "factual_sentence_count": {"type": "integer"},
                "supported_sentence_count": {"type": "integer"},
                "estimated_grounding_pct": {"type": "integer"},
            },
            "required": [
                "factual_sentence_count",
                "supported_sentence_count",
                "estimated_grounding_pct",
            ],
        },
    },
    "required": ["section_id", "revised_text", "revised_summary", "self_check"],
    "additionalProperties": False,
}

_CITATION_PATTERN = re.compile(r"\[CITE:([a-f0-9-]+)\]")
_ALLOWED_ISSUE_TYPES = {
    "unsupported",
    "overstated",
    "missing_citation",
    "invalid_citation",
    "not_in_pack",
}



def _split_into_sentences(text: str) -> list[str]:
    cleaned = text.strip()
    if not cleaned:
        return []
    parts = re.split(r"(?<=[.!?])\s+", cleaned)
    return [part.strip() for part in parts if part.strip()]


def _extract_citations(text: str) -> list[str]:
    return _CITATION_PATTERN.findall(text)


def _citations_at_sentence_end(sentence: str) -> bool:
    cleaned = sentence.strip()
    if not cleaned:
        return True
    if cleaned[-1] in ".!?":
        cleaned = cleaned[:-1].rstrip()
    tail_match = re.search(r"(\[CITE:[^\]]+\](?:\s+\[CITE:[^\]]+\])*)$", cleaned)
    if not tail_match:
        return False
    tail = tail_match.group(1)
    all_cites = re.findall(r"\[CITE:[^\]]+\]", cleaned)
    tail_cites = re.findall(r"\[CITE:[^\]]+\]", tail)
    return len(all_cites) == len(tail_cites)


def _validate_section_text(section_text: str, allowed_snippet_ids: set[str]) -> None:
    citations = _extract_citations(section_text)
    invalid = sorted({cid for cid in citations if cid not in allowed_snippet_ids})
    if invalid:
        raise ValueError(f"Section cites snippets not in evidence pack: {invalid}")

    for sentence in _split_into_sentences(section_text):
        if "[CITE:" not in sentence:
            continue
        if not _citations_at_sentence_end(sentence):
            raise ValueError("Citations must appear only at the end of each cited sentence.")


def _strip_citations(text: str) -> str:
    cleaned = _CITATION_PATTERN.sub("", text)
    cleaned = re.sub(r"\s{2,}", " ", cleaned).strip()
    if cleaned and cleaned[-1] not in ".!?":
        cleaned += "."
    return cleaned


def _summary_from_text(text: str) -> str:
    sentences = _split_into_sentences(text)
    if len(sentences) >= 2:
        line1 = _strip_citations(sentences[0])
        line2 = _strip_citations(sentences[1])
    elif sentences:
        line1 = _strip_citations(sentences[0])
        line2 = "This section remains limited by the available evidence."
    else:
        line1 = "This section contains no supported factual statements."
        line2 = "Additional evidence is required to expand the analysis."
    summary = f"{line1}\n{line2}"
    return summary


def _validate_repair_scope(
    original_text: str, revised_text: str, issue_indices: set[int]
) -> None:
    original_sentences = _split_into_sentences(original_text)
    revised_sentences = _split_into_sentences(revised_text)

    if not issue_indices:
        if original_text.strip() != revised_text.strip():
            raise ValueError("No issues provided but revised text differs.")
        return

    i = 0
    j = 0
    while i < len(original_sentences) and j < len(revised_sentences):
        if i in issue_indices:
            if revised_sentences[j] == original_sentences[i]:
                i += 1
                j += 1
                continue
            next_non_issue = i + 1
            while next_non_issue < len(original_sentences) and next_non_issue in issue_indices:
                next_non_issue += 1
            if (
                next_non_issue < len(original_sentences)
                and revised_sentences[j] == original_sentences[next_non_issue]
            ):
                i = next_non_issue
                continue
            i += 1
            j += 1
            continue

        if revised_sentences[j] != original_sentences[i]:
            raise ValueError("Non-issue sentence was modified during repair.")
        i += 1
        j += 1

    if i < len(original_sentences):
        remaining_non_issue = [
            idx for idx in range(i, len(original_sentences)) if idx not in issue_indices
        ]
        if remaining_non_issue:
            raise ValueError("Revised text removed non-issue sentences.")

    if j < len(revised_sentences):
        raise ValueError("Revised text added new sentences outside issue scope.")


def _validate_next_section_patch(
    original_text: str,
    patched_text: str,
    allowed_snippet_ids: set[str],
) -> None:
    original_sentences = _split_into_sentences(original_text)
    patched_sentences = _split_into_sentences(patched_text)

    if len(original_sentences) < 2 or len(patched_sentences) < 2:
        raise ValueError("Next section must have at least two sentences to patch.")

    if original_sentences[2:] != patched_sentences[2:]:
        raise ValueError("Next section text beyond the first two sentences was modified.")

    first_two = " ".join(patched_sentences[:2])
    _validate_section_text(first_two, allowed_snippet_ids)


def _remove_issue_sentences(text: str, issue_indices: set[int]) -> tuple[str, list[dict]]:
    sentences = _split_into_sentences(text)
    if not sentences:
        return text, []
    edits: list[dict] = []
    revised: list[str] = []
    for idx, sentence in enumerate(sentences):
        if idx in issue_indices:
            edits.append(
                {
                    "sentence_index": idx,
                    "before": sentence,
                    "after": "",
                    "change_type": "remove",
                }
            )
            continue
        revised.append(sentence)
    revised_text = " ".join(revised).strip()
    return revised_text, edits


def _patch_next_section_narrative(
    *,
    next_section_id: str,
    next_section_text: str,
    revised_summary: str,
    next_section_title: str,
) -> tuple[str, str, dict]:
    sentences = _split_into_sentences(next_section_text)
    if len(sentences) < 2:
        raise ValueError("Next section must have at least two sentences to patch.")
    summary_line = revised_summary.splitlines()[0] if revised_summary else "the prior section"
    first_sentence = (
        f"Building on {summary_line.lower()}, this section transitions into "
        f"{next_section_title}."
    )
    second_sentence = (
        "The following discussion connects the earlier summary to the next set of "
        "evidence."
    )
    patched = [first_sentence, second_sentence] + sentences[2:]
    patched_text = " ".join(patched).strip()
    patch_log = {
        "next_section_id": next_section_id,
        "before_first_two_sentences": " ".join(sentences[:2]),
        "after_first_two_sentences": f"{first_sentence} {second_sentence}",
    }
    return patched_text, _summary_from_text(patched_text), patch_log


def _load_outline_by_id(state: OrchestratorState) -> dict[str, OutlineSection]:
    outline = state.outline
    if outline is None or not outline.sections:
        raise ValueError("Outline is required for repairs.")
    return {section.section_id: section for section in outline.sections}


def _load_section_order(state: OrchestratorState) -> list[str]:
    outline = state.outline
    if outline is None or not outline.sections:
        raise ValueError("Outline is required for repairs.")
    ordered = sorted(outline.sections, key=lambda s: s.section_order)
    return [section.section_id for section in ordered]


def _load_draft_sections(session: Session, *, tenant_id, run_id) -> dict[str, DraftSectionRow]:
    rows = (
        session.query(DraftSectionRow)
        .filter(DraftSectionRow.tenant_id == tenant_id, DraftSectionRow.run_id == run_id)
        .all()
    )
    return {row.section_id: row for row in rows}


def _load_section_reviews(session: Session, *, tenant_id, run_id) -> dict[str, SectionReviewRow]:
    rows = (
        session.query(SectionReviewRow)
        .filter(SectionReviewRow.tenant_id == tenant_id, SectionReviewRow.run_id == run_id)
        .all()
    )
    return {row.section_id: row for row in rows}


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


def _normalize_issues(raw_issues: list[dict]) -> list[dict]:
    issues: list[dict] = []
    for item in raw_issues or []:
        issue_type = str(item.get("issue_type") or item.get("problem") or "").strip().lower()
        if issue_type not in _ALLOWED_ISSUE_TYPES:
            continue
        try:
            sentence_index = int(item.get("sentence_index", 0))
        except Exception:
            sentence_index = 0
        details = str(item.get("details") or item.get("notes") or "").strip()
        issues.append(
            {
                "sentence_index": sentence_index,
                "issue_type": issue_type,
                "details": details,
            }
        )
    return issues


def _build_snippet_payload(snippets: list[EvidenceSnippetRef]) -> list[dict]:
    payload: list[dict] = []
    for snippet in snippets:
        payload.append(
            {
                "snippet_id": str(snippet.snippet_id),
                "text": snippet.text.strip()[:600],
            }
        )
    return payload


def _repair_with_llm(
    llm_client,
    *,
    section: OutlineSection,
    section_text: str,
    section_summary: str,
    prior_summary: str | None,
    issues: list[dict],
    evidence_snippets: list[EvidenceSnippetRef],
) -> dict:
    prompt = (
        "This section FAILED a 70% grounding evaluation. Rewrite it entirely so that it PASSES.\n\n"
        "GROUNDING RULE (same definition the evaluator uses):\n"
        "  grounding_score = supported_factual_sentences / total_factual_sentences \u00d7 100\n"
        "  You MUST achieve grounding_score > 70.\n"
        "  Transitional sentences with no factual claim are excluded from the count.\n\n"
        f"Section ID: {section.section_id}\n"
        f"Section Title: {section.title}\n"
        f"Section Goal: {section.goal}\n"
        "Prior Section Summary (for narrative transitions only, not as a fact source):\n"
        f"{prior_summary or 'NONE'}\n\n"
        "Evaluator found these issues (use as guidance):\n"
        + json.dumps(issues, indent=2, ensure_ascii=True)
        + "\n\n"
        "Current section text:\n"
        + section_text
        + "\n\n"
        "Evidence snippets (the ONLY source of facts you may use):\n"
        + json.dumps(_build_snippet_payload(evidence_snippets), indent=2, ensure_ascii=True)
        + "\n\n"
        "Rules:\n"
        "- Every factual sentence MUST be supported by at least one snippet and end with [CITE:snippet_id].\n"
        "- If a claim cannot be supported by any snippet, remove the sentence.\n"
        "- You MAY restructure, combine, or reorder sentences.\n"
        "- Do NOT invent facts not present in the snippets.\n"
        "- Narrative transitions (no facts, no names, no numbers) may be uncited.\n"
        "- No headings, bullet lists, or markdown in revised_text.\n"
        "- Use the exact snippet_id values from the evidence list.\n"
        "- Multiple citations: separate tokens [CITE:id1] [CITE:id2].\n"
        "- Citations at the very end of the sentence, after final punctuation.\n\n"
        "Self-check (REQUIRED before returning):\n"
        "1. Count every factual sentence in your revised_text.\n"
        "2. Verify each one is supported by a provided snippet.\n"
        "3. Compute: supported / total \u00d7 100.\n"
        "4. If the result is \u2264 70, revise again until it exceeds 70.\n"
        "5. Report the final counts in self_check.\n"
    )
    system = "You repair evidence-grounded drafts and return strict JSON only."
    log_llm_exchange("request", prompt, stage="repair", section_id=section.section_id, logger=logger)
    response = llm_client.generate(
        prompt,
        system=system,
        max_tokens=1800,
        temperature=0.2,
        response_format=json_response_format("repair", REPAIR_SCHEMA),
    )
    log_llm_exchange("response", response, stage="repair", section_id=section.section_id, logger=logger)
    payload = extract_json_payload(response)
    if not isinstance(payload, dict):
        raise ValueError("Repair response did not return a JSON object.")
    return payload


def _persist_draft_section(
    session: Session,
    *,
    tenant_id,
    run_id,
    section_id: str,
    text: str,
    summary: str | None,
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
        row.section_summary = summary
        row.updated_at = now
    else:
        row = DraftSectionRow(
            tenant_id=tenant_id,
            run_id=run_id,
            section_id=section_id,
            text=text,
            section_summary=summary,
            created_at=now,
            updated_at=now,
        )
        session.add(row)
    session.flush()


@observe(name="repair_agent")
@instrument_node("repair")
def repair_agent_node(state: OrchestratorState, session: Session) -> OrchestratorState:
    # Repair emits stage-level events via instrument_node; no additional node-level progress writes.
    if state.repair_attempts >= 1:
        raise ValueError("Repair agent can only run once per draft.")

    state.repair_attempts += 1

    outline_by_id = _load_outline_by_id(state)
    ordered_ids = _load_section_order(state)
    draft_rows = _load_draft_sections(session, tenant_id=state.tenant_id, run_id=state.run_id)
    review_rows = _load_section_reviews(session, tenant_id=state.tenant_id, run_id=state.run_id)

    failing_sections = [
        section_id
        for section_id in ordered_ids
        if review_rows.get(section_id) and review_rows[section_id].verdict != "pass"
    ]
    failing_section_ids = set(failing_sections)
    if not failing_sections:
        return state

    try:
        llm_client = get_llm_client_for_stage("repair", state.llm_provider, state.llm_model, stage_models=state.stage_models)
    except LLMError as exc:
        raise ValueError("LLM repair is required but unavailable.") from exc
    if not llm_client:
        raise ValueError("LLM repair is required but no LLM client is configured.")

    section_texts = {sid: draft_rows[sid].text for sid in draft_rows}
    section_summaries = {
        sid: (draft_rows[sid].section_summary or "")
        for sid in draft_rows
    }

    repair_logs: list[dict] = []

    for section_id in failing_sections:
        section = outline_by_id[section_id]
        review = review_rows.get(section_id)
        issues = _normalize_issues(review.issues_json if review else [])
        issue_indices = {issue["sentence_index"] for issue in issues}

        original_text = section_texts.get(section_id, "")
        original_summary = section_summaries.get(section_id, "")
        if not original_text:
            raise ValueError(f"Draft section missing for {section_id}")

        section_index = ordered_ids.index(section_id)
        prior_summary = None
        if section_index > 0:
            prior_summary = section_summaries.get(ordered_ids[section_index - 1], "")

        # Continuity patch is disabled: modifying passing sections risks reducing their
        # grounding score. Repairs go directly to re-evaluation without touching
        # any section that was not itself failing.
        patch_target_section_id: str | None = None
        patch_target_section: OutlineSection | None = None
        patch_target_text: str | None = None
        patch_target_summary: str | None = None

        section_snippets = _load_section_snippets(
            session,
            tenant_id=state.tenant_id,
            run_id=state.run_id,
            section_id=section_id,
            state_snippets=state.section_evidence_snippets,
        )
        next_snippets: list[EvidenceSnippetRef] = []

        sentence_count = len(_split_into_sentences(original_text))
        has_invalid_indexes = any(
            idx < 0 or idx >= sentence_count for idx in issue_indices
        )

        if not section_snippets:
            revised_text, edits = _remove_issue_sentences(original_text, issue_indices)
            revised_text = _strip_citations(revised_text).replace("  ", " ").strip()
            revised_summary = _summary_from_text(revised_text)
            if has_invalid_indexes:
                revised_text = original_text
                if original_summary:
                    revised_summary = original_summary
            log_entry: dict = {"repaired_section_edits": edits}
        else:
            repair_payload = _repair_with_llm(
                llm_client,
                section=section,
                section_text=original_text,
                section_summary=original_summary,
                prior_summary=prior_summary,
                issues=issues,
                evidence_snippets=section_snippets,
            )
            repaired_id = str(repair_payload.get("section_id", "")).strip()
            if repaired_id and repaired_id != section_id:
                raise ValueError(f"Repair response section_id mismatch for {section_id}")
            revised_text = str(repair_payload.get("revised_text", "")).strip()
            revised_summary = str(repair_payload.get("revised_summary", "")).strip()
            self_check = repair_payload.get("self_check") or {}
            estimated_pct = self_check.get("estimated_grounding_pct", 100)
            if isinstance(estimated_pct, int) and estimated_pct <= 70:
                logger.warning(
                    "Repair self-check below threshold for %s: estimated %d%%",
                    section_id,
                    estimated_pct,
                )
            log_entry = self_check if isinstance(self_check, dict) else {}

        _persist_draft_section(
            session,
            tenant_id=state.tenant_id,
            run_id=state.run_id,
            section_id=section_id,
            text=revised_text,
            summary=revised_summary,
        )
        section_texts[section_id] = revised_text
        section_summaries[section_id] = revised_summary
        if log_entry:
            repair_logs.append(log_entry)

    report_title = (state.outline and state.outline.report_title) or f"Research Report: {state.user_query}"
    draft_lines: list[str] = [f"# {report_title}", ""]
    for section_id in ordered_ids:
        section = outline_by_id[section_id]
        text = section_texts.get(section_id, "")
        draft_lines.append(f"## {section.section_order}. {section.title}")
        draft_lines.append("")
        if text:
            draft_lines.append(text)
        draft_lines.append("")

    state.draft_text = "\n".join(draft_lines).strip() + "\n"
    state.draft_version += 1
    if repair_logs:
        state.repair_edits_json.extend(repair_logs)

    return state
