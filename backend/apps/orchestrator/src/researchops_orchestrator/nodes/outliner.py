"""
Outliner node - creates a structured outline for the report.

Generates an LLM-driven outline and enforces hard constraints.
"""

from __future__ import annotations

import json
import os
import re
from typing import Any

from sqlalchemy.orm import Session

from db.models.outline_notes import OutlineNoteRow
from db.models.run_sections import RunSectionRow
from researchops_core.observability import emit_run_event, instrument_node
from researchops_core.orchestrator.state import (
    OrchestratorState,
    OutlineModel,
    OutlineSection,
)
from researchops_llm import LLMError, get_llm_client



def _print_llm_exchange(label: str, content: str) -> None:
    if content is None:
        return
    if os.getenv("OUTLINE_DEBUG") != "1":
        return
    snippet = content[:4000]


@instrument_node("outline")
def outliner_node(state: OrchestratorState, session: Session) -> OrchestratorState:
    """
    Create a structured outline for the report using the LLM only.
    """
    user_query = state.user_query
    vetted_sources = state.vetted_sources

    try:
        llm_client = get_llm_client(state.llm_provider, state.llm_model)
    except LLMError as exc:
        raise ValueError("LLM outline generation is required but unavailable.") from exc

    if not llm_client:
        raise ValueError("LLM outline generation is required but no LLM client is configured.")

    outline = _generate_outline_with_llm(user_query, vetted_sources, llm_client, state.run_id)
    if outline is None:
        raise ValueError("LLM outline generation failed.")

    outline = _normalize_outline(outline)
    errors = _validate_outline(outline, vetted_sources)
    if errors:
        repaired = _repair_outline_with_llm(
            outline,
            errors,
            llm_client,
            state.run_id,
            user_query,
            vetted_sources,
        )
        if repaired is None:
            raise ValueError(f"LLM outline validation failed: {', '.join(errors[:6])}")
        repaired = _normalize_outline(repaired)
        errors = _validate_outline(repaired, vetted_sources)
        if errors:
            raise ValueError(f"LLM outline validation failed: {', '.join(errors[:6])}")
        outline = repaired
    _persist_outline(session, state.tenant_id, state.run_id, outline)

    emit_run_event(
        session=session,
        tenant_id=state.tenant_id,
        run_id=state.run_id,
        event_type="outline.created",
        stage="outline",
        data={"run_id": str(state.run_id), "section_count": len(outline.sections)},
    )

    state.outline = outline
    return state


def _extract_json_payload(text: str) -> dict | list | None:
    if not text:
        return None
    match = re.search(r"```(?:json)?\s*(.*?)\s*```", text, flags=re.IGNORECASE | re.DOTALL)
    cleaned = match.group(1) if match else text
    cleaned = cleaned.strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass

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


def _generate_outline_with_llm(
    user_query: str, vetted_sources: list, llm_client, run_id
) -> OutlineModel | None:
    min_sections, max_sections = _section_count_bounds(vetted_sources)
    source_lines = []
    for source in vetted_sources[:12]:
        title = source.title or "Untitled"
        year = source.year or "n.d."
        abstract = (source.abstract or "").strip().replace("\n", " ")
        if len(abstract) > 220:
            abstract = abstract[:220].rstrip() + "..."
        line = f"- {title} ({year})"
        if abstract:
            line += f": {abstract}"
        source_lines.append(line)

    prompt = (
        "Create a structured report outline grounded in the sources below.\n"
        "Return ONLY valid JSON with this schema:\n"
        "{\n"
        '  "run_id": "...",\n'
        '  "sections": [\n'
        "    {\n"
        '      "section_id": "intro",\n'
        '      "title": "Introduction",\n'
        '      "goal": "2-3 sentences.",\n'
        '      "key_points": ["...", "..."],\n'
        '      "suggested_evidence_themes": ["..."],\n'
        '      "section_order": 1\n'
        "    }\n"
        "  ]\n"
        "}\n\n"
        f"Run ID: {run_id}\n"
        f"Question: {user_query}\n\n"
        "Sources:\n"
        + "\n".join(source_lines or ["- (no sources available)"])
        + "\n\n"
        "Rules:\n"
        f"- Total sections should be {min_sections} to {max_sections}\n"
        "- Introduction must be first and Conclusion must be last\n"
        "- Section titles must be unique\n"
        "- Each section must include 6-10 key_points\n"
        "- suggested_evidence_themes should be keywords/topics\n"
        "- If too few sources, use fewer sections but keep intro+conclusion\n"
        "- Do not include markdown, no backticks, no commentary\n"
    )
    system = "You design grounded report outlines as strict JSON."
    try:
        _print_llm_exchange("request", prompt)
        response = llm_client.generate(
            prompt,
            system=system,
            max_tokens=1400,
            temperature=0.3,
            response_format="json",
        )
    except LLMError as exc:
        try:
            response = llm_client.generate(
                prompt,
                system=system,
                max_tokens=1400,
                temperature=0.3,
            )
        except LLMError as fallback_exc:
            return None

    _print_llm_exchange("response", response)
    payload = _extract_json_payload(response)
    if payload is None:
        return None

    if isinstance(payload, list):
        payload = {"sections": payload}

    try:
        outline = OutlineModel.model_validate(payload)
    except Exception as exc:
        return None

    if not outline.sections:
        return None
    return outline


