"""RAGAS-based atomic claim extractor."""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

_EXTRACTION_PROMPT = """\
Extract all distinct atomic factual claims from the section text below.
An atomic claim is the smallest independently verifiable fact.
Break compound sentences into separate claims.
Ignore markdown headings, citation markers like [^1] or [CITE:...], and bibliography text.

Return ONLY valid JSON: {{"claims": ["claim 1", "claim 2", ...]}}

Section text:
{section_text}
"""


class RagasExtractor:
    """Extracts atomic claims from section text using RAGAS-inspired decomposition."""

    def __init__(self, llm_client) -> None:
        self._llm = llm_client

    async def extract(self, section_text: str, contexts: list[str]) -> list[str]:
        """Return deduplicated list of atomic claim strings. Returns [] on failure."""
        try:
            raw = await self._call_ragas(section_text, contexts)
            return list(dict.fromkeys(raw))  # deduplicate preserving order
        except Exception:
            logger.warning("RagasExtractor: claim extraction failed", exc_info=True)
            return []

    async def _call_ragas(self, section_text: str, contexts: list[str]) -> list[str]:
        """Call RAGAS faithfulness claim decomposition.

        Tries the RAGAS library first. Falls back to our own extraction prompt
        if RAGAS does not expose per-statement results in the installed version.
        """
        try:
            return await self._ragas_library_extract(section_text, contexts)
        except Exception:
            logger.debug("RAGAS library extraction unavailable, using fallback prompt")
            return await self._fallback_extract(section_text)

    async def _ragas_library_extract(self, section_text: str, contexts: list[str]) -> list[str]:
        """Use ragas.metrics.Faithfulness to decompose into atomic statements."""
        from ragas import SingleTurnSample
        from ragas.metrics import Faithfulness

        sample = SingleTurnSample(
            user_input="Extract claims from this research section.",
            response=section_text,
            retrieved_contexts=contexts,
        )
        metric = Faithfulness()
        # Score triggers internal statement decomposition
        await metric.single_turn_ascore(sample)
        # Access decomposed statements — attribute name may vary by ragas version
        statements: list[str] = []
        for attr in ("_statements", "statements", "_decomposed_statements"):
            if hasattr(metric, attr):
                raw = getattr(metric, attr)
                if isinstance(raw, list) and raw:
                    statements = [str(s) for s in raw]
                    break
        if not statements:
            raise AttributeError("RAGAS metric did not expose per-statement results")
        return list(dict.fromkeys(statements))  # deduplicate preserving order

    async def _fallback_extract(self, section_text: str) -> list[str]:
        """Extract claims using direct LLM call with structured prompt."""
        from llm import extract_json_payload

        prompt = _EXTRACTION_PROMPT.format(section_text=section_text[:4000])
        response = self._llm.generate(prompt, system="You are a precise fact extraction assistant.")
        payload = extract_json_payload(response)
        claims = payload.get("claims", [])
        return list(dict.fromkeys(str(c) for c in claims if c))
