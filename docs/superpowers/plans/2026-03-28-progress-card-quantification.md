# Progress Card Quantification & LLM-Planned Step Labels — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the 5 hardcoded template step labels in `ResearchProgressCard` with 6 LLM-planned labels tailored to the research question, and add live per-step metrics (queries run, papers found/selected, sections outlined/packed/drafted/evaluated) as right-aligned inline numbers on each step row.

**Architecture:** The backend generates 6 step labels in one lightweight LLM call at the very start of `retriever_node`, stores them in `OrchestratorState.step_labels`, and emits them in the first SSE event (`retrieve.plan_created`). The frontend reads those labels from the event payload, derives per-step metrics by scanning the accumulated SSE events, and renders each step row as `[badge] [label flex-1] [metric right-aligned]`.

**Tech Stack:** Python (Pydantic, LangChain LLM client), TypeScript, React, Tailwind CSS. No new dependencies. No new files.

---

## Files

| Action | Path |
|--------|------|
| Modify | `backend/libs/core/orchestrator/state.py` |
| Modify | `backend/services/orchestrator/nodes/retriever.py` |
| Modify | `frontend/dashboard/src/components/run/researchProgress.ts` |
| Modify | `frontend/dashboard/src/components/run/ResearchProgressCard.tsx` |

---

## Task 1 — Backend: add `step_labels` to state + LLM planning call

**Files:**
- Modify: `backend/libs/core/orchestrator/state.py`
- Modify: `backend/services/orchestrator/nodes/retriever.py`

### Step 1 — Add `step_labels` field to `OrchestratorState`

In [state.py](backend/libs/core/orchestrator/state.py), find the `# Metadata` block near the bottom of `OrchestratorState` (around line 198). Add the new field just before `iteration_count`:

```python
    # Step labels (LLM-planned at run start, streamed to frontend)
    step_labels: list[str] | None = None
```

The full block should read:

```python
    # Step labels (LLM-planned at run start, streamed to frontend)
    step_labels: list[str] | None = None

    # Metadata
    iteration_count: int = 0
    max_iterations: int = 5
    started_at: datetime | None = None
    completed_at: datetime | None = None
```

- [ ] Make the edit above.

### Step 2 — Add `_plan_step_labels` helper to `retriever.py`

In [retriever.py](backend/services/orchestrator/nodes/retriever.py), add this function just before `retriever_node` (around line 1188). It reuses the existing `get_llm_client_for_stage` / `LLMError` / `_extract_json_payload` helpers already imported in the file.

```python
def _plan_step_labels(
    question: str,
    llm_provider: str | None,
    llm_model: str | None,
) -> list[str] | None:
    """Return 6 LLM-planned step labels tailored to the research question.

    Returns None on any error so the caller can fall back to hardcoded labels.
    Never raises.
    """
    try:
        llm_client = get_llm_client_for_stage("retrieve", llm_provider, llm_model)
        if llm_client is None:
            return None

        system = (
            "You are a research pipeline planner. Write exactly 6 short action phrases "
            "(max 10 words each) describing the steps of a research pipeline for the given "
            "question. The 6 steps are always: (1) search papers, (2) outline the report, "
            "(3) package evidence per section, (4) draft each section, (5) evaluate quality, "
            "(6) export the report. Tailor each phrase to the specific question. "
            "Return a JSON array of exactly 6 strings. No other output."
        )
        response = llm_client.generate(
            question,
            system=system,
            max_tokens=300,
            temperature=0.3,
        )
        payload = _extract_json_payload(response)
        if isinstance(payload, list) and len(payload) == 6 and all(isinstance(s, str) for s in payload):
            return [s.strip() for s in payload]
        logger.warning(
            "Step label planning returned unexpected shape",
            extra={"event": "pipeline.llm.step_labels", "payload_type": type(payload).__name__},
        )
        return None
    except Exception as exc:
        logger.warning(
            "Step label planning failed, using fallback labels",
            extra={"event": "pipeline.llm.step_labels", "reason": str(exc)},
        )
        return None
```

- [ ] Add the function above to `retriever.py` directly before `retriever_node`.