def _section_count_bounds(vetted_sources: list) -> tuple[int, int]:
    if len(vetted_sources) < 10:
        return 4, 6
    return 6, 10


def _validate_outline(outline: OutlineModel, vetted_sources: list) -> list[str]:
    errors: list[str] = []
    sections = outline.sections
    if not sections:
        return ["Outline must include sections."]

    min_sections, max_sections = _section_count_bounds(vetted_sources)
    if not (min_sections <= len(sections) <= max_sections):
        errors.append("Outline section count is outside required bounds.")

    orders = [section.section_order for section in sections]
    if any(not isinstance(order, int) for order in orders):
        errors.append("All section_order values must be integers.")
    expected_orders = list(range(1, len(sections) + 1))
    if sorted(orders) != expected_orders:
        errors.append("section_order values must be consecutive starting at 1.")
    if orders != expected_orders:
        errors.append("Sections must be ordered by section_order.")

    first = sections[0]
    last = sections[-1]
    if first.section_id != "intro" or first.title.strip().lower() != "introduction":
        errors.append("Introduction must be the first section with section_id=\"intro\".")
    if last.section_id != "conclusion" or last.title.strip().lower() != "conclusion":
        errors.append("Conclusion must be the last section with section_id=\"conclusion\".")

    if len(sections) - 2 < 2:
        errors.append("Outline must include at least two middle sections.")

    titles = [section.title.strip().lower() for section in sections]
    if len(titles) != len(set(titles)):
        errors.append("Section titles must be unique.")

    section_ids = [section.section_id.strip() for section in sections]
    if len(section_ids) != len(set(section_ids)):
        errors.append("Section IDs must be unique.")

    for section in sections:
        if not section.goal.strip():
            errors.append("Each section must include a non-empty goal.")
        sentence_count = _sentence_count(section.goal)
        if sentence_count < 2 or sentence_count > 3:
            errors.append("Each section goal must be 2 to 3 sentences.")
        if len(section.key_points) < 2:
            errors.append("Each section must include at least 2 key_points.")
        if len(section.key_points) < 6 or len(section.key_points) > 10:
            errors.append("Each section must include 6 to 10 key_points.")
        if not section.suggested_evidence_themes:
            errors.append("Each section must include suggested_evidence_themes.")
    return errors


def _normalize_outline(outline: OutlineModel) -> OutlineModel:
    entries: list[dict[str, object]] = []
    for section in outline.sections:
        section_id = str(section.section_id).strip().lower()
        title = str(section.title).strip()
        goal = str(section.goal).strip()
        key_points = _normalize_str_list(section.key_points)
        themes = _normalize_str_list(section.suggested_evidence_themes)
        try:
            section_order = int(section.section_order)
        except (TypeError, ValueError):
            section_order = None

        title_lower = title.lower()
        if section_id in {"introduction", "intro"} or title_lower == "introduction":
            section_id = "intro"
        if section_id in {"summary", "conclusion"} or title_lower == "conclusion":
            section_id = "conclusion"

        entries.append(
            {
                "section_id": section_id,
                "title": title,
                "goal": goal,
                "key_points": key_points,
                "suggested_evidence_themes": themes,
                "section_order": section_order,
            }
        )

    if not entries:
        return outline

    has_all_orders = all(isinstance(entry["section_order"], int) for entry in entries)
    if has_all_orders:
        entries.sort(key=lambda item: int(item["section_order"]))
        expected = list(range(1, len(entries) + 1))
        actual = [int(item["section_order"]) for item in entries]
        if actual != expected:
            for index, item in enumerate(entries, start=1):
                item["section_order"] = index
    else:
        for index, item in enumerate(entries, start=1):
            item["section_order"] = index

    normalized_sections = [
        OutlineSection(
            section_id=entry["section_id"],
            title=entry["title"],
            goal=entry["goal"],
            key_points=entry["key_points"],
            suggested_evidence_themes=entry["suggested_evidence_themes"],
            section_order=entry["section_order"],
        )
        for entry in entries
    ]
    return OutlineModel(sections=normalized_sections, total_estimated_words=outline.total_estimated_words)


