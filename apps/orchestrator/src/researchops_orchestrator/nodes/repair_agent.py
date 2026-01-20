"""
RepairAgent node - fixes validation errors in the draft.

TARGETED REPAIR: Only modifies failing sections, not full rewrites.
"""

from __future__ import annotations

import json
import logging
import os
import re

from sqlalchemy.orm import Session

from researchops_core.observability import emit_run_event, instrument_node
from researchops_core.orchestrator.state import (
    OrchestratorState,
    RepairPlan,
    ValidationErrorType,
)
from researchops_llm import LLMError, get_llm_client

logger = logging.getLogger(__name__)


def _print_repair_exchange(label: str, content: str) -> None:
    if content is None:
        return
    print(f"\n[repair agent {label}]\n{content}\n", flush=True)


@instrument_node("repair")
def repair_agent_node(state: OrchestratorState, session: Session) -> OrchestratorState:
    """
    Repair validation errors with targeted edits.

    Strategy:
    1. Analyze validation errors
    2. Identify failing claims and sections
    3. Apply targeted fixes (add citations, remove unsupported claims)
    4. Increment draft version

    Args:
        state: Current orchestrator state
        session: Database session

    Returns:
        Updated state with repaired draft
    """
    errors = state.citation_errors
    draft_text = state.draft_text
    claims = state.extracted_claims

    if not errors:
        # No errors to repair
        return state

    # Increment repair attempt counter
    state.repair_attempts += 1

    # Create repair plan
    target_claims = []
    target_sections = set()

    for error in errors:
        if error.claim_id:
            target_claims.append(error.claim_id)
        if error.section_id:
            target_sections.add(error.section_id)

    repair_plan = RepairPlan(
        target_claims=target_claims,
        target_sections=list(target_sections),
        strategy="Remove or modify unsupported claims, add missing citations",
        additional_evidence_needed=False,
    )

    state.repair_plan = repair_plan

    # Emit progress
    emit_run_event(
        session=session,
        tenant_id=state.tenant_id,
        run_id=state.run_id,
        event_type="progress",
        stage="repair",
        data={
            "error_count": len(errors),
            "target_claims": len(target_claims),
            "target_sections": len(target_sections),
            "repair_attempt": state.repair_attempts,
        },
    )

    repaired_draft = draft_text

    llm_client = None
    require_llm = os.getenv("LLM_REPAIR_REQUIRED", "true").strip().lower() in {
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
            raise ValueError("LLM repair is required but unavailable.") from exc

    if llm_client:
        repaired_llm = _repair_with_llm(
            draft_text=draft_text,
            errors=errors,
            claims=claims,
            evidence_snippets=state.evidence_snippets,
            llm_client=llm_client,
        )
        if repaired_llm:
            repaired_draft = repaired_llm
            state.draft_text = repaired_draft
            state.draft_version += 1
            logger.info(
                "repair_complete_llm",
                extra={
                    "run_id": str(state.run_id),
                    "repair_attempt": state.repair_attempts,
                    "draft_version": state.draft_version,
                },
            )
            return state
        if require_llm:
            raise ValueError("LLM repair failed to produce a revision.")

    if require_llm and not llm_client:
        raise ValueError("LLM repair is required but no LLM client is configured.")

    # Apply repairs (rule-based fallback)
    for error in errors:
        if error.error_type == ValidationErrorType.MISSING_CITATION:
            # Find claim and try to add a citation
            claim = next((c for c in claims if c.claim_id == error.claim_id), None)
            if claim:
                repaired_draft = _add_citation_to_claim(
                    repaired_draft, claim, state.evidence_snippets
                )

        elif error.error_type == ValidationErrorType.INVALID_CITATION:
            # Remove invalid citation
            if error.citation_id:
                repaired_draft = _remove_invalid_citation(repaired_draft, error.citation_id)

        elif error.error_type in [
            ValidationErrorType.UNSUPPORTED_CLAIM,
            ValidationErrorType.CONTRADICTED_CLAIM,
        ]:
            # Remove or soften the claim
            claim = next((c for c in claims if c.claim_id == error.claim_id), None)
            if claim:
                repaired_draft = _soften_claim(repaired_draft, claim)

    # Update state
    state.draft_text = repaired_draft
    state.draft_version += 1
    logger.info(
        "repair_complete",
        extra={
            "run_id": str(state.run_id),
            "repair_attempt": state.repair_attempts,
            "draft_version": state.draft_version,
        },
    )

    return state


def _extract_json_list(text: str) -> list[dict] | None:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`").strip()
    start = cleaned.find("[")
    end = cleaned.rfind("]")
    if start == -1 or end == -1 or end <= start:
        return None
    try:
        data = json.loads(cleaned[start : end + 1])
    except json.JSONDecodeError:
        return None
    if not isinstance(data, list):
        return None
    return [item for item in data if isinstance(item, dict)]


def _select_snippets_for_claim(claim_text: str, evidence_snippets: list, max_snippets: int = 3) -> list:
    claim_lower = claim_text.lower()
    keywords = [w for w in claim_lower.split() if len(w) > 4]
    scored = []
    for snippet in evidence_snippets:
        snippet_lower = snippet.text.lower()
        matches = sum(1 for kw in keywords if kw in snippet_lower)
        if matches:
            scored.append((matches, snippet))
    scored.sort(key=lambda x: x[0], reverse=True)
    return [s for _, s in scored[:max_snippets]] or evidence_snippets[:max_snippets]


def _replace_sentence(draft: str, claim_text: str, new_sentence: str | None) -> str:
    claim_text_escaped = re.escape(claim_text[:50])
    pattern = re.compile(
        rf"(?P<prefix>^|[.!?]\s+)(?P<sentence>[^.!?]*{claim_text_escaped}[^.!?]*[.!?])",
        re.DOTALL,
    )

    def replacer(match):
        prefix = match.group("prefix") or ""
        if new_sentence is None:
            return prefix
        sentence = new_sentence.strip()
        if sentence and sentence[-1] not in ".!?":
            sentence += "."
        return f"{prefix}{sentence}"

    return pattern.sub(replacer, draft, count=1)


def _repair_with_llm(
    *, draft_text: str, errors, claims, evidence_snippets, llm_client
) -> str | None:
    claim_lookup = {c.claim_id: c for c in claims}
    issues = []
    for error in errors[:10]:
        claim = claim_lookup.get(error.claim_id)
        if not claim:
            continue
        snippets = _select_snippets_for_claim(claim.text, evidence_snippets, max_snippets=3)
        issues.append(
            {
                "claim_id": claim.claim_id,
                "claim_text": claim.text,
                "section_id": claim.section_id,
                "error_type": error.error_type.value,
                "evidence": [
                    {"snippet_id": str(s.snippet_id), "text": s.text[:240]} for s in snippets
                ],
            }
        )

    if not issues:
        return None

    prompt = (
        "You are repairing a research draft. Fix ONLY the problematic claims below.\n"
        "Return ONLY JSON: a list of edits. Each edit has:\n"
        '- "claim_id": string\n'
        '- "action": "replace" or "remove"\n'
        '- "replacement": the revised sentence (include [CITE:...] tokens) if action=replace\n\n'
        "Rules:\n"
        "- Use only the provided evidence snippets.\n"
        "- Paraphrase; do not copy snippet text verbatim.\n"
        "- If the claim cannot be supported, choose action=remove.\n\n"
        "Issues:\n"
        + json.dumps(issues, indent=2)
    )
    system = "You repair research drafts and return strict JSON edits."
    _print_repair_exchange("request", prompt)
    try:
        response = llm_client.generate(
            prompt,
            system=system,
            max_tokens=5000,
            temperature=0.3,
            response_format="json",
        )
    except LLMError as exc:
        logger.warning("llm_repair_failed", extra={"error": str(exc)})
        return None

    _print_repair_exchange("response", response)
    edits = _extract_json_list(response)
    if not edits:
        logger.warning(
            "llm_repair_parse_failed",
            extra={"reason": "no_json", "response_preview": response[:1200]},
        )
        return None

    updated = draft_text
    for edit in edits:
        claim_id = edit.get("claim_id")
        if claim_id not in claim_lookup:
            continue
        action = str(edit.get("action", "")).strip().lower()
        if action not in {"replace", "remove"}:
            continue
        replacement = edit.get("replacement")
        if action == "replace" and not isinstance(replacement, str):
            continue
        if action == "remove":
            replacement = None

        updated = _replace_sentence(updated, claim_lookup[claim_id].text, replacement)

    return updated


def _add_citation_to_claim(draft: str, claim, evidence_snippets: list) -> str:
    """
    Add a citation to a claim missing one.

    Find the best matching snippet and insert [CITE:snippet_id].

    Args:
        draft: Current draft text
        claim: Claim object
        evidence_snippets: Available evidence snippets

    Returns:
        Modified draft text
    """
    # Find best matching snippet (simple keyword matching)
    claim_lower = claim.text.lower()
    best_snippet = None
    best_score = 0.0

    for snippet in evidence_snippets:
        snippet_lower = snippet.text.lower()
        # Count keyword matches
        keywords = [w for w in claim_lower.split() if len(w) > 4]
        matches = sum(1 for kw in keywords if kw in snippet_lower)
        score = matches / len(keywords) if keywords else 0

        if score > best_score:
            best_score = score
            best_snippet = snippet

    if best_snippet and best_score > 0.2:
        # Insert citation at end of claim sentence
        citation = f" [CITE:{best_snippet.snippet_id}]"

        # Find claim in draft
        claim_text_escaped = re.escape(claim.text[:50])  # Use first 50 chars
        pattern = re.compile(rf"{claim_text_escaped}.*?\.", re.DOTALL)

        def replacer(match):
            sentence = match.group(0)
            # Add citation before the period
            if citation not in sentence:
                return sentence[:-1] + citation + "."
            return sentence

        draft = pattern.sub(replacer, draft, count=1)

    return draft


def _remove_invalid_citation(draft: str, citation_id: str) -> str:
    """
    Remove an invalid citation from the draft.

    Args:
        draft: Current draft text
        citation_id: Citation ID to remove

    Returns:
        Modified draft text
    """
    # Pattern: [CITE:citation_id]
    pattern = rf"\[CITE:{re.escape(citation_id)}\]\s*"
    draft = re.sub(pattern, "", draft)

    return draft


def _soften_claim(draft: str, claim) -> str:
    """
    Soften an unsupported or contradicted claim.

    Add hedging language or remove the claim.

    Args:
        draft: Current draft text
        claim: Claim object

    Returns:
        Modified draft text
    """
    # Find the full sentence containing the claim to avoid repeated hedge insertions
    claim_text_escaped = re.escape(claim.text[:50])
    pattern = re.compile(
        rf"(?P<prefix>^|[.!?]\s+)(?P<sentence>[^.!?]*{claim_text_escaped}[^.!?]*\.)",
        re.DOTALL,
    )

    # Hedging prefixes
    hedges = [
        "Some research suggests that ",
        "Preliminary evidence indicates that ",
        "Further investigation is needed, but ",
    ]

    def replacer(match):
        prefix = match.group("prefix") or ""
        sentence = match.group("sentence") or match.group(0)
        sentence_lower = sentence.lower()
        # Check if already hedged anywhere in the full sentence
        if any(hedge.lower() in sentence_lower for hedge in hedges):
            return match.group(0)
        # Add hedge once to the full sentence
        import random

        hedge = random.choice(hedges)
        return f"{prefix}{hedge}{sentence.lstrip()}"

    draft = pattern.sub(replacer, draft, count=1)

    return draft
