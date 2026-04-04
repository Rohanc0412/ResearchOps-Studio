# Repair Agent Rewrite-Mode Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the repair agent's surgical sentence-patch prompt with a full-section rewrite that explicitly targets >70% grounding and self-verifies before returning.

**Architecture:** Two files change — `repair_agent.py` (schema + prompt + parsing) and `test_repair_routing.py` (fixtures + new warning test). No other files are touched. All changes are internal to the repair stage; the graph routing and evaluator are already correct.

**Tech Stack:** Python 3.12, pytest, SQLAlchemy (test fixtures use in-memory SQLite via existing `db_session` fixture)

---

### Task 1: Update test fixtures to new schema shape

**Files:**
- Modify: `tests/backend/unit/test_repair_routing.py`

All three `StubLLM` classes in the repair tests return the old schema (`next_section_id`, `patched_next_text`, `patched_next_summary`, `edits_json`). Update them to the new schema (`self_check`). Also update the stale prompt-content assertion. After this task the tests will FAIL — that is expected and confirms the tests are driving the implementation.

- [ ] **Step 1: Update StubLLM in `test_repair_agent_repairs_last_section_without_next_section`**

In `tests/backend/unit/test_repair_routing.py`, replace the `StubLLM.generate` return value (around line 325):

```python
class StubLLM:
    def generate(self, _prompt, **_kwargs):
        return json.dumps(
            {
                "section_id": "conclusion",
                "revised_text": "Conclusion fixed with evidence [CITE:11111111-1111-1111-1111-111111111111].",
                "revised_summary": "Fixed conclusion.\nStill concise.",
                "self_check": {
                    "factual_sentence_count": 1,
                    "supported_sentence_count": 1,
                    "estimated_grounding_pct": 100,
                },
            }
        )
```

- [ ] **Step 2: Update StubLLM in `test_repair_agent_calls_each_failed_section_once_when_adjacent_sections_fail`**

Replace both return values in the two-branch `StubLLM.generate` (around lines 440–493):

```python
class StubLLM:
    def generate(self, prompt, **_kwargs):
        prompts.append(prompt)
        if "Section ID: intro" in prompt:
            return json.dumps(
                {
                    "section_id": "intro",
                    "revised_text": (
                        "Intro fixed with evidence "
                        "[CITE:11111111-1111-1111-1111-111111111111]."
                    ),
                    "revised_summary": "Fixed intro.\nStill concise.",
                    "self_check": {
                        "factual_sentence_count": 1,
                        "supported_sentence_count": 1,
                        "estimated_grounding_pct": 100,
                    },
                }
            )
        return json.dumps(
            {
                "section_id": "methods",
                "revised_text": (
                    "Methods fixed with evidence "
                    "[CITE:22222222-2222-2222-2222-222222222222]."
                ),
                "revised_summary": "Fixed methods.\nStill concise.",
                "self_check": {
                    "factual_sentence_count": 1,
                    "supported_sentence_count": 1,
                    "estimated_grounding_pct": 100,
                },
            }
        )
```

Note: the branch condition changes from `"Current Section ID: intro"` to `"Section ID: intro"` to match the new prompt format.

- [ ] **Step 3: Update prompt assertions in the same test**

Replace the two stale prompt assertions (around lines 619–620):

```python
# Old — remove these two lines:
assert "There is no eligible next section to patch." in prompts[0]
assert "Next Section ID: methods" not in prompts[0]

# New — replace with:
assert "FAILED a 70% grounding evaluation" in prompts[0]
assert "Section ID: intro" in prompts[0]
```

- [ ] **Step 4: Update StubLLM in `test_repair_agent_does_not_modify_passing_section_after_failing_section`**

Replace the `StubLLM.generate` return value (around lines 636–657):

```python
class StubLLM:
    def generate(self, _prompt, **_kwargs):
        return json.dumps(
            {
                "section_id": "intro",
                "revised_text": "Intro fixed with evidence [CITE:11111111-1111-1111-1111-111111111111].",
                "revised_summary": "Fixed intro.\nStill concise.",
                "self_check": {
                    "factual_sentence_count": 1,
                    "supported_sentence_count": 1,
                    "estimated_grounding_pct": 100,
                },
            }
        )
```

