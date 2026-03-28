# Design: Research Progress Card — Active Step Breathing Animation

**Date:** 2026-03-29
**Status:** Approved

## Summary

Add a breathing (opacity pulse) animation to the currently-executing event row in the Research Progress Card's updates dropdown. The row is derived from the active pipeline step's most recent meaningful event, not simply the last received event. Layout stays minimal — no new labels, no extra data.

---

## Affected Files

| File | Change |
|------|--------|
| `frontend/dashboard/src/components/run/researchProgress.ts` | Add `currentAction` field derivation |
| `frontend/dashboard/src/components/run/ResearchProgressCard.tsx` | Render `currentAction` row with animation |

---

## Section 1: Model Changes

### New field on `ResearchProgressCardModel`

```typescript
currentAction: ResearchProgressEventRow | null;
```

- `null` when `status !== "running"`
- Populated when the run is active

### Derivation logic in `buildResearchProgressCardModel`

1. Identify the current active step (the step with `state === "current"`)
2. Resolve the stage(s) for that step index using `STAGE_TO_STEP_INDEX` (e.g. step 3 → `draft`, `repair`)
3. Filter all incoming events to those matching those stages, excluding `level === "debug"`
4. Within that filtered list, prefer events whose `event_type` contains a **started** suffix pattern:
   - Matches: `section_started`, `rerank.started`, `export.started` (any `event_type` ending in `_started` or `.started`)
   - Pick the most recent match
5. If no in-progress event exists, fall back to the most recent non-debug event for that stage
6. Humanize via the same `humanizeEvent()` path used for `recentEvents` — no new message format
7. Exclude the chosen event from `recentEvents` to avoid duplicate display

---

## Section 2: Component Changes

### Active row rendering

In the updates dropdown, render `currentAction` as the **first row** when non-null, followed by the existing `recentEvents` list. No section headers or labels added.

**Active row styling:**
- **Dot**: `bg-indigo-400`, animated opacity `[1, 0.3, 1]` over 2s ease-in-out, infinite
- **Message text**: same opacity animation `[1, 0.3, 1]` over 2s, synchronized with dot (same duration + easing)
- **Timestamp**: displays `"now"` (string literal) instead of a relative timestamp

**All other rows** render exactly as today — no animation, muted dot color, relative timestamp.

When `currentAction` is `null`, the dropdown renders `recentEvents` as-is with no animated row.

---

## Animation Spec

Uses Framer Motion (already a project dependency):

```tsx
<motion.span
  animate={{ opacity: [1, 0.3, 1] }}
  transition={{ duration: 2, ease: "easeInOut", repeat: Infinity }}
/>
```

Applied to both the dot element and the message text element. Same `duration` and `ease` keeps them synchronized.

---

## Non-Goals

- No extra payload data shown in the dropdown
- No "Now" label or section header
- No layout restructuring
- No changes to event humanization messages
