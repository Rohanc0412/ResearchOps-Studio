"""
Outliner node - creates a structured outline for the report.

Generates a hierarchical outline with sections and subsections.
Each section includes guidance on required evidence.
"""

from __future__ import annotations

import json
import logging
import os
import re
from typing import Any

from sqlalchemy.orm import Session

from researchops_core.observability import instrument_node
from researchops_core.orchestrator.state import (
    OrchestratorState,
    OutlineModel,
    OutlineSection,
)
from researchops_llm import LLMError, get_llm_client

logger = logging.getLogger(__name__)


def _print_llm_exchange(label: str, content: str) -> None:
    if content is None:
        return
    print(f"\n[outline llm {label}]\n{content}\n", flush=True)


@instrument_node("outline")
def outliner_node(state: OrchestratorState, session: Session) -> OrchestratorState:
    """
    Create a structured outline for the report.

    Strategy:
    1. Standard research report structure
    2. Introduction, Methods, Results, Discussion
    3. Customize based on available sources

    Args:
        state: Current orchestrator state
        session: Database session

    Returns:
        Updated state with outline
    """
    user_query = state.user_query
    vetted_sources = state.vetted_sources

    llm_client = None
    require_llm = os.getenv("LLM_OUTLINE_REQUIRED", "true").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
    try:
        llm_client = get_llm_client(state.llm_provider, state.llm_model)
    except LLMError as exc:
        logger.warning("llm_unavailable", extra={"error": str(exc)})
        if require_llm:
            raise ValueError("LLM outline generation is required but unavailable.") from exc

    if llm_client:
        outline = _generate_outline_with_llm(user_query, vetted_sources, llm_client)
        if outline:
            state.outline = outline
            logger.info(
                "outline_llm_complete",
                extra={"run_id": str(state.run_id), "sections": len(outline.sections)},
            )
            return state
        if require_llm:
            raise ValueError("LLM outline generation failed.")

    if require_llm and not llm_client:
        raise ValueError("LLM outline generation is required but no LLM client is configured.")

    outline = _build_default_outline(user_query)
    state.outline = outline
    logger.info(
        "outline_complete",
        extra={"run_id": str(state.run_id), "sections": len(outline.sections)},
    )

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


def _normalize_outline_payload(payload: Any, user_query: str) -> OutlineModel | None:
    if isinstance(payload, list):
        data = {"sections": payload}
    elif isinstance(payload, dict):
        data = payload
    else:
        return None

    sections = data.get("sections") or data.get("outline") or data.get("items")
    if not isinstance(sections, list):
        return None

    normalized_sections: list[OutlineSection] = []

    def normalize_section(raw: Any, parent_id: str | None, index: int) -> None:
        if not isinstance(raw, dict):
            return
        section_id = raw.get("section_id") or raw.get("id") or raw.get("number")
        if isinstance(section_id, int):
            section_id = str(section_id)
        if not isinstance(section_id, str) or not section_id.strip():
            section_id = f"{parent_id}.{index + 1}" if parent_id else str(index + 1)
        section_id = section_id.strip()

        title = raw.get("title") or raw.get("heading") or raw.get("name")
        if not isinstance(title, str) or not title.strip():
            title = f"Section {section_id}"
        title = title.strip()

        description = raw.get("description") or raw.get("summary") or ""
        if not isinstance(description, str):
            description = str(description) if description is not None else ""
        description = description.strip() or title

        required = (
            raw.get("required_evidence")
            or raw.get("requiredEvidence")
            or raw.get("evidence")
            or raw.get("requirements")
            or []
        )
        if isinstance(required, str):
            required_list = [required.strip()] if required.strip() else []
        elif isinstance(required, list):
            required_list = [str(item).strip() for item in required if str(item).strip()]
        else:
            required_list = []

        if not required_list and user_query:
            required_list = [user_query]

        normalized_sections.append(
            OutlineSection(
                section_id=section_id,
                title=title,
                description=description,
                required_evidence=required_list,
            )
        )

        subsections = raw.get("subsections") or raw.get("children") or raw.get("sections")
        if isinstance(subsections, list):
            for sub_index, sub in enumerate(subsections):
                normalize_section(sub, section_id, sub_index)

    for idx, section in enumerate(sections):
        normalize_section(section, None, idx)

    if not normalized_sections:
        return None

    total_estimated_words = (
        data.get("total_estimated_words")
        or data.get("totalEstimatedWords")
        or data.get("total_words")
    )
    try:
        total_words = int(total_estimated_words)
    except (TypeError, ValueError):
        total_words = max(1500, len(normalized_sections) * 200)

    return OutlineModel(sections=normalized_sections, total_estimated_words=total_words)


