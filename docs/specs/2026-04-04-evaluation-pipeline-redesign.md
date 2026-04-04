# Evaluation Pipeline Redesign

**Date:** 2026-04-04  
**Status:** Approved  

---

## Problem

The current evaluation pipeline produces misleading metrics. With 4/6 sections failing, the dashboard can display 90% Grounding Score and 98% Answer Faithfulness because:

- **Grounding score** is an arithmetic average of LLM-assigned 0–100 scores per section. A failing section can score 75 before being force-failed, inflating the average.
- **Answer faithfulness** is `supported_claims / total_claims` globally — a section with 1 unsupported claim out of 10 fails the section but contributes 90% to the ratio.
- **Sections passed** is the only honest metric but is buried as the third number.

The three metrics are independent and can give contradictory impressions.

---

## Goals

1. Replace the three current metrics with two that accurately represent report quality.
2. Primary display: **what percentage of this report can I trust?**
3. Secondary display: **what is the hallucination rate?**
4. Reduce LLM call count from `4N + M` to `2N + 2M` (N = sections, M = repaired sections).

---

## Metrics

### Quality Score

A single percentage representing how much of the report is trustworthy. Computed from weighted per-claim verdicts.

**Claim verdict weights:**

| Verdict | Weight | Rationale |
|---|---|---|
| `supported` | +1.0 | Fully backed by evidence |
| `missing_citation` | +0.75 | Content likely correct, just undocumented |
| `invalid_citation` | +0.75 | Content likely correct, citation broken |
| `overstated` | +0.5 | Partially supported |
| `unsupported` | 0.0 | No evidential basis |
| `contradicted` | -1.0 | Actively undermines the report |

**Section quality score:**
```
section_quality = clamp(sum(weights) / total_claims, 0.0, 1.0) × 100
```

**Report quality score:**
```
quality_pct = average(section_quality_scores)
```

### Hallucination Rate

The fraction of claims with no evidentiary basis.

```
hallucination_rate = (contradicted_claims + unsupported_claims) / total_claims × 100
```

Computed at report level only. Not broken down per section in the UI.

---

## Framework Split

Two frameworks handle different stages of the pipeline:

| Framework | Stage | Purpose |
|---|---|---|
| **RAGAS** | Pipeline evaluation | Atomic claim extraction + binary verification for repair trigger |
| **DeepEval** | Manual evaluation | Nuanced per-claim verdict classification for quality score + hallucination rate |

### Why RAGAS for pipeline eval

The pipeline needs a fast, good-enough quality signal to decide which sections to repair. RAGAS faithfulness provides atomic claim decomposition (better than sentence-level) and binary supported/not-supported in a single call. Nuanced verdicts are not required at this stage.

### Why DeepEval for manual eval

DeepEval's `FaithfulnessMetric` returns per-claim nuanced verdicts (supported, unsupported, contradicted, overstated, missing_citation, invalid_citation) — matching the six verdict types the custom scoring layer requires. Manual evaluation is the user-facing pass where accuracy matters most.

---

## Pipeline Flow

```
Research pipeline runs
        │
        ▼
[RAGAS faithfulness] per section
  • Atomically extracts claims from section text
  • Binary verifies each claim against evidence snippets
  • 1 LLM call per section
        │
        ▼
Repair trigger check (internal, not user-facing):
  quality_score < 70  OR  any claim verdict == "contradicted"
        │
        ├── Section PASSES
        │       └── Cache claims from RAGAS output → section_claims table
        │
        └── Section FAILS
                ├── Repair agent rewrites section (1 LLM call)
                └── Re-extract claims via RAGAS (1 LLM call)
                        └── Cache updated claims → section_claims table
        │
        ▼
All sections have cached claims in section_claims table
        │
        ▼
User triggers manual evaluation
        │
        ▼
[DeepEval FaithfulnessMetric] per section
  • Loads cached claims from section_claims table
  • Verifies each claim against evidence snippets
  • Returns nuanced verdict per claim
  • 1 LLM call per section
        │
        ▼
Custom scoring layer
  • Apply verdict weights → section_quality_score
  • Average section scores → quality_pct
  • Count contradicted + unsupported → hallucination_rate
        │
        ▼
Store results → evaluation_passes, evaluation_pass_sections, run_usage_metrics
```

---

## LLM Call Count

RAGAS faithfulness makes 2 internal LLM calls per section (claim extraction + binary verification). DeepEval makes 1 call per section.

| Phase | Formula | N=6, M=4 |
|---|---|---|
| Pipeline eval (RAGAS, 2 calls/section) | 2N | 12 |
| Repair | M | 4 |
| Re-extraction after repair (RAGAS, 2 calls/section) | 2M | 8 |
| Manual eval (DeepEval, 1 call/section) | N | 6 |
| **Total** | **3N + 3M** | **30** |

**Current total:** `4N + M = 28`.

Note: at high repair rates (M close to N), the new design is comparable to current. The primary gain is accuracy and reduced complexity, not raw LLM call reduction. At low repair rates (M ≈ 0), new design costs 3N vs current 4N.