### Step 3 — Call `_plan_step_labels` at the top of `retriever_node` and add to event payload

In [retriever.py](backend/services/orchestrator/nodes/retriever.py), find `retriever_node` (line ~1189). The current first line is `question = state.user_query`. Insert the planning call before it, and add `step_labels` to the `retrieve.plan_created` event payload.

Before (the opening of the function and the plan_created emit):

```python
@instrument_node("retrieve")
def retriever_node(state: OrchestratorState, session: Session) -> OrchestratorState:
    question = state.user_query
    query_plan, llm_used = _build_query_plan(
        question=question,
        llm_provider=state.llm_provider,
        llm_model=state.llm_model,
    )
    if not query_plan:
        raise ValueError("Question is required for retrieval")

    emit_run_event(
        session=session,
        tenant_id=state.tenant_id,
        run_id=state.run_id,
        event_type="retrieve.plan_created",
        stage="retrieve",
        data={
            "query_count": len(query_plan),
            "queries": [{"intent": p.intent, "query": p.query} for p in query_plan],
            "llm_used": llm_used,
        },
    )
```

After:

```python
@instrument_node("retrieve")
def retriever_node(state: OrchestratorState, session: Session) -> OrchestratorState:
    question = state.user_query
    state.step_labels = _plan_step_labels(
        question=question,
        llm_provider=state.llm_provider,
        llm_model=state.llm_model,
    )

    query_plan, llm_used = _build_query_plan(
        question=question,
        llm_provider=state.llm_provider,
        llm_model=state.llm_model,
    )
    if not query_plan:
        raise ValueError("Question is required for retrieval")

    emit_run_event(
        session=session,
        tenant_id=state.tenant_id,
        run_id=state.run_id,
        event_type="retrieve.plan_created",
        stage="retrieve",
        data={
            "query_count": len(query_plan),
            "queries": [{"intent": p.intent, "query": p.query} for p in query_plan],
            "step_labels": state.step_labels,
            "llm_used": llm_used,
        },
    )
```

- [ ] Apply the edit above.

### Step 4 — Verify the backend still starts

```bash
cd backend && python -c "from services.orchestrator.nodes.retriever import retriever_node; print('ok')"
```

Expected: `ok` (no import errors).

- [ ] Run the verification above.

### Step 5 — Commit backend changes

```bash
git add backend/libs/core/orchestrator/state.py backend/services/orchestrator/nodes/retriever.py
git commit -m "feat: add LLM step label planning to retriever_node, emit in plan_created event"
```

- [ ] Commit.

---

## Task 2 — Frontend model: 6-step mapping, stepMetrics, LLM labels

**Files:**
- Modify: `frontend/dashboard/src/components/run/researchProgress.ts`

This task rewrites the model layer. Work through the steps below in order — each is a self-contained edit.

### Step 1 — Replace `STAGE_TO_STEP_INDEX` with the 6-step version

Find the current `STAGE_TO_STEP_INDEX` constant (line ~44):

```ts
const STAGE_TO_STEP_INDEX: Record<string, number> = {
  retrieve: 0,
  ingest: 1,
  outline: 1,
  evidence_pack: 2,
  draft: 3,
  evaluate: 4,
  validate: 4,
  repair: 4,
  factcheck: 4,
  export: 4
};
```

Replace with:

```ts
const STAGE_TO_STEP_INDEX: Record<string, number> = {
  retrieve: 0,
  outline: 1,
  evidence_pack: 2,
  draft: 3,
  repair: 3,
  evaluate: 4,
  validate: 4,
  factcheck: 4,
  export: 5,
};
```

Key changes: `ingest` removed; `repair` moved from index 4 to 3 (re-activates writer); `export` promoted from 4 to 5.

- [ ] Apply the edit.

### Step 2 — Replace `STEP_PHASE_NAMES` with `FALLBACK_STEP_LABELS`

Find `const STEP_PHASE_NAMES = ...` (line ~57) and replace the entire line:

```ts
const STEP_PHASE_NAMES = ["Collect", "Themes", "Studies", "Compare", "Summary"] as const;
```

