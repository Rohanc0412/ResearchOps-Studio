"""
RepairAgent node - repairs failed sections and patches continuity.

Uses an LLM to repair only failing sentences in a section and to
patch the first two sentences of the next section for continuity.
"""

from __future__ import annotations

from datetime import datetime
import json
import re

from sqlalchemy.orm import Session

from db.models.draft_sections import DraftSectionRow
from db.models.section_evidence import SectionEvidenceRow
from db.models.section_reviews import SectionReviewRow
from db.models.snippets import SnippetRow
from db.models.snapshots import SnapshotRow
from researchops_core.observability import instrument_node
from researchops_core.orchestrator.state import (
    EvidenceSnippetRef,
    OrchestratorState,
    OutlineSection,
)
from researchops_llm import LLMError, get_llm_client

_CITATION_PATTERN = re.compile(r"\[CITE:([a-f0-9-]+)\]")
_ALLOWED_ISSUE_TYPES = {
    "unsupported",
    "overstated",
    "missing_citation",
    "invalid_citation",
    "not_in_pack",
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


def _validate_section_summary(summary: str) -> None:
    cleaned = (summary or "").strip()
    if not cleaned:
        raise ValueError("section_summary is empty.")

    lines = [line.strip() for line in cleaned.splitlines() if line.strip()]
    if len(lines) != 2:
        raise ValueError("section_summary must be exactly 2 non-empty lines.")
    if "[CITE:" in cleaned:
        raise ValueError("section_summary must not include citations.")
    for line in lines:
        if line[-1] not in ".!?":
            raise ValueError("Each section_summary line must end with punctuation.")


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
    _validate_section_summary(summary)
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
            if next_non_issue < len(original_sentences) and revised_sentences[j] == original_sentences[next_non_issue]:
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
        remaining_non_issue = [idx for idx in range(i, len(original_sentences)) if idx not in issue_indices]
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
    first_sentence = f"Building on {summary_line.lower()}, this section transitions into {next_section_title}."
    second_sentence = "The following discussion connects the earlier summary to the next set of evidence."
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
    next_section: OutlineSection,
    next_section_text: str,
    next_section_summary: str | None,
    next_section_snippets: list[EvidenceSnippetRef],
) -> dict:
    prompt = (
        "Repair the current section and apply a continuity patch to the next section.\n"
        "Return ONLY JSON with this schema:\n"
        "{\n"
        '  "section_id": "...",\n'
        '  "revised_text": "...",\n'
        '  "revised_summary": "line1\\nline2",\n'
        '  "next_section_id": "...",\n'
        '  "patched_next_text": "...",\n'
        '  "patched_next_summary": "line1\\nline2",\n'
        '  "edits_json": {\n'
        '    "repaired_section_edits": [\n'
        '      { "sentence_index": 0, "before": "...", "after": "...", "change_type": "..." }\n'
        "    ],\n"
        '    "continuity_patch": {\n'
        '      "next_section_id": "...",\n'
        '      "before_first_two_sentences": "...",\n'
        '      "after_first_two_sentences": "..."\n'
        "    }\n"
        "  }\n"
        "}\n\n"
        f"Current Section ID: {section.section_id}\n"
        f"Current Section Title: {section.title}\n"
        f"Current Section Text:\n{section_text}\n\n"
        f"Current Section Summary:\n{section_summary}\n\n"
        "Prior Section Summary (if any):\n"
        f"{prior_summary or 'NONE'}\n\n"
        "Evaluator Issues:\n"
        + json.dumps(issues, indent=2, ensure_ascii=True)
        + "\n\n"
        "Evidence pack snippets for current section:\n"
        + json.dumps(_build_snippet_payload(evidence_snippets), indent=2, ensure_ascii=True)
        + "\n\n"
        f"Next Section ID: {next_section.section_id}\n"
        f"Next Section Title: {next_section.title}\n"
        f"Next Section Text:\n{next_section_text}\n\n"
        f"Next Section Summary:\n{next_section_summary or ''}\n\n"
        "Evidence pack snippets for next section:\n"
        + json.dumps(_build_snippet_payload(next_section_snippets), indent=2, ensure_ascii=True)
        + "\n\n"
        "Rules:\n"
        "- Fix ONLY sentences referenced by sentence_index.\n"
        "- Do NOT modify sentences outside those indexes.\n"
        "- Do NOT add new claims not present in the original section text.\n"
        "- If unsupported: remove or rewrite to match evidence.\n"
        "- If overstated: soften language and add citations if factual.\n"
        "- If missing_citation: add citation tokens at the end.\n"
        "- If invalid_citation or not_in_pack: replace with valid snippet_id or remove.\n"
        "- Every factual sentence must end with citation token(s).\n"
        "- Citations only at the end of sentences.\n"
        "- No headings, bullet lists, or markdown.\n\n"
        "Micro-summary rules:\n"
        "- Exactly 2 lines, one sentence per line.\n"
        "- No citations.\n"
        "- No new facts not in revised_text.\n\n"
        "Continuity patch rules (next section):\n"
        "- ALWAYS patch the first two sentences only.\n"
        "- Keep every character after sentence 1 identical to the original next_section_text.\n"
        "- Do NOT introduce new claims.\n"
        "- If patched sentences are factual, cite using next section evidence pack.\n"
        "- Narrative transitions may be uncited.\n"
        "- Update patched_next_summary only if needed for consistency.\n"
        "- Do NOT include commentary outside JSON.\n"
    )
    system = "You repair evidence-grounded drafts and return strict JSON only."
    _log_llm_exchange("request", section.section_id, prompt)
    response = llm_client.generate(
        prompt,
        system=system,
        max_tokens=1800,
        temperature=0.2,
        response_format="json",
    )
    _log_llm_exchange("response", section.section_id, response)
    payload = _extract_json_payload(response)
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
    now = datetime.utcnow()
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


