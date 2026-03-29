"""Shared evaluation constants used by both the orchestrator pipeline and the API evaluation runner."""

from __future__ import annotations

# Metric key constants
METRIC_EVAL_STATUS = "eval_status"
METRIC_EVAL_GROUNDING_PCT = "eval_grounding_pct"

ALLOWED_PROBLEMS: frozenset[str] = frozenset({
    "unsupported",
    "contradicted",
    "missing_citation",
    "invalid_citation",
    "not_in_pack",
    "overstated",
})

GROUNDING_SCHEMA = {
    "type": "object",
    "properties": {
        "section_id": {"type": "string"},
        "grounding_score": {"type": "integer"},
        "verdict": {"type": "string"},
        "issues": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "sentence_index": {"type": "integer"},
                    "problem": {"type": "string"},
                    "notes": {"type": "string"},
                    "citations": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["sentence_index", "problem", "notes", "citations"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["section_id", "grounding_score", "verdict", "issues"],
    "additionalProperties": False,
}