- [ ] **Step 5: Run tests and verify they FAIL**

```bash
cd c:/projects/ResearchOps-Studio
python -m pytest tests/backend/unit/test_repair_routing.py -v
```

Expected: 3–4 failures mentioning schema validation or key errors. If all 5 pass something is wrong — the tests are not yet driving the implementation.

---

### Task 2: Update REPAIR_SCHEMA, rewrite `_repair_with_llm`, clean up `repair_agent_node`

**Files:**
- Modify: `backend/services/orchestrator/nodes/repair_agent.py`

Three groups of changes, all in one file:
1. Replace `REPAIR_SCHEMA`
2. Rewrite `_repair_with_llm` (remove `next_section*` params, new prompt)
3. Clean up `repair_agent_node` (remove dead parsing, add self_check warning, restructure no-snippets path)

- [ ] **Step 1: Replace REPAIR_SCHEMA (lines 39–60)**

```python
REPAIR_SCHEMA = {
    "type": "object",
    "properties": {
        "section_id": {"type": "string"},
        "revised_text": {"type": "string"},
        "revised_summary": {"type": "string"},
        "self_check": {
            "type": "object",
            "properties": {
                "factual_sentence_count": {"type": "integer"},
                "supported_sentence_count": {"type": "integer"},
                "estimated_grounding_pct": {"type": "integer"},
            },
            "required": [
                "factual_sentence_count",
                "supported_sentence_count",
                "estimated_grounding_pct",
            ],
        },
    },
    "required": ["section_id", "revised_text", "revised_summary", "self_check"],
    "additionalProperties": False,
}
```

- [ ] **Step 2: Rewrite `_repair_with_llm` (lines 366–472)**

Replace the entire function:

```python
def _repair_with_llm(
    llm_client,
    *,
    section: OutlineSection,
    section_text: str,
    section_summary: str,
    prior_summary: str | None,
    issues: list[dict],
    evidence_snippets: list[EvidenceSnippetRef],
) -> dict:
    prompt = (
        "This section FAILED a 70% grounding evaluation. Rewrite it entirely so that it PASSES.\n\n"
        "GROUNDING RULE (same definition the evaluator uses):\n"
        "  grounding_score = supported_factual_sentences / total_factual_sentences \u00d7 100\n"
        "  You MUST achieve grounding_score > 70.\n"
        "  Transitional sentences with no factual claim are excluded from the count.\n\n"
        f"Section ID: {section.section_id}\n"
        f"Section Title: {section.title}\n"
        f"Section Goal: {section.goal}\n"
        "Prior Section Summary (for narrative transitions only, not as a fact source):\n"
        f"{prior_summary or 'NONE'}\n\n"
        "Evaluator found these issues (use as guidance):\n"
        + json.dumps(issues, indent=2, ensure_ascii=True)
        + "\n\n"
        "Current section text:\n"
        + section_text
        + "\n\n"
        "Evidence snippets (the ONLY source of facts you may use):\n"
        + json.dumps(_build_snippet_payload(evidence_snippets), indent=2, ensure_ascii=True)
        + "\n\n"
        "Rules:\n"
        "- Every factual sentence MUST be supported by at least one snippet and end with [CITE:snippet_id].\n"
        "- If a claim cannot be supported by any snippet, remove the sentence.\n"
        "- You MAY restructure, combine, or reorder sentences.\n"
        "- Do NOT invent facts not present in the snippets.\n"
        "- Narrative transitions (no facts, no names, no numbers) may be uncited.\n"
        "- No headings, bullet lists, or markdown in revised_text.\n"
        "- Use the exact snippet_id values from the evidence list.\n"
        "- Multiple citations: separate tokens [CITE:id1] [CITE:id2].\n"
        "- Citations at the very end of the sentence, after final punctuation.\n\n"
        "Self-check (REQUIRED before returning):\n"
        "1. Count every factual sentence in your revised_text.\n"
        "2. Verify each one is supported by a provided snippet.\n"
        "3. Compute: supported / total \u00d7 100.\n"
        "4. If the result is \u2264 70, revise again until it exceeds 70.\n"
        "5. Report the final counts in self_check.\n"
    )
    system = "You repair evidence-grounded drafts and return strict JSON only."
    log_llm_exchange("request", prompt, stage="repair", section_id=section.section_id, logger=logger)
    response = llm_client.generate(
        prompt,
        system=system,
        max_tokens=1800,
        temperature=0.2,
        response_format=json_response_format("repair", REPAIR_SCHEMA),
    )
    log_llm_exchange("response", response, stage="repair", section_id=section.section_id, logger=logger)
    payload = extract_json_payload(response)
    if not isinstance(payload, dict):
        raise ValueError("Repair response did not return a JSON object.")
    return payload
```

