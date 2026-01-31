"""
Outliner node - creates a structured outline for the report.

Generates an LLM-driven outline and enforces hard constraints.
"""

from __future__ import annotations

import json
import logging
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
from researchops_llm import LLMError, get_llm_client_for_stage, json_response_format

logger = logging.getLogger(__name__)

OUTLINE_SCHEMA = {
    "type": "object",
    "properties": {
        "sections": {
            "type": "array",
            "minItems": 1,
            "items": {
                "type": "object",
                "properties": {
                    "section_id": {"type": "string"},
                    "title": {"type": "string"},
                    "goal": {"type": "string"},
                    "key_points": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                    "suggested_evidence_themes": {"type": "array", "items": {"type": "string"}},
                    "section_order": {"type": "integer"},
                },
                "required": [
                    "section_id",
                    "title",
                    "goal",
                    "key_points",
                    "suggested_evidence_themes",
                    "section_order",
                ],
                "additionalProperties": False,
            },
        }
    },
    "required": ["sections"],
    "additionalProperties": False,
}



def _print_llm_exchange(label: str, content: str) -> None:
    if content is None:
        return
    message = (
        "LLM request sent for outline"
        if "request" in label and "response" not in label
        else "LLM response received for outline"
    )
    log_full = os.getenv("LLM_LOG_FULL", "").strip().lower() in {"1", "true", "yes", "on"}
    if log_full:
        logger.info(f"{message}\n{content}")
        logger.info(
            message,
            extra={
                "event": "pipeline.llm",
                "stage": "outline",
                "label": label,
                "chars": len(content),
            },
        )
        return
    logger.info(
        message,
        extra={
            "event": "pipeline.llm",
            "stage": "outline",
            "label": label,
            "chars": len(content),
            "content": content,
        },
    )


@instrument_node("outline")
def outliner_node(state: OrchestratorState, session: Session) -> OrchestratorState:
    """
    Create a structured outline for the report using the LLM only.
    """
    user_query = state.user_query
    vetted_sources = state.vetted_sources

    try:
        llm_client = get_llm_client_for_stage("outline", state.llm_provider, state.llm_model)
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
        '      "goal": "Describe the section objective.",\n'
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
            response_format=json_response_format("outline", OUTLINE_SCHEMA),
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
        fallback = _fallback_outline_from_text(response, user_query, vetted_sources)
        if fallback:
            logger.warning(
                "Outline JSON missing; reconstructed from text",
                extra={"event": "outline.fallback", "reason": "no_json"},
            )
        return fallback

    if isinstance(payload, list):
        payload = {"sections": payload}

    try:
        outline = OutlineModel.model_validate(payload)
    except Exception as exc:
        fallback = _fallback_outline_from_text(response, user_query, vetted_sources)
        if fallback:
            logger.warning(
                "Outline JSON invalid; reconstructed from text",
                extra={"event": "outline.fallback", "reason": "invalid_json"},
            )
        return fallback

    if not outline.sections:
        return _fallback_outline_from_text(response, user_query, vetted_sources)
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


def _fallback_outline_from_text(
    text: str,
    user_query: str,
    vetted_sources: list,
) -> OutlineModel | None:
    titles = _extract_section_titles(text)
    min_sections, max_sections = _section_count_bounds(vetted_sources)
    target_count = min(max(len(titles), min_sections), max_sections)

    if not titles:
        titles = _default_section_titles(target_count)
    else:
        titles = _ensure_intro_conclusion(titles)
        if len(titles) < min_sections:
            titles.extend(_default_section_titles(min_sections)[len(titles) :])
        titles = titles[:target_count]

    keywords = _collect_keywords(vetted_sources, limit=8)
    sections: list[OutlineSection] = []
    for idx, title in enumerate(titles, start=1):
        section_id = _section_id_from_title(title, idx)
        goal = _section_goal(title, user_query, keywords)
        key_points = _section_key_points(title, user_query, keywords, count=8)
        themes = _section_themes(keywords, count=5)
        sections.append(
            OutlineSection(
                section_id=section_id,
                title=title,
                goal=goal,
                key_points=key_points,
                suggested_evidence_themes=themes,
                section_order=idx,
            )
        )

    return OutlineModel(sections=sections, total_estimated_words=None)


