# Repair Agent: Rewrite-Mode Prompt with 70% Grounding Self-Check

**Date:** 2026-04-04
**Area:** `backend/services/orchestrator/nodes/repair_agent.py`

---

## Problem

The current repair prompt uses a surgical "fix only sentence N" model. This fails to consistently push sections above the 70% grounding threshold for two reasons:

1. **Sentence index fragility.** The evaluator's LLM counts sentences by its own perception; the repair agent splits by regex (`_split_into_sentences`). When these disagree, the repair fixes the wrong sentence and the issue persists.
2. **Over-constrained.** "Fix ONLY sentences referenced by sentence_index" prevents the LLM from fixing latent issues the evaluator didn't flag, leaving the section stuck just below 70%.

Additionally, dead schema fields (`next_section_id`, `patched_next_text`, `patched_next_summary`) remain in the prompt and schema after the continuity patch was disabled, adding noise and wasted tokens.

---

## Goal

Repair every failing section so its grounding score consistently exceeds 70%, with no reliance on fragile sentence indices.

---

## Design

### 1. New REPAIR_SCHEMA

Remove the three dead continuity-patch fields. Add a `self_check` object:

```json
{
  "type": "object",
  "properties": {
    "section_id": { "type": "string" },
    "revised_text": { "type": "string" },
    "revised_summary": { "type": "string" },
    "self_check": {
      "type": "object",
      "properties": {
        "factual_sentence_count":  { "type": "integer" },
        "supported_sentence_count": { "type": "integer" },
        "estimated_grounding_pct": { "type": "integer" }
      },
      "required": ["factual_sentence_count", "supported_sentence_count", "estimated_grounding_pct"]
    }
  },
  "required": ["section_id", "revised_text", "revised_summary", "self_check"],
  "additionalProperties": false
}
```

`self_check` acts as a forced chain-of-thought step: the LLM must count and verify before it can complete its response.

### 2. New repair prompt

Replace the current surgical prompt with a rewrite-mode prompt:

```
This section FAILED a 70% grounding evaluation. Rewrite it entirely so that it PASSES.

GROUNDING RULE (same definition the evaluator uses):
  grounding_score = supported_factual_sentences / total_factual_sentences × 100
  You MUST achieve grounding_score > 70.
  Transitional sentences with no factual claim are excluded from the count.

Section ID: <section_id>
Section Title: <section_title>
Section Goal: <section_goal>
Prior Section Summary (for narrative transitions only, not as a fact source):
<prior_summary or 'NONE'>

Evaluator found these issues (use as guidance):
<issues_json>

Current section text:
<section_text>

Evidence snippets (the ONLY source of facts you may use):
<snippet_payload>

Rules:
- Every factual sentence MUST be supported by at least one snippet and end with [CITE:snippet_id].
- If a claim cannot be supported by any snippet, remove the sentence.
- You MAY restructure, combine, or reorder sentences.
- Do NOT invent facts not present in the snippets.
- Narrative transitions (no facts, no names, no numbers) may be uncited.
- No headings, bullet lists, or markdown in revised_text.
- Use the exact snippet_id values from the evidence list.
- Multiple citations: separate tokens [CITE:id1] [CITE:id2].
- Citations at the very end of the sentence, after final punctuation.

Self-check (REQUIRED before returning):
1. Count every factual sentence in your revised_text.
2. Verify each one is supported by a provided snippet.
3. Compute: supported / total × 100.
4. If the result is ≤ 70, revise again until it exceeds 70.
5. Report the final counts in self_check.
```

System prompt remains: `"You repair evidence-grounded drafts and return strict JSON only."`

### 3. Response parsing cleanup in `repair_agent_node`

Remove the dead `patched_next_*` parsing block:
- `patched_next_id`, `patched_next_text`, `patched_next_summary` extractions
- The `if patch_target_section_id is not None: raise ValueError(...)` validation

Add a warning log if `self_check.estimated_grounding_pct <= 70`:
```python
self_check = repair_payload.get("self_check") or {}
estimated_pct = self_check.get("estimated_grounding_pct", 100)
if estimated_pct <= 70:
    logger.warning(
        "Repair self-check below threshold for %s: estimated %d%%",
        section_id,
        estimated_pct,
    )
```

### 4. `edits_json` in state

`repair_logs` currently appends `edits_json` from the LLM response. Since the new schema has no `edits_json` field, stop reading it from the payload. `state.repair_edits_json` can instead log the `self_check` dict for observability.

---

## What does NOT change

- Graph routing (`repair_agent → evaluator`) — already correct after Bug #11 fix
- Continuity patch — remains disabled
- No-snippets fallback path (`_remove_issue_sentences`) — unchanged
- DB persistence (`_persist_draft_section`) — unchanged
- `state.draft_text` assembly — unchanged
- Evaluator, writer, tests other than the repair unit tests

---

## Test changes

- Update `StubLLM` responses in `test_repair_routing.py` to return the new schema shape (drop `patched_next_*`, add `self_check`)
- Add a test: when `self_check.estimated_grounding_pct <= 70`, a warning is logged
- Existing pass/fail routing tests remain valid

---

## Success criteria

- Sections that were failing at 65–69% grounding consistently reach >70% after repair
- No passing sections are degraded (enforced by existing test: `test_repair_agent_does_not_modify_passing_section_after_failing_section`)
- All unit tests pass
