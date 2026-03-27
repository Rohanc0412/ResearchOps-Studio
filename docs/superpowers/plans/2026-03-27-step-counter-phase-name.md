# Step Counter Phase Name Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the "Step N of 5" fallback metric text in ResearchProgressCard with the short phase name for the current step.

**Architecture:** Single change inside `deriveMetricText()` in `researchProgress.ts`. Add a `STEP_PHASE_NAMES` constant array and replace both "Step N of 5" string returns with a lookup into that array. No other files change.

**Tech Stack:** TypeScript. No test framework is installed — verify via `tsc` build.

---

## Files

| Action | Path |
|--------|------|
| Modify | `frontend/dashboard/src/components/run/researchProgress.ts` |

---

## Task 1: Add STEP_PHASE_NAMES and update deriveMetricText

**Files:**
- Modify: `frontend/dashboard/src/components/run/researchProgress.ts`

- [ ] **Step 1: Add the STEP_PHASE_NAMES constant**

Open `frontend/dashboard/src/components/run/researchProgress.ts`.

After the `STAGE_TO_STEP_INDEX` constant (around line 44–55), add:

```typescript
const STEP_PHASE_NAMES = ["Collect", "Themes", "Studies", "Compare", "Summary"] as const;
```

- [ ] **Step 2: Update deriveMetricText to use phase names**

Find `deriveMetricText` (starts around line 177). The function currently has these two "Step N of 5" returns:

```typescript
if (!latestEvent) return "Step 1 of 5";
```
and at the end of the function:
```typescript
return `Step ${Math.min(currentStepIndex + 1, 5)} of 5`;
```

Replace both with phase name lookups. The full updated function:

```typescript
function deriveMetricText(
  status: ProgressStatus,
  latestEvent: RunEvent | undefined,
  events: RunEvent[],
  currentStepIndex: number
) {
  if (status === "succeeded") return "Done";
  if (status === "failed") return "Needs retry";
  if (status === "canceled") return "Stopped";
  if (!latestEvent) return STEP_PHASE_NAMES[0];

  const payload = latestEvent.payload ?? {};
  const queryCount = pickNumber(payload, ["query_count", "queries", "search_count", "searches"]);
  if (queryCount !== null) return `${queryCount} searches`;

  const sourceCount = pickNumber(payload, ["source_count", "sources", "candidate_count", "paper_count"]);
  if (sourceCount !== null) return `${sourceCount} sources`;

  const snippetCount = pickNumber(payload, ["snippet_count", "evidence_count"]);
  if (snippetCount !== null) return `${snippetCount} snippets`;

  const sectionProgress = deriveSectionMetric(events, latestEvent.stage);
  if (sectionProgress) return sectionProgress;

  return STEP_PHASE_NAMES[Math.min(currentStepIndex, 4)];
}
```

Note: `Math.min(currentStepIndex, 4)` (not `currentStepIndex + 1`) because `STEP_PHASE_NAMES` is 0-indexed and we want the *current* phase name, not the next one.

- [ ] **Step 3: Verify TypeScript compiles**

```bash
cd frontend/dashboard && npm run build
```

Expected: no TypeScript errors, build succeeds.

- [ ] **Step 4: Commit**

```bash
git add frontend/dashboard/src/components/run/researchProgress.ts
git commit -m "feat: show phase name instead of step counter in ResearchProgressCard"
```