def _extract_section_titles(text: str) -> list[str]:
    if not text:
        return []
    cleaned = re.sub(r"```.*?```", "", text, flags=re.DOTALL)
    titles: list[str] = []
    seen: set[str] = set()
    for line in cleaned.splitlines():
        candidate = line.strip()
        if not candidate:
            continue
        candidate = re.sub(r"^[#\-\*\d\.\)\s]+", "", candidate).strip()
        candidate = re.sub(r"^section\s+\d+\s*[:\-]\s*", "", candidate, flags=re.I).strip()
        if len(candidate) < 3:
            continue
        normalized = candidate.lower()
        if normalized in {"references", "bibliography", "citations"}:
            continue
        if normalized in seen:
            continue
        seen.add(normalized)
        titles.append(candidate)
    return titles


def _default_section_titles(target_count: int) -> list[str]:
    base = [
        "Introduction",
        "Background and Context",
        "Methods and Approaches",
        "Findings and Evidence",
        "Limitations and Risks",
        "Conclusion",
    ]
    extras = [
        "Applications and Use Cases",
        "Open Questions",
        "Future Directions",
        "Practical Implications",
    ]
    if target_count <= len(base):
        return base[:target_count]
    needed = target_count - len(base)
    return base + extras[:needed]


def _ensure_intro_conclusion(titles: list[str]) -> list[str]:
    normalized = [t.strip() for t in titles if t.strip()]
    if not normalized:
        return normalized
    lower = [t.lower() for t in normalized]
    if "introduction" not in lower:
        normalized.insert(0, "Introduction")
    if "conclusion" not in lower:
        normalized.append("Conclusion")
    return normalized


def _section_id_from_title(title: str, index: int) -> str:
    lower = title.strip().lower()
    if lower.startswith("intro") or lower == "introduction":
        return "intro"
    if lower.startswith("conclusion") or lower == "summary":
        return "conclusion"
    slug = re.sub(r"[^a-z0-9]+", "_", lower).strip("_")
    return slug or f"section_{index}"


def _section_goal(title: str, user_query: str, keywords: list[str]) -> str:
    hint = ", ".join(keywords[:2]) if keywords else "the available evidence"
    return (
        f"Clarify the purpose of {title.lower()} in answering the question about {user_query}. "
        f"Highlight how this section uses themes like {hint} to frame the discussion."
    )


def _section_key_points(
    title: str, user_query: str, keywords: list[str], *, count: int
) -> list[str]:
    points: list[str] = []
    seeds = keywords[:max(3, min(len(keywords), 6))]
    if not seeds:
        seeds = ["scope", "evidence", "implications"]
    templates = [
        f"Define how {title.lower()} relates to {user_query}.",
        f"Summarize key evidence about {seeds[0]}.",
        f"Explain notable patterns or trends in {seeds[1]}.",
        f"Describe limitations or gaps around {seeds[2]}.",
        f"Connect {title.lower()} to practical impacts.",
        f"Identify open questions that remain unresolved.",
        f"Compare viewpoints that shape this section.",
        f"Outline why these points matter for the final report.",
    ]
    for item in templates:
        if len(points) >= count:
            break
        points.append(item)
    return points[:count]


def _section_themes(keywords: list[str], *, count: int) -> list[str]:
    if not keywords:
        return ["evidence", "methods", "trends", "risks", "implications"][:count]
    return keywords[:count]


def _collect_keywords(vetted_sources: list, limit: int = 8) -> list[str]:
    text = " ".join(
        [
            str(getattr(source, "title", "") or "")
            for source in vetted_sources or []
        ]
    )
    text += " " + " ".join(
        [
            str(getattr(source, "abstract", "") or "")
            for source in vetted_sources or []
        ]
    )
    tokens = re.findall(r"[a-zA-Z][a-zA-Z0-9\-]{2,}", text.lower())
    stop = {
        "the",
        "and",
        "for",
        "with",
        "that",
        "from",
        "this",
        "into",
        "about",
        "using",
        "based",
        "study",
        "research",
        "analysis",
        "approach",
        "methods",
        "results",
        "paper",
        "model",
        "models",
    }
    counts: dict[str, int] = {}
    for token in tokens:
        if token in stop:
            continue
        counts[token] = counts.get(token, 0) + 1
    ranked = sorted(counts.items(), key=lambda item: item[1], reverse=True)
    return [word for word, _ in ranked[:limit]]


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
        '      "goal": "Describe the section objective.",\n'
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