- [ ] **Step 3: Replace the `if not section_snippets / else` block in `repair_agent_node` (lines 588–678)**

Replace the entire block from `if not section_snippets:` through `if isinstance(edits_json, dict): repair_logs.append(edits_json)` with:

```python
        if not section_snippets:
            revised_text, edits = _remove_issue_sentences(original_text, issue_indices)
            revised_text = _strip_citations(revised_text).replace("  ", " ").strip()
            revised_summary = _summary_from_text(revised_text)
            if has_invalid_indexes:
                revised_text = original_text
                if original_summary:
                    revised_summary = original_summary
            log_entry: dict = {"repaired_section_edits": edits}
        else:
            repair_payload = _repair_with_llm(
                llm_client,
                section=section,
                section_text=original_text,
                section_summary=original_summary,
                prior_summary=prior_summary,
                issues=issues,
                evidence_snippets=section_snippets,
            )
            repaired_id = str(repair_payload.get("section_id", "")).strip()
            if repaired_id and repaired_id != section_id:
                raise ValueError(f"Repair response section_id mismatch for {section_id}")
            revised_text = str(repair_payload.get("revised_text", "")).strip()
            revised_summary = str(repair_payload.get("revised_summary", "")).strip()
            self_check = repair_payload.get("self_check") or {}
            estimated_pct = self_check.get("estimated_grounding_pct", 100)
            if isinstance(estimated_pct, int) and estimated_pct <= 70:
                logger.warning(
                    "Repair self-check below threshold for %s: estimated %d%%",
                    section_id,
                    estimated_pct,
                )
            log_entry = self_check if isinstance(self_check, dict) else {}

        _persist_draft_section(
            session,
            tenant_id=state.tenant_id,
            run_id=state.run_id,
            section_id=section_id,
            text=revised_text,
            summary=revised_summary,
        )
        section_texts[section_id] = revised_text
        section_summaries[section_id] = revised_summary
        if log_entry:
            repair_logs.append(log_entry)
```

- [ ] **Step 4: Run tests and verify they all pass**

```bash
cd c:/projects/ResearchOps-Studio
python -m pytest tests/backend/unit/test_repair_routing.py -v
```

Expected output:
```
PASSED test_evaluator_routes_any_failed_section_to_repair
PASSED test_evaluator_persists_pipeline_faithfulness_metrics
PASSED test_repair_agent_repairs_last_section_without_next_section
PASSED test_repair_agent_calls_each_failed_section_once_when_adjacent_sections_fail
PASSED test_repair_agent_does_not_modify_passing_section_after_failing_section
5 passed
```

- [ ] **Step 5: Commit**

