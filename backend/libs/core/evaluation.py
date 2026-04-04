"""Shared evaluation constants used by both the orchestrator pipeline and the API evaluation runner."""

from __future__ import annotations

# Metric key constants (stored in run_usage_metrics.metric_name)
METRIC_EVAL_STATUS = "eval_status"
METRIC_EVAL_QUALITY_PCT = "eval_quality_pct"
METRIC_EVAL_HALLUCINATION_RATE = "eval_hallucination_rate"
METRIC_EVAL_EVALUATED_AT = "eval_evaluated_at"

ALLOWED_VERDICTS: frozenset[str] = frozenset({
    "supported",
    "unsupported",
    "contradicted",
    "missing_citation",
    "invalid_citation",
    "overstated",
})

CLAIM_VERIFICATION_SCHEMA = {
    "type": "object",
    "properties": {
        "verdicts": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "claim_index": {"type": "integer"},
                    "verdict": {"type": "string"},
                    "citations": {"type": "array", "items": {"type": "string"}},
                    "notes": {"type": "string"},
                },
                "required": ["claim_index", "verdict", "citations", "notes"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["verdicts"],
    "additionalProperties": False,
}