with:

```ts
const FALLBACK_STEP_LABELS: string[] = [
  "Search papers and collect evidence.",
  "Structure the report outline.",
  "Package evidence per section.",
  "Draft each section with citations.",
  "Review quality and evidence coverage.",
  "Export the final report.",
];
```

- [ ] Apply the edit.

### Step 3 — Add `stepMetrics` to `ResearchProgressCardModel`

Find the `ResearchProgressCardModel` type (line ~21) and add the new field:

```ts
export type ResearchProgressCardModel = {
  title: string;
  steps: ResearchProgressStep[];
  summaryText: string;
  metricText: string;
  progressRatio: number;
  status: ProgressStatus;
  recentEvents: ResearchProgressEventRow[];
  stepMetrics: (string | null)[];
};
```

- [ ] Apply the edit (add `stepMetrics: (string | null)[];` to the type).

### Step 4 — Rewrite `buildResearchProgressCardModel` to use 6 LLM-planned steps

Replace the current function body of `buildResearchProgressCardModel` (lines ~59–105). The key changes are:
1. Read `step_labels` from the first `retrieve.plan_created` event payload.
2. Build the 6-step array using those labels (falling back to `FALLBACK_STEP_LABELS`).
3. Pass `events` to a new `deriveStepMetrics` call and include `stepMetrics` in the returned model.
4. Update `deriveCurrentStepIndex` call to handle index 5 as the succeeded sentinel.

```ts
export function buildResearchProgressCardModel({
  activeRun,
  chatTitle,
  messages,
  events
}: BuildResearchProgressCardModelArgs): ResearchProgressCardModel {
  const title = deriveResearchTitle(activeRun?.question, messages, chatTitle);

  // Read LLM-planned labels from the first retrieve.plan_created event.
  // event_type is sent by the backend and preserved by RunEventSchema's .passthrough().
  const planEvent = events.find(
    e => (e as RunEvent & { event_type?: string }).event_type === "retrieve.plan_created"
  );
  const rawLabels = planEvent?.payload?.["step_labels"];
  const stepLabels: string[] = (
    Array.isArray(rawLabels) && rawLabels.length === 6
      ? rawLabels as string[]
      : FALLBACK_STEP_LABELS
  );

  const STEP_IDS = ["retrieve", "outline", "evidence_pack", "draft", "evaluate", "export"] as const;

  const latestEvent = events.at(-1);
  const currentStepIndex = deriveCurrentStepIndex(activeRun?.status ?? "running", latestEvent);
  const completedCount = activeRun?.status === "succeeded" ? STEP_IDS.length : Math.max(0, currentStepIndex);
  const progressRatio = deriveProgressRatio(activeRun?.status ?? "running", currentStepIndex, latestEvent);

  return {
    title,
    steps: STEP_IDS.map((id, index) => ({
      id,
      label: stepLabels[index] ?? FALLBACK_STEP_LABELS[index] ?? "",
      state:
        activeRun?.status === "succeeded" || index < currentStepIndex
          ? "complete"
          : index === currentStepIndex
            ? activeRun?.status === "canceled" && completedCount === index
              ? "pending"
              : "current"
            : "pending"
    })),
    summaryText: deriveSummaryText(activeRun, latestEvent),
    metricText: deriveMetricText(activeRun?.status ?? "running", latestEvent, events, currentStepIndex),
    progressRatio,
    status: activeRun?.status ?? "running",
    recentEvents: events.slice(-6).reverse().map((event, index) => ({
      id: `${event.ts}-${event.message}-${index}`,
      ts: event.ts,
      message: humanizeEventMessage(event),
      detail: humanizeEventDetail(event),
      level: event.level
    })),
    stepMetrics: deriveStepMetrics(events, activeRun?.status ?? "running"),
  };
}
```

- [ ] Replace the function body with the code above.

### Step 5 — Fix `deriveCurrentStepIndex` and `deriveProgressRatio` for 6 steps

`deriveCurrentStepIndex` currently clamps at 4 and returns 5 for succeeded. With 6 steps (indices 0–5), succeeded should return 6 and the clamp should be 5.