```bash
cd c:/projects/ResearchOps-Studio
git add backend/services/orchestrator/nodes/repair_agent.py tests/backend/unit/test_repair_routing.py
git commit -m "feat: rewrite repair agent prompt to full-section rewrite with 70% self-check

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

### Task 3: Add self_check warning test

**Files:**
- Modify: `tests/backend/unit/test_repair_routing.py`

Add a test that verifies a `WARNING` log is emitted when the LLM self-reports `estimated_grounding_pct <= 70`. The warning log is already implemented in Task 2 — this task just confirms it.

- [ ] **Step 1: Write the test**

Add this test at the end of `tests/backend/unit/test_repair_routing.py`:

```python
def test_repair_agent_logs_warning_when_self_check_below_threshold(db_session, monkeypatch, caplog):
    import logging
    from nodes.repair_agent import repair_agent_node
    import nodes.repair_agent as repair_module

    tenant_id = uuid4()
    run_id = uuid4()
    _make_run(db_session, tenant_id=tenant_id, run_id=run_id)

    class StubLLM:
        def generate(self, _prompt, **_kwargs):
            return json.dumps(
                {
                    "section_id": "intro",
                    "revised_text": "Intro still weak [CITE:11111111-1111-1111-1111-111111111111].",
                    "revised_summary": "Still weak.",
                    "self_check": {
                        "factual_sentence_count": 5,
                        "supported_sentence_count": 3,
                        "estimated_grounding_pct": 60,
                    },
                }
            )

    monkeypatch.setattr(repair_module, "get_llm_client_for_stage", lambda *_args, **_kwargs: StubLLM())
    _make_snippet(db_session, tenant_id=tenant_id, snippet_id="11111111-1111-1111-1111-111111111111")

    outline = OutlineModel(
        sections=[
            OutlineSection(
                section_id="intro",
                title="Introduction",
                goal="Intro goal.",
                key_points=["A"],
                suggested_evidence_themes=["t"],
                section_order=1,
            )
        ]
    )
    db_session.add_all(
        [
            DraftSectionRow(
                tenant_id=tenant_id,
                run_id=run_id,
                section_id="intro",
                text="Unsupported intro sentence.",
                section_summary="Old summary.",
            ),
            SectionReviewRow(
                tenant_id=tenant_id,
                run_id=run_id,
                section_id="intro",
                verdict="fail",
                issues_json=[
                    {
                        "sentence_index": 0,
                        "problem": "unsupported",
                        "notes": "Missing support.",
                        "citations": [],
                    }
                ],
                reviewed_at=datetime.now(UTC),
            ),
        ]
    )
    db_session.flush()

    state = OrchestratorState(
        tenant_id=tenant_id,
        run_id=run_id,
        user_query="test",
        outline=outline,
        section_evidence_snippets={
            "intro": [
                EvidenceSnippetRef(
                    snippet_id="11111111-1111-1111-1111-111111111111",
                    source_id=uuid4(),
                    text="Intro evidence snippet.",
                    char_start=0,
                    char_end=21,
                )
            ]
        },
    )

    with caplog.at_level(logging.WARNING, logger="nodes.repair_agent"):
        repair_agent_node.__wrapped__(state, _RuntimeSessionProxy(db_session))

    assert any(
        "self-check below threshold" in record.message and "intro" in record.message
        for record in caplog.records
    )
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd c:/projects/ResearchOps-Studio
python -m pytest tests/backend/unit/test_repair_routing.py::test_repair_agent_logs_warning_when_self_check_below_threshold -v
```

Expected: FAIL — the test should not pass before the warning is confirmed present. If Task 2 was done correctly, this test should actually PASS already (the warning code was implemented in Task 2, Step 3). Confirm it passes.

- [ ] **Step 3: Run the full test suite**

```bash
cd c:/projects/ResearchOps-Studio
python -m pytest tests/backend/unit/test_repair_routing.py -v
```

Expected:
```
PASSED test_evaluator_routes_any_failed_section_to_repair
PASSED test_evaluator_persists_pipeline_faithfulness_metrics
PASSED test_repair_agent_repairs_last_section_without_next_section
PASSED test_repair_agent_calls_each_failed_section_once_when_adjacent_sections_fail
PASSED test_repair_agent_does_not_modify_passing_section_after_failing_section
PASSED test_repair_agent_logs_warning_when_self_check_below_threshold
6 passed
```

- [ ] **Step 4: Commit**

```bash
cd c:/projects/ResearchOps-Studio
git add tests/backend/unit/test_repair_routing.py
git commit -m "test: verify repair agent logs warning when self-check grounding <= 70%

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```