@instrument_node("repair")
def repair_agent_node(state: OrchestratorState, session: Session) -> OrchestratorState:
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
    if not failing_sections:
        return state

    try:
        llm_client = get_llm_client(state.llm_provider, state.llm_model)
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

        if section_index + 1 >= len(ordered_ids):
            raise ValueError(f"Next section missing for continuity patch after {section_id}")
        next_section_id = ordered_ids[section_index + 1]
        next_section = outline_by_id[next_section_id]
        next_text = section_texts.get(next_section_id, "")
        next_summary = section_summaries.get(next_section_id, "")
        if not next_text:
            raise ValueError(f"Draft section missing for {next_section_id}")

        section_snippets = _load_section_snippets(
            session,
            tenant_id=state.tenant_id,
            run_id=state.run_id,
            section_id=section_id,
            state_snippets=state.section_evidence_snippets,
        )
        next_snippets = _load_section_snippets(
            session,
            tenant_id=state.tenant_id,
            run_id=state.run_id,
            section_id=next_section_id,
            state_snippets=state.section_evidence_snippets,
        )

        sentence_count = len(_split_into_sentences(original_text))
        has_invalid_indexes = any(
            idx < 0 or idx >= sentence_count for idx in issue_indices
        )

        if not section_snippets:
            revised_text, edits = _remove_issue_sentences(original_text, issue_indices)
            revised_text = _strip_citations(revised_text).replace("  ", " ").strip()
            revised_summary = _summary_from_text(revised_text)
            patched_next_text, patched_next_summary, patch_log = _patch_next_section_narrative(
                next_section_id=next_section_id,
                next_section_text=next_text,
                revised_summary=revised_summary,
                next_section_title=next_section.title,
            )
            edits_json = {
                "repaired_section_edits": edits,
                "continuity_patch": patch_log,
            }
        else:
            repair_payload = _repair_with_llm(
                llm_client,
                section=section,
                section_text=original_text,
                section_summary=original_summary,
                prior_summary=prior_summary,
                issues=issues,
                evidence_snippets=section_snippets,
                next_section=next_section,
                next_section_text=next_text,
                next_section_summary=next_summary,
                next_section_snippets=next_snippets,
            )

            repaired_id = str(repair_payload.get("section_id", "")).strip()
            if repaired_id and repaired_id != section_id:
                raise ValueError(f"Repair response section_id mismatch for {section_id}")
            revised_text = str(repair_payload.get("revised_text", "")).strip()
            revised_summary = str(repair_payload.get("revised_summary", "")).strip()
            patched_next_id = str(repair_payload.get("next_section_id", "")).strip()
            if patched_next_id and patched_next_id != next_section_id:
                raise ValueError(
                    f"Repair response next_section_id mismatch for {next_section_id}"
                )
            patched_next_text = str(repair_payload.get("patched_next_text", "")).strip()
            patched_next_summary = str(repair_payload.get("patched_next_summary", "")).strip()
            edits_json = (
                repair_payload.get("edits_json") if isinstance(repair_payload, dict) else None
            )

        if has_invalid_indexes:
            revised_text = original_text
            if original_summary:
                revised_summary = original_summary

        allowed_ids = {str(snippet.snippet_id) for snippet in section_snippets}
        _validate_section_text(revised_text, allowed_ids)
        _validate_section_summary(revised_summary)
        if not has_invalid_indexes:
            _validate_repair_scope(original_text, revised_text, issue_indices)
        else:
            if revised_text.strip() != original_text.strip():
                raise ValueError("Invalid issue indexes but section text changed.")

        next_allowed_ids = {str(snippet.snippet_id) for snippet in next_snippets}
        if not next_allowed_ids:
            next_allowed_ids = allowed_ids
        _validate_next_section_patch(next_text, patched_next_text, next_allowed_ids)
        _validate_section_summary(patched_next_summary)

        _persist_draft_section(
            session,
            tenant_id=state.tenant_id,
            run_id=state.run_id,
            section_id=section_id,
            text=revised_text,
            summary=revised_summary,
        )
        _persist_draft_section(
            session,
            tenant_id=state.tenant_id,
            run_id=state.run_id,
            section_id=next_section_id,
            text=patched_next_text,
            summary=patched_next_summary,
        )

        section_texts[section_id] = revised_text
        section_summaries[section_id] = revised_summary
        section_texts[next_section_id] = patched_next_text
        section_summaries[next_section_id] = patched_next_summary

        if isinstance(edits_json, dict):
            repair_logs.append(edits_json)

    draft_lines: list[str] = [f"# Research Report: {state.user_query}", ""]
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