Find `deriveCurrentStepIndex` (line ~137):

```ts
function deriveCurrentStepIndex(status: ProgressStatus, latestEvent?: RunEvent) {
  if (status === "succeeded") return 5;
  if (!latestEvent) return 0;
  const index = STAGE_TO_STEP_INDEX[latestEvent.stage] ?? 0;
  return Math.min(index, 4);
}
```

Replace with:

```ts
function deriveCurrentStepIndex(status: ProgressStatus, latestEvent?: RunEvent) {
  if (status === "succeeded") return 6;
  if (!latestEvent) return 0;
  const index = STAGE_TO_STEP_INDEX[latestEvent.stage] ?? 0;
  return Math.min(index, 5);
}
```

Find `deriveProgressRatio` (line ~144). The division `/ 5` must become `/ 6`:

```ts
function deriveProgressRatio(status: ProgressStatus, currentStepIndex: number, latestEvent?: RunEvent) {
  if (status === "succeeded") return 1;
  if (status === "failed" || status === "canceled") {
    return Math.max(0.08, Math.min(0.96, (currentStepIndex + 0.35) / 6));
  }

  let intraStep = 0.45;
  if (latestEvent) {
    if (latestEvent.message.includes("completed") || latestEvent.message.startsWith("Finished stage:")) {
      intraStep = 0.82;
    } else if (latestEvent.message.includes("started") || latestEvent.message.startsWith("Starting stage:")) {
      intraStep = 0.22;
    }

    const maybeSectionProgress = deriveSectionProgress(latestEvent, latestEvent.stage);
    if (maybeSectionProgress !== null) intraStep = maybeSectionProgress;
  }

  return Math.max(0.08, Math.min(0.96, (currentStepIndex + intraStep) / 6));
}
```

- [ ] Apply both edits.

### Step 6 — Fix the lone reference to `STEP_PHASE_NAMES` in `deriveMetricText`

`deriveMetricText` uses `STEP_PHASE_NAMES` as a fallback (line ~188 and ~203). The constant no longer exists. Replace both references:

Find:

```ts
  if (!latestEvent) return STEP_PHASE_NAMES[0];
```

Replace with:

```ts
  if (!latestEvent) return "";
```

Find:

```ts
  return STEP_PHASE_NAMES[Math.min(currentStepIndex, 4)]!;
```

Replace with:

```ts
  return "";
```

- [ ] Apply both edits.

### Step 7 — Add `deriveStepMetrics` function

Add this new pure function after `deriveMetricText` (around line ~204). It scans all accumulated SSE events and returns one metric string (or `null`) per step.

**Important note on `event_type`:** The backend includes `event_type` in the SSE JSON (e.g. `"retrieve.plan_created"`). `RunEventSchema` uses `.passthrough()`, so the field is present at runtime but not in the TypeScript type. Access it via a local type helper at the top of the function.

