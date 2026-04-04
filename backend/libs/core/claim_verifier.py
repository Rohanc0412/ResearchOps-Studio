"""LLM-based nuanced claim verdict classifier."""

from __future__ import annotations

import json
import logging

from core.evaluation import ALLOWED_VERDICTS, CLAIM_VERIFICATION_SCHEMA

logger = logging.getLogger(__name__)

_SYSTEM = "You are an expert research evaluator assessing factual claims against evidence."

_VERIFY_PROMPT = """\
For each numbered claim, examine the evidence snippets and classify it as exactly ONE verdict:
- supported: at least one snippet directly backs the claim
- unsupported: no snippet supports it (may be true, but not in evidence)
- contradicted: a snippet directly opposes the claim — use this only when evidence explicitly contradicts
- overstated: snippets partially support but not the full strength or extent claimed
- missing_citation: claim is likely correct but has no inline citation marker [^N]
- invalid_citation: claim has a citation marker referencing a non-existent snippet

Return ONLY valid JSON:
{{"verdicts": [{{"claim_index": 0, "verdict": "...", "citations": ["snippet_id"], "notes": "brief reason"}}]}}

Rules:
- Every claim index must appear exactly once in verdicts
- citations must be snippet IDs from the list below (empty array if none)
- Never invent snippet IDs

Claims:
{claims_text}

Evidence snippets:
{snippets_json}
"""


class ClaimVerifier:
    """Classifies each claim against evidence snippets with a nuanced verdict."""

    def __init__(self, llm_client) -> None:
        self._llm = llm_client

    def verify(
        self,
        claims: list[str],
        snippets: list[dict],  # [{"id": str, "text": str}]
    ) -> list[dict]:
        """Return one verdict dict per claim. Falls back to 'unsupported' on failure.

        Each result: {"claim_index": int, "claim_text": str, "verdict": str, "citations": list, "notes": str}
        """
        if not claims:
            return []
        try:
            return self._call_llm(claims, snippets)
        except Exception:
            logger.warning("ClaimVerifier: verification failed, defaulting to unsupported", exc_info=True)
            return self._default_results(claims)

    def _call_llm(self, claims: list[str], snippets: list[dict]) -> list[dict]:
        from llm import extract_json_payload

        claims_text = "\n".join(f"{i}. {c}" for i, c in enumerate(claims))
        snippets_payload = [{"id": s["id"], "text": s["text"][:500]} for s in snippets]
        prompt = _VERIFY_PROMPT.format(
            claims_text=claims_text,
            snippets_json=json.dumps(snippets_payload, indent=2),
        )
        response = self._llm.generate(prompt, system=_SYSTEM)
        payload = extract_json_payload(response)
        raw_verdicts = payload.get("verdicts", [])
        return self._normalise(raw_verdicts, claims)

    def _normalise(self, raw: list[dict], claims: list[str]) -> list[dict]:
        by_index = {int(v.get("claim_index", -1)): v for v in raw}
        results = []
        for idx, claim_text in enumerate(claims):
            entry = by_index.get(idx, {})
            verdict = str(entry.get("verdict", "unsupported"))
            if verdict not in ALLOWED_VERDICTS:
                verdict = "unsupported"
            results.append({
                "claim_index": idx,
                "claim_text": claim_text,
                "verdict": verdict,
                "citations": [str(c) for c in entry.get("citations", [])],
                "notes": str(entry.get("notes", "")),
            })
        return results

    def _default_results(self, claims: list[str]) -> list[dict]:
        return [
            {"claim_index": i, "claim_text": c, "verdict": "unsupported", "citations": [], "notes": ""}
            for i, c in enumerate(claims)
        ]