def _normalize_str_list(items: list[str]) -> list[str]:
    cleaned: list[str] = []
    for item in items:
        value = str(item).strip()
        if value:
            cleaned.append(value)
    return cleaned


def _repair_outline_with_llm(
    outline: OutlineModel,
    errors: list[str],
    llm_client,
    run_id,
    user_query: str,
    vetted_sources: list,
) -> OutlineModel | None:
    min_sections, max_sections = _section_count_bounds(vetted_sources)
    try:
        payload = outline.model_dump()
    except AttributeError:
        payload = outline.dict()
    payload_json = json.dumps(payload, ensure_ascii=True, indent=2)

    prompt = (
        "Your JSON failed validation for these reasons:\n"
        + "\n".join(f"- {err}" for err in errors)
        + "\n\n"
        "Return corrected JSON matching the schema exactly.\n"
        "Return ONLY valid JSON with this schema:\n"
        "{\n"
        '  "run_id": "...",\n'
        '  "sections": [\n'
        "    {\n"
        '      "section_id": "intro",\n'
        '      "title": "Introduction",\n'
        '      "goal": "2-3 sentences.",\n'
        '      "key_points": ["...", "..."],\n'
        '      "suggested_evidence_themes": ["..."],\n'
        '      "section_order": 1\n'
        "    }\n"
        "  ]\n"
        "}\n\n"
        f"Run ID: {run_id}\n"
        f"Question: {user_query}\n"
        f"Required section count: {min_sections} to {max_sections}\n\n"
        "Previous JSON:\n"
        + payload_json
        + "\n\n"
        "Do not include markdown, no backticks, no commentary.\n"
    )
    system = "You correct report outlines as strict JSON."
    try:
        _print_llm_exchange("repair_request", prompt)
        response = llm_client.generate(
            prompt,
            system=system,
            max_tokens=1400,
            temperature=0.2,
            response_format="json",
        )
    except LLMError as exc:
        try:
            response = llm_client.generate(
                prompt,
                system=system,
                max_tokens=1400,
                temperature=0.2,
            )
        except LLMError as fallback_exc:
            return None

    _print_llm_exchange("repair_response", response)
    payload = _extract_json_payload(response)
    if payload is None:
        return None

    if isinstance(payload, list):
        payload = {"sections": payload}

    try:
        repaired = OutlineModel.model_validate(payload)
    except Exception as exc:
        return None

    if not repaired.sections:
        return None
    return repaired


def _sentence_count(text: str) -> int:
    cleaned = text.strip()
    if not cleaned:
        return 0
    parts = [p for p in re.split(r"(?<=[.!?])\s+", cleaned) if p.strip()]
    return len(parts)


def _persist_outline(session: Session, tenant_id, run_id, outline: OutlineModel) -> None:
    session.query(OutlineNoteRow).filter(
        OutlineNoteRow.tenant_id == tenant_id,
        OutlineNoteRow.run_id == run_id,
    ).delete()
    session.query(RunSectionRow).filter(
        RunSectionRow.tenant_id == tenant_id,
        RunSectionRow.run_id == run_id,
    ).delete()

    for section in outline.sections:
        session.add(
            RunSectionRow(
                tenant_id=tenant_id,
                run_id=run_id,
                section_id=section.section_id,
                title=section.title,
                goal=section.goal,
                section_order=section.section_order,
            )
        )
        session.add(
            OutlineNoteRow(
                tenant_id=tenant_id,
                run_id=run_id,
                section_id=section.section_id,
                notes_json={
                    "key_points": section.key_points,
                    "suggested_evidence_themes": section.suggested_evidence_themes,
                },
            )
        )
    session.flush()