```ts
function deriveStepMetrics(events: RunEvent[], status: ProgressStatus): (string | null)[] {
  // event_type is sent by the backend and preserved via .passthrough() — not in the TS type
  type E = RunEvent & { event_type?: string };
  const evts = events as E[];

  // ── Step 0: retrieve ──────────────────────────────────────────
  let queryCount: number | null = null;
  let foundTotal: number | null = null;
  let selectedTotal: number | null = null;

  for (const e of evts) {
    if (e.event_type === "retrieve.plan_created") {
      const q = pickNumber(e.payload ?? {}, ["query_count"]);
      if (q !== null) queryCount = q;
    }
    if (e.event_type === "retrieve.mcp_completed") {
      const foundBySource = e.payload?.["found_by_source"];
      if (foundBySource && typeof foundBySource === "object" && !Array.isArray(foundBySource)) {
        foundTotal = Object.values(foundBySource as Record<string, number>).reduce((a, b) => a + b, 0);
      }
    }
    if (e.event_type === "retrieve.summary") {
      const s = pickNumber(e.payload ?? {}, ["selected_sources_total"]);
      if (s !== null) selectedTotal = s;
    }
  }

  let step0: string | null = null;
  if (queryCount !== null || foundTotal !== null || selectedTotal !== null) {
    const parts: string[] = [];
    if (queryCount !== null) parts.push(`${queryCount} q`);
    if (foundTotal !== null) parts.push(`${foundTotal} found`);
    if (selectedTotal !== null) parts.push(`${selectedTotal} sel.`);
    step0 = parts.join(" · ");
  }

  // ── Step 1: outline ───────────────────────────────────────────
  let step1: string | null = null;
  for (const e of evts) {
    if (e.event_type === "outline.created") {
      const n = pickNumber(e.payload ?? {}, ["section_count"]);
      if (n !== null) step1 = `${n} sections`;
    }
  }

  // ── Step 2: evidence_pack ─────────────────────────────────────
  let step2: string | null = null;
  {
    const packedSections = evts.filter(e => e.event_type === "evidence_pack.created").length;
    // Reuse outline section_count for total
    let outlineSections: number | null = null;
    for (const e of evts) {
      if (e.event_type === "outline.created") {
        outlineSections = pickNumber(e.payload ?? {}, ["section_count"]);
      }
    }
    if (packedSections > 0) {
      step2 = outlineSections !== null
        ? `${packedSections} / ${outlineSections} sections`
        : `${packedSections} sections`;
    }
  }

  // ── Step 3: draft ─────────────────────────────────────────────
  let step3: string | null = null;
  {
    const draftedSections = evts.filter(e => e.event_type === "draft.section_completed").length;
    let totalSections: number | null = null;
    for (const e of evts) {
      if (e.stage === "draft" && e.event_type === "progress") {
        const t = pickNumber(e.payload ?? {}, ["total_sections"]);
        if (t !== null) totalSections = t;
      }
    }
    // Fall back to outline section_count
    if (totalSections === null) {
      for (const e of evts) {
        if (e.event_type === "outline.created") {
          totalSections = pickNumber(e.payload ?? {}, ["section_count"]);
        }
      }
    }
    if (draftedSections > 0) {
      step3 = totalSections !== null
        ? `${draftedSections} / ${totalSections} sections`
        : `${draftedSections} sections`;
    }
  }

  // ── Step 4: evaluate ──────────────────────────────────────────
  let step4: string | null = null;
  for (const e of evts) {
    if (e.event_type === "evaluate.summary") {
      const pass = pickNumber(e.payload ?? {}, ["pass_count"]);
      const fail = pickNumber(e.payload ?? {}, ["fail_count"]);
      if (pass !== null || fail !== null) {
        if ((fail ?? 0) > 0) {
          step4 = `${fail} flagged`;
        } else {
          step4 = `${pass ?? 0} passed`;
        }
      }
    }
  }
  // Active (no summary yet): count evaluate.section_completed events
  if (step4 === null) {
    const evalDone = evts.filter(
      e => e.event_type === "evaluate.section_completed" || e.event_type === "evaluate.completed"
    ).length;
    if (evalDone > 0) step4 = `${evalDone} reviewed`;
  }

  // ── Step 5: export ────────────────────────────────────────────
  let step5: string | null = null;
  const hasExport = evts.some(e => e.stage === "export");
  if (status === "succeeded" || hasExport) step5 = "done";

  return [step0, step1, step2, step3, step4, step5];
}
```

- [ ] Add the function above after `deriveMetricText`.

### Step 8 — Verify TypeScript compiles

```bash
cd frontend/dashboard && npm run build 2>&1 | tail -20
```

Expected: no TypeScript errors. If `event_type` is not a field on `RunEvent`, use `e.message` pattern matching instead (check `frontend/dashboard/src/types/dto.ts` for the `RunEvent` type shape).

- [ ] Run the build verification.

### Step 9 — Fix `RunEvent` shape if needed

If the build fails with `Property 'event_type' does not exist on type 'RunEvent'`, open `frontend/dashboard/src/types/dto.ts` and check the actual field name on `RunEvent`. Common alternatives: `type`, `event_type`, `eventType`.