def _generate_outline_with_llm(
    user_query: str, vetted_sources: list, llm_client
) -> OutlineModel | None:
    source_lines = []
    for source in vetted_sources[:8]:
        title = source.title or "Untitled"
        year = source.year or "n.d."
        source_lines.append(f"- {title} ({year}) [{source.canonical_id}]")

    debug_simple = os.getenv("LLM_OUTLINE_DEBUG_SIMPLE_PROMPT", "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
    if debug_simple:
        prompt = (
            "Return ONLY valid JSON with this schema:\n"
            "{\n"
            '  "sections": [\n'
            '    {"section_id": "1", "title": "Overview", "description": "Short summary", "required_evidence": ["test"]}\n'
            "  ],\n"
            '  "total_estimated_words": 300\n'
            "}\n\n"
            f"Topic: {user_query}\n"
        )
        system = "Return strict JSON only."
        max_tokens = 200
    else:
        prompt = (
            "Create a structured research outline as JSON.\n"
            "Return ONLY valid JSON with this schema:\n"
            "{\n"
            '  "sections": [\n'
            '    {"section_id": "1", "title": "...", "description": "...", "required_evidence": ["..."]}\n'
            "  ],\n"
            '  "total_estimated_words": 3000\n'
            "}\n\n"
            f"Topic: {user_query}\n\n"
            "Sources:\n"
            + "\n".join(source_lines or ["- (no sources available)"])
            + "\n\n"
            "Requirements:\n"
            "- 6 to 8 sections with reasonable numbering (1, 1.1, 2, 2.1, ...)\n"
            "- Each section must include required_evidence keywords\n"
            "- Use clear, non-repetitive titles\n"
        )
        system = "You design structured research outlines as strict JSON."
        max_tokens = 5000
    try:
        _print_llm_exchange("request", prompt)
        response = llm_client.generate(
            prompt,
            system=system,
            max_tokens=max_tokens,
            temperature=0.3,
            response_format="json",
        )
    except LLMError as exc:
        logger.warning(
            "llm_outline_failed",
            extra={"error": str(exc), "attempt": "response_format"},
        )
        try:
            _print_llm_exchange("request", prompt)
            response = llm_client.generate(
                prompt,
                system=system,
                max_tokens=max_tokens,
                temperature=0.3,
            )
        except LLMError as fallback_exc:
            logger.warning(
                "llm_outline_failed",
                extra={"error": str(fallback_exc), "attempt": "no_response_format"},
            )
            return None

    _print_llm_exchange("response", response)

    payload = _extract_json_payload(response)
    if payload is None:
        logger.warning(
            "llm_outline_parse_failed",
            extra={"reason": "no_json_payload", "response_preview": response[:1200]},
        )
        return None

    if isinstance(payload, list):
        payload = {"sections": payload}

    try:
        outline = OutlineModel.model_validate(payload)
    except Exception as exc:
        outline = _normalize_outline_payload(payload, user_query)
        if outline is None:
            logger.warning(
                "llm_outline_invalid",
                extra={"error": str(exc), "response_preview": response[:1200]},
            )
            return None

    if not outline.sections:
        return None
    return outline


def _build_default_outline(user_query: str) -> OutlineModel:
    sections = []

    # 1. Executive Summary
    sections.append(
        OutlineSection(
            section_id="1",
            title="Executive Summary",
            description="High-level overview of key findings and recommendations",
            required_evidence=["key findings", "main conclusions"],
        )
    )

    # 2. Introduction
    sections.append(
        OutlineSection(
            section_id="2",
            title="Introduction",
            description="Background and motivation for the research topic",
            required_evidence=[user_query, f"background {user_query}"],
        )
    )

    sections.append(
        OutlineSection(
            section_id="2.1",
            title="Problem Statement",
            description="Clear articulation of the research problem",
            required_evidence=[f"challenges {user_query}", f"open problems {user_query}"],
        )
    )

    sections.append(
        OutlineSection(
            section_id="2.2",
            title="Research Questions",
            description="Key questions this research aims to answer",
            required_evidence=[user_query],
        )
    )

    # 3. Literature Review
    sections.append(
        OutlineSection(
            section_id="3",
            title="Literature Review",
            description="Survey of existing work and state of the art",
            required_evidence=[f"literature review {user_query}", f"state of the art {user_query}"],
        )
    )

    sections.append(
        OutlineSection(
            section_id="3.1",
            title="Foundational Work",
            description="Seminal papers and early developments",
            required_evidence=[f"foundational {user_query}", f"history {user_query}"],
        )
    )

    sections.append(
        OutlineSection(
            section_id="3.2",
            title="Recent Advances",
            description="Current state of the art and recent breakthroughs",
            required_evidence=[f"recent advances {user_query}", f"latest {user_query}"],
        )
    )

    # 4. Methods and Approaches
    sections.append(
        OutlineSection(
            section_id="4",
            title="Methods and Approaches",
            description="Techniques and methodologies used in this area",
            required_evidence=[f"methods {user_query}", f"techniques {user_query}"],
        )
    )

    sections.append(
        OutlineSection(
            section_id="4.1",
            title="Common Methodologies",
            description="Widely-used approaches and best practices",
            required_evidence=[f"best practices {user_query}", f"standard methods {user_query}"],
        )
    )

    sections.append(
        OutlineSection(
            section_id="4.2",
            title="Novel Techniques",
            description="Innovative or emerging approaches",
            required_evidence=[f"novel {user_query}", f"innovative {user_query}"],
        )
    )

    # 5. Findings and Results
    sections.append(
        OutlineSection(
            section_id="5",
            title="Key Findings",
            description="Main results and insights from the literature",
            required_evidence=[f"results {user_query}", f"findings {user_query}"],
        )
    )

    sections.append(
        OutlineSection(
            section_id="5.1",
            title="Empirical Results",
            description="Experimental findings and benchmarks",
            required_evidence=[f"benchmarks {user_query}", f"evaluation {user_query}"],
        )
    )

    sections.append(
        OutlineSection(
            section_id="5.2",
            title="Theoretical Insights",
            description="Conceptual and theoretical contributions",
            required_evidence=[f"theory {user_query}", f"insights {user_query}"],
        )
    )

    # 6. Applications
    sections.append(
        OutlineSection(
            section_id="6",
            title="Applications and Use Cases",
            description="Practical applications and real-world deployments",
            required_evidence=[f"applications {user_query}", f"use cases {user_query}"],
        )
    )

    # 7. Challenges and Limitations
    sections.append(
        OutlineSection(
            section_id="7",
            title="Challenges and Limitations",
            description="Current obstacles and areas for improvement",
            required_evidence=[f"challenges {user_query}", f"limitations {user_query}"],
        )
    )

    # 8. Future Directions
    sections.append(
        OutlineSection(
            section_id="8",
            title="Future Directions",
            description="Open problems and promising research directions",
            required_evidence=[f"future work {user_query}", f"open problems {user_query}"],
        )
    )

    # 9. Conclusion
    sections.append(
        OutlineSection(
            section_id="9",
            title="Conclusion",
            description="Summary of findings and recommendations",
            required_evidence=["summary", "recommendations"],
        )
    )

    return OutlineModel(
        sections=sections,
        total_estimated_words=3000,  # Rough estimate: ~200 words per section
    )
