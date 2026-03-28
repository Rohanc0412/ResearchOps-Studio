# Progress Card Quantification & LLM-Planned Step Labels

**Date:** 2026-03-28
**Status:** Approved

---

## Goal

Replace the generic, hardcoded step labels in `ResearchProgressCard` with:
1. **LLM-planned labels** — 6 short sentences tailored to the specific research question, generated at run-start in the backend.
2. **Live per-step metrics** — right-aligned inline numbers on each step row (queries run, papers found/selected, sections outlined/packed/drafted/evaluated/exported), derived purely from existing SSE event payloads.
3. **Layout: Option A** — each step row is `[badge] [label flex-1] [metric right-aligned]`. No extra stat blocks or strips.
4. **All existing animations strictly preserved** (see Animation Contract below).

---

## Pipeline Step Mapping (fixed 6)

One step per real pipeline node. Count never changes; only the label text is dynamic.

| Index | Node | Stage key | Fallback label |
|-------|------|-----------|----------------|
| 0 | retriever | `retrieve` | Search papers and collect evidence. |
| 1 | outliner | `outline` | Structure the report outline. |
| 2 | evidence_packer | `evidence_pack` | Package evidence per section. |
| 3 | writer | `draft` | Draft each section with citations. |
| 4 | evaluator | `evaluate` | Review quality and evidence coverage. |
| 5 | exporter | `export` | Export the final report. |

**Repair loop:** `repair_agent` maps to the same step index as `draft` (index 3). When repair runs, the writer step re-activates. Its badge shows a `↻` icon and its label gains a `(pass N)` suffix where N is `state.iteration_count`. No new step row is added.

`STAGE_TO_STEP_INDEX` must be updated:
```ts
retrieve: 0, outline: 1, evidence_pack: 2,
draft: 3, repair: 3,
evaluate: 4, validate: 4, factcheck: 4,
export: 5
```

---

## Backend Changes

### 1. `OrchestratorState` — new field

```python
step_labels: list[str] | None = None
```

Defaults `None`. Populated at the start of `retriever_node`.

### 2. `retriever_node` — LLM step planning call

At the **very first line** of `retriever_node`, before any search queries are issued:

- Make one lightweight LLM call using the already-configured `llm_provider` / `llm_model`.
- **Prompt (system):** "You are a research pipeline planner. Write exactly 6 short action phrases (max 10 words each) describing the steps of a research pipeline for the given question. The 6 steps are always: (1) search papers, (2) outline the report, (3) package evidence per section, (4) draft each section, (5) evaluate quality, (6) export the report. Tailor each phrase to the specific question. Return a JSON array of exactly 6 strings. No other output."
- **User message:** `{user_query}`
- **Failure handling:** wrap in `try/except`; on any error (LLM failure, JSON parse error, wrong array length) log a warning and leave `state.step_labels = None`. The frontend falls back to hardcoded labels. This must never raise.
- On success: `state.step_labels = parsed_labels`

### 3. `retrieve.plan_created` event — add `step_labels` to payload

The existing `retrieve.plan_created` event already fires immediately after the LLM planning call. Add `step_labels` to its `data` dict:

```python
data={
    "query_count": len(query_plan),
    "queries": [...],
    "step_labels": state.step_labels,   # new — list[str] or None
    "llm_used": llm_used,
}
```

This is the first SSE event the frontend receives, so labels arrive before any progress updates.

---

## Frontend Changes

### 1. `researchProgress.ts` — model update

Add to `ResearchProgressCardModel`:

```ts
stepMetrics: (string | null)[]   // 6 entries; null = step not yet reached
```

Step labels are derived inside `buildResearchProgressCardModel` from the first `retrieve.plan_created` event payload:

```ts
const planEvent = events.find(e => e.event_type === "retrieve.plan_created");
const rawLabels = planEvent?.payload?.["step_labels"];
const stepLabels: string[] = (
  Array.isArray(rawLabels) && rawLabels.length === 6
    ? rawLabels
    : FALLBACK_STEP_LABELS
);
```

`FALLBACK_STEP_LABELS` replaces the current inline template strings array.

### 2. `researchProgress.ts` — `deriveStepMetrics` function

New pure function, called inside `buildResearchProgressCardModel`. Scans all accumulated `events` and returns `(string | null)[]` of length 6.

**Step 0 — retrieve:**
- Scan for `retrieve.plan_created` → `query_count` (queries run)
- Scan for `retrieve.mcp_completed` → sum values of `found_by_source` (papers found)
- Scan for `retrieve.summary` → `selected_sources_total` (papers selected)
- Completed metric: `"9 q · 47 found · 14 selected"`
- Active metric (partial — only some sub-events fired): show what's available, e.g. `"9 q · 47 found"` or `"9 q"` or `null`

**Step 1 — outline:**
- Scan for `stage_finish` with `stage === "outline"` → `state_summary.outline_sections`
- Metric: `"6 sections"`

