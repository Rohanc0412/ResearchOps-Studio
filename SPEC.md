# ResearchOps Studio — Part 1 Contract (Definition of Done)

Part 1 defines strict, deterministic, fail-closed artifact contracts and enforcement rules.
No LLM calls or best-effort parsing are permitted.

## Definition Of Done (Part 1)

### Artifacts (Output Formats)

1) **Literature Map**
- Nodes:
  - `type` ∈ `{paper, dataset, code}`
  - MUST include `metadata` and `score`
  - MUST include `evidence_refs[]` that reference **snippet-based** evidence only
- Edges:
  - `type` ∈ `{cites, extends, compares, critiques}`
  - MUST reference existing node ids
  - MAY include `evidence_refs[]`

2) **Structured Report**
- Strict section ordering: `intro`, `background`, `related_work`, `methods`, `comparison`, `gaps`, `conclusions`
- Each section MUST contain:
  - `text` (non-empty)
  - `claims[]`
  - `citations` mapping: `citation_key -> EvidenceRef`
- Claim enforcement:
  - `severity=trivial` => citation not required
  - `severity=non_trivial` => MUST include `citation_keys` (non-empty)
  - Each `citation_key` MUST exist in the section `citations` map
- Fail-closed: any violation MUST block output.

3) **Experiment Plan**
- MUST include: `hypothesis`, `datasets`, `baseline_models`, `evaluation_metrics`, `ablation_plan`,
  `compute_estimation`, `risks_and_failure_cases`
- Dataset/model claims MUST include `evidence_refs[]` pointing to snippet evidence.

### Evidence (Immutable Snapshots + Snippets)

- `EvidenceRef` MUST include:
  - `snapshot_id`
  - `snippet_id` (URL-only or missing snippet id is invalid)
  - optional `start_char`, `end_char` offsets
- `EvidenceSnapshot` MUST include:
  - `snapshot_id`
  - `source_meta` (string ok)
  - `content_hash` (sha256 hex)
  - `captured_at` (ISO-8601 timestamp)
  - `raw_text`
- `EvidenceSnippet` MUST include:
  - `snippet_id`
  - `snapshot_id`
  - `start_char`, `end_char` within `raw_text`
  - `snippet_text` equal to `raw_text[start_char:end_char]`
  - `injection_risk_flag` default false
- Citations MUST reference `snippet_id` and MUST resolve via:
  `snippet_id -> snippet -> snapshot`.

### Budgets (Run Safety)

- Configurable policy:
  - `max_connector_calls`
  - `max_time_seconds`
  - `max_tokens`
  - `max_retries_per_stage`
  - `max_evidence_items_ingested`
- Exhaustion behavior:
  - `fail`: raise `BudgetExceededError`
  - `finalize_partial`: return a `PartialResult` with a deterministic `reason`

## Acceptance Criteria (Checklist)

- [ ] `SPEC.md` exists and matches enforced rules.
- [ ] `claim_policy.yaml` exists and is loadable into strict Pydantic models.
- [ ] All Pydantic models are strict and forbid unknown fields.
- [ ] Report section ordering is enforced and deterministic.
- [ ] Non-trivial claims without `citation_keys` fail closed.
- [ ] Claims referencing missing `citation_key` fail closed.
- [ ] EvidenceRef without `snippet_id` fails closed.
- [ ] EvidenceRef referencing an unknown `snippet_id` fails closed.
- [ ] Budget exhaustion in `fail` mode raises `BudgetExceededError`.
- [ ] Budget exhaustion in `finalize_partial` mode returns `PartialResult(partial=true)` with a reason.
- [ ] `examples/*.json` load as golden fixtures:
  - valid ones pass
  - rejected one fails with the expected error class/message
- [ ] `pytest` passes.

## Explicit Failure Cases (Expected Errors)

These error messages are part of the contract and are asserted in tests.

1) Report non-trivial claim missing citations
- Error class: `ClaimPolicyViolationError`
- Message: `Non-trivial claim requires at least one citation_key: claim_id=<ID>`

2) Report claim references missing citation key
- Error class: `ClaimPolicyViolationError`
- Message: `Claim references unknown citation_key: claim_id=<ID> citation_key=<KEY>`

3) EvidenceRef snippet missing in store
- Error class: `EvidenceValidationError`
- Message: `Unknown snippet_id in EvidenceStore: snippet_id=<ID>`

4) EvidenceRef missing snippet_id (URL-only)
- Error class: `EvidenceValidationError`
- Message: `EvidenceRef must include snippet_id (URL-only refs are not allowed)`

5) Budget exceeded in fail mode
- Error class: `BudgetExceededError`
- Message: `Budget exceeded: <budget_name> limit=<N> used=<M>`

6) Budget exceeded in finalize_partial mode
- Returned type: `PartialResult`
- `reason`: `Budget exceeded: <budget_name> limit=<N> used=<M>`

