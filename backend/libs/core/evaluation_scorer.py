"""Weighted claim scoring for evaluation pipeline."""

from __future__ import annotations

_WEIGHTS: dict[str, float] = {
    "supported": 1.0,
    "missing_citation": 0.75,
    "invalid_citation": 0.75,
    "overstated": 0.5,
    "unsupported": 0.0,
    "contradicted": -1.0,
}

_REPAIR_THRESHOLD = 70


class EvaluationScorer:
    """Computes quality_pct, hallucination_rate, and repair decisions from claim verdicts."""

    def section_quality(self, verdicts: list[str]) -> int:
        """Return 0–100 quality score for a single section."""
        if not verdicts:
            return 0
        total = sum(_WEIGHTS.get(v, 0.0) for v in verdicts)
        clamped = max(0.0, min(1.0, total / len(verdicts)))
        return round(clamped * 100)

    def report_quality(self, section_scores: list[int]) -> int:
        """Return 0–100 quality score averaged across all sections."""
        if not section_scores:
            return 0
        return round(sum(section_scores) / len(section_scores))

    def hallucination_rate(self, verdicts: list[str]) -> int:
        """Return 0–100 rate of claims that are unsupported or contradicted."""
        if not verdicts:
            return 0
        bad = sum(1 for v in verdicts if v in ("unsupported", "contradicted"))
        return round(bad / len(verdicts) * 100)

    def repair_needed(self, verdicts: list[str], quality_score: int) -> bool:
        """Return True if the section should be sent to the repair agent."""
        if quality_score < _REPAIR_THRESHOLD:
            return True
        return any(v == "contradicted" for v in verdicts)