**Step 2 — evidence_pack:**
- Count `evidence_pack.created` events received so far → `completedSections`
- Read `outline_sections` from outline stage_finish (total sections) → `totalSections`
- Active metric: `"${completedSections} / ${totalSections} sections"` (updates each event)
- Completed metric: same final value

**Step 3 — draft (writer, and repair re-entry):**
- Count `draft.section_completed` events → `completedSections`
- Read `total_sections` from any `progress` event with `stage === "draft"` → `totalSections`
- Active metric: `"${completedSections} / ${totalSections} sections"`
- On repair re-entry: prefix with iteration, e.g. `"2 / 6 sections (pass 2)"`

**Step 4 — evaluate:**
- Scan for `evaluate.summary` → `pass_count`, `fail_count`
- Active: count `evaluate.section_completed` events as they arrive
- Completed metric: `"${pass_count} passed"` or `"${fail_count} flagged"` if any failed

**Step 5 — export:**
- Completed metric: `"done"` (no count needed; run is succeeded when this step completes)

**Null rules:**
- Return `null` for any step that has not started yet (no relevant events seen)
- Pending steps always show `null`

### 3. `STAGE_TO_STEP_INDEX` update

```ts
const STAGE_TO_STEP_INDEX: Record<string, number> = {
  retrieve: 0,
  outline: 1,       // was "ingest: 1" — ingest removed, outline promoted
  evidence_pack: 2,
  draft: 3,
  repair: 3,        // re-activates writer step
  evaluate: 4,
  validate: 4,
  factcheck: 4,
  export: 5,        // was index 4 — now index 5
};
```

`ingest` mapping removed (not used by the pipeline).

### 4. `ResearchProgressCard.tsx` — step row layout

Each step rendered as a flex row:

```
[badge 20×20]  [label flex-1]  [metric text-right flex-shrink-0]
```

- **label:** `<WaveText>` only when `state === "current" && isRunning` — unchanged rule
- **metric when `state === "complete"`:** `text-[10px] font-semibold text-white/40 whitespace-nowrap`
- **metric when `state === "current"`:** `text-[10px] font-bold text-[#9580c4] whitespace-nowrap`
- **metric when `state === "pending"` or null:** `text-[10px] text-white/10` showing `—`
- **Repair re-entry (step 3, writer):** badge renders `↻` icon instead of number; label appended with `(pass N)` in `text-white/30`

No changes to `ProgressStepBadge`, `WaveText`, progress bar, header, or expanded events log.

---

## Animation Contract

These rules are **non-negotiable** — violating them breaks the existing animations (lessons from prior debugging).

### Rule 1 — Never add `opacity` or `box-shadow` to the global transition

`index.css` global transition is intentionally limited to `color, background-color, border-color`:
```css
transition-property: color, background-color, border-color;
```
`opacity` drives `dot-blink` and `letter-breathe`. `box-shadow` drives `halo-pulse`. Adding either to the global transition will flatten those keyframe animations.

**Corollary:** new metric text elements must not carry inline `transition: opacity ...` or `transition: box-shadow ...` styles.

### Rule 2 — Keyframes must be defined in BOTH places

Every `@keyframes` block must appear in:
1. `frontend/dashboard/src/index.css` (unlayered, takes precedence over `@layer` blocks)
2. `frontend/dashboard/tailwind.config.ts` under `theme.extend.keyframes`

If a new animation is needed (e.g. a counter tick), it must be added to both files. Tailwind JIT alone is not sufficient — the CSS file copy is the authoritative source for animations that use `opacity` or `box-shadow`.

### Rule 3 — No new animations are needed

The existing four animations cover all cases:
- `animate-dot-blink` — status dot in header
- `animate-halo-pulse` — active step badge
- `animate-letter-breathe` (via `<WaveText>`) — active step label text
- `animate-shimmer` — progress bar fill

The new metric text is **static per render** (number changes, but no CSS animation on the value itself). Do not add a number-counting animation.

### Rule 4 — `animate-shimmer` requires `background-size: 200%`

The shimmer gradient is 200% wide. The progress bar fill div must keep:
```tsx
className="... bg-[linear-gradient(...)] bg-[length:200%_100%]"
```
Do not remove `bg-[length:200%_100%]` when editing the progress bar row.

### Rule 5 — `<WaveText>` must remain a direct text wrapper

`WaveText` splits text into `<span>` characters with staggered `animationDelay`. It must not be wrapped in a container that has `transform` or `opacity` transitions — that competes with the per-character keyframe.

---

## Files Changed

| Action | Path |
|--------|------|
| Modify | `backend/services/orchestrator/nodes/retriever.py` |
| Modify | `backend/libs/core/orchestrator/state.py` |
| Modify | `frontend/dashboard/src/components/run/researchProgress.ts` |
| Modify | `frontend/dashboard/src/components/run/ResearchProgressCard.tsx` |

No new files. No new dependencies. No new API endpoints.

---

## Out of Scope

- Persisting step labels to the database (they live only in SSE event payloads and frontend state for the duration of a run)
- Showing step labels in the artifact download card (`RunArtifactLinks`)
- Animated number counting (Rule 3 above)
- Changing the expanded events log section