---

## Claim Caching

A new `section_claims` table stores extracted claims per section, populated by the pipeline and reused by manual evaluation.

Claims are always extracted from the **final version** of section text:
- Sections that **pass** pipeline eval: claims cached from RAGAS output immediately.
- Sections that **fail and get repaired**: claims re-extracted via RAGAS after repair completes.

If claims are stale (edge case: section edited manually post-pipeline), manual evaluation re-extracts before verifying.

---

## Repair Trigger

The repair trigger is an **internal implementation detail** — not stored as a user-facing metric, not displayed in the UI.

**Rule:**
```
repair_needed = (ragas_quality_score < 70) OR (any claim is "contradicted")
```

The `contradicted` override ensures that sections actively contradicting their evidence are always repaired, even if the overall quality score is above threshold.

---

## Data Model Changes

### New table: `section_claims`

| Column | Type | Notes |
|---|---|---|
| `id` | UUID | PK |
| `tenant_id` | UUID | |
| `run_id` | UUID | FK to runs |
| `section_id` | str(100) | |
| `claim_index` | int | Order within section |
| `claim_text` | text | Atomic factual claim |
| `extracted_at` | timestamp | |

Unique constraint: `(tenant_id, run_id, section_id, claim_index)`

### `evaluation_passes` changes

| Remove | Add |
|---|---|
| `grounding_pct` (int) | `quality_pct` (int) |
| `faithfulness_pct` (int) | `hallucination_rate` (int, 0–100) |

### `evaluation_pass_sections` changes

| Remove | Add |
|---|---|
| `grounding_score` (int) | `quality_score` (int) |
| `verdict` (str: pass/fail) | *(removed)* |
| `issues_json` | `claims_json` — array of `{claim_index, claim_text, verdict, citations, notes}` |

### `run_usage_metrics` changes

| Remove | Add |
|---|---|
| `eval_grounding_pct` | `eval_quality_pct` |
| `eval_faithfulness_pct` | `eval_hallucination_rate` |
| `eval_sections_passed` | *(removed)* |
| `eval_sections_total` | *(removed)* |

### `section_reviews` table

The existing `section_reviews` table (latest review per section) is retired. Its role is replaced by `section_claims` (claim storage) and `evaluation_pass_sections` (per-pass results).

---

## Shared Scoring Module

Both the pipeline evaluator (`evaluator.py`) and manual runner (`evaluation_runner.py`) use a shared `EvaluationScorer` class:

```python
class EvaluationScorer:
    WEIGHTS = {
        "supported": 1.0,
        "missing_citation": 0.75,
        "invalid_citation": 0.75,
        "overstated": 0.5,
        "unsupported": 0.0,
        "contradicted": -1.0,
    }

    def section_quality(self, verdicts: list[str]) -> int:
        """Returns 0–100 quality score for a section."""

    def report_quality(self, section_scores: list[int]) -> int:
        """Returns 0–100 quality score for the full report."""

    def hallucination_rate(self, all_verdicts: list[str]) -> int:
        """Returns 0–100 hallucination rate across the report."""

    def repair_needed(self, verdicts: list[str], quality_score: int) -> bool:
        """Returns True if section should be sent to repair agent."""
```

Scores are identical regardless of whether evaluation was triggered manually or by the pipeline.

---

## What Is Removed

- Grounding LLM prompt (section → 0–100 score)
- Faithfulness claim extraction prompt (custom)
- Faithfulness verification prompt (custom)
- Binary pass/fail verdict per section
- `grounding_pct`, `faithfulness_pct` metrics
- `sections_passed`, `sections_total` metrics
- `section_reviews` table (replaced by `section_claims`)
- `section_review_issues` table
- `section_review_issue_citations` table

---

## What Is Added

- `ragas` Python dependency
- `deepeval` Python dependency
- `section_claims` DB table + migration
- `EvaluationScorer` shared module
- RAGAS claim extraction step in pipeline evaluator
- DeepEval verification step in manual evaluation runner
- Post-repair claim re-extraction step in orchestrator

---

## Assumptions to Verify Before Implementation

1. **DeepEval verdict types** — the spec assumes `FaithfulnessMetric` returns all six verdict types: `supported`, `unsupported`, `contradicted`, `overstated`, `missing_citation`, `invalid_citation`. Verify against DeepEval's current API. If it only returns binary verdicts, a custom LLM prompt replaces the DeepEval call while RAGAS is still used for extraction.

2. **RAGAS claim output format** — claims extracted by RAGAS must be accessible as a list of strings for caching in `section_claims`. Verify RAGAS exposes per-statement results (not just an aggregate score) in its current API version.

3. **Stale claim detection** — the spec notes that manual evaluation re-extracts if claims are stale. The detection mechanism (e.g. comparing `section_claims.extracted_at` vs `draft_sections.updated_at`) is left to implementation.

---

## Out of Scope

- Changes to retrieval, writing, or artifact generation phases
- Per-section hallucination breakdown in the UI
- Configurable framework selection per run
- Evaluation of runs that predate this change (historical data remains as-is)
