# ResearchProgressCard Step Counter — Phase Name Design

## Summary

Replace the fallback metric text "Step N of 5" in the ResearchProgressCard with the short name of the current phase. The card layout, all other text, and all dynamic metric values (search counts, source counts, etc.) remain unchanged.

## Current Behaviour

`deriveMetricText()` in `researchProgress.ts` returns:
- `"Step 1 of 5"` — when no event has arrived yet
- `"Step N of 5"` — as a fallback when the latest event carries no numeric payload

## Target Behaviour

The same two cases now return the short phase name for the current step index:

| Step index | Phase name |
|-----------|------------|
| 0         | Collect    |
| 1         | Themes     |
| 2         | Studies    |
| 3         | Compare    |
| 4         | Summary    |

Examples:
- No event yet → "Collect"
- Latest event is on `retrieve` stage (index 0) → "Collect"
- Latest event is on `draft` stage (index 3) → "Compare"
- Latest event carries `query_count = 42` → "42 searches" *(unchanged)*

Terminal states ("Done", "Needs retry", "Stopped") are unchanged.

## Scope

**Only file touched:** `frontend/dashboard/src/components/run/researchProgress.ts`

**Changes:**
1. Add a `STEP_PHASE_NAMES` constant array mapping index → phase name.
2. Update `deriveMetricText()` to use `STEP_PHASE_NAMES[currentStepIndex]` instead of the "Step N of 5" string in both the early-return (`!latestEvent`) and the final fallback.

No changes to the card component, CSS, types, or any other file.