If the field is named differently, do a find-and-replace in `deriveStepMetrics` to use the correct field name.

- [ ] Resolve any type errors, re-run build.

### Step 10 — Commit frontend model changes

```bash
git add frontend/dashboard/src/components/run/researchProgress.ts
git commit -m "feat: 6-step progress model with LLM-planned labels and per-step metrics"
```

- [ ] Commit.

---

## Task 3 — Frontend card: Option A inline metric layout

**Files:**
- Modify: `frontend/dashboard/src/components/run/ResearchProgressCard.tsx`

### Step 1 — Update the step row layout to include an inline right-aligned metric

Find the step row rendering block in `ResearchProgressCard` (the `{/* label */}` div, lines ~88–108):

```tsx
              {/* label */}
              <div className="min-w-0 flex-1 pt-[5px]">
                <p
                  className={cx(
                    "text-[11px] leading-relaxed",
                    isFailed && step.state === "current"
                      ? "text-[rgba(255,100,100,0.6)]"
                      : step.state === "current"
                        ? "font-medium text-[#f8fafc]"
                        : step.state === "complete"
                          ? "text-white/45"
                          : "text-white/[0.16]"
                  )}
                >
                  {step.state === "current" && isRunning ? (
                    <WaveText text={step.label} duration={2.8} />
                  ) : (
                    step.label
                  )}
                </p>
              </div>
```

Replace with a flex row that adds the metric on the right. Note: `model.stepMetrics[index]` provides the metric value (or `null`).

```tsx
              {/* label + metric row */}
              <div className="flex min-w-0 flex-1 items-baseline gap-2 pt-[5px]">
                <p
                  className={cx(
                    "min-w-0 flex-1 text-[11px] leading-relaxed",
                    isFailed && step.state === "current"
                      ? "text-[rgba(255,100,100,0.6)]"
                      : step.state === "current"
                        ? "font-medium text-[#f8fafc]"
                        : step.state === "complete"
                          ? "text-white/45"
                          : "text-white/[0.16]"
                  )}
                >
                  {step.state === "current" && isRunning ? (
                    <WaveText text={step.label} duration={2.8} />
                  ) : (
                    step.label
                  )}
                </p>
                <span
                  className={cx(
                    "shrink-0 whitespace-nowrap text-[10px]",
                    step.state === "complete"
                      ? "font-semibold text-white/40"
                      : step.state === "current"
                        ? "font-bold text-[#9580c4]"
                        : "text-white/10"
                  )}
                >
                  {model.stepMetrics[index] ?? "—"}
                </span>
              </div>
```

- [ ] Apply the edit.

### Step 2 — Verify TypeScript compiles

```bash
cd frontend/dashboard && npm run build 2>&1 | tail -20
```

Expected: no errors.

- [ ] Run verification.

### Step 3 — Commit card changes

```bash
git add frontend/dashboard/src/components/run/ResearchProgressCard.tsx
git commit -m "feat: Option A step row layout — inline right-aligned metric per step"
```

- [ ] Commit.

---

## Verification checklist

After all tasks are complete, do a quick smoke test:

1. Start the stack: `cd backend && make dev` (or your local dev command) + `cd frontend/dashboard && npm run dev`
2. Open a project, trigger a research run.
3. **On run start:** confirm the progress card shows 6 steps (not 5). The labels should be specific to the question (e.g. not generic "Collect recent evidence on...").
4. **During retrieve:** confirm step 0 metric fills in progressively — first `9 q`, then `9 q · 47 found`, then `9 q · 47 found · 14 sel.`.
5. **During evidence_pack:** confirm step 2 shows `N / M sections` updating as packs are created.
6. **During draft:** confirm step 3 shows `N / M sections` updating.
7. **After evaluate:** confirm step 4 shows `N passed` or `N flagged`.
8. **After export:** confirm step 5 shows `done` and all animations (halo-pulse, dot-blink, shimmer, WaveText) still work correctly.
9. **On run failure:** confirm that the global transition does not flatten the blink/pulse animations (no `opacity` or `box-shadow` in Tailwind transition classes on the new metric `<span>`).
