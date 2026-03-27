# ResearchProgressCard Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Redesign `ResearchProgressCard` to use frosted-glass aesthetics, numbered+connected steps, and four CSS animations (letter-wave, halo pulse, progress shimmer, dot blink).

**Architecture:** All changes are in two files — `tailwind.config.ts` gets four new keyframes/animation utilities, and `ResearchProgressCard.tsx` is fully rewritten with three co-located sub-components (`ProgressStepBadge`, `WaveText`). No changes to the data model or any other file.

**Tech Stack:** React 18, TypeScript, Tailwind CSS v3, Vite, Lucide React icons.

---

## File Map

| File | Change |
|------|--------|
| `frontend/dashboard/tailwind.config.ts` | Add 4 keyframes + 4 animation utilities |
| `frontend/dashboard/src/components/run/ResearchProgressCard.tsx` | Full rewrite — new card shell, `ProgressStepBadge`, `WaveText` |

No other files touched.

---

## Task 1: Add Animation Keyframes to Tailwind Config

**Files:**
- Modify: `frontend/dashboard/tailwind.config.ts`

- [ ] **Step 1: Add keyframes and animation utilities**

Open `frontend/dashboard/tailwind.config.ts`. Inside `theme.extend`, add to the existing `keyframes` block and `animation` block:

```ts
keyframes: {
  // --- existing ---
  "fade-in": {
    from: { opacity: "0", transform: "translateY(4px)" },
    to:   { opacity: "1", transform: "translateY(0)" },
  },
  "scale-in": {
    from: { opacity: "0", transform: "scale(0.96)" },
    to:   { opacity: "1", transform: "scale(1)" },
  },
  spin: {
    from: { transform: "rotate(0deg)" },
    to:   { transform: "rotate(360deg)" },
  },
  // --- new ---
  "letter-breathe": {
    "0%, 100%": { opacity: "1" },
    "50%":      { opacity: "0.45" },
  },
  "halo-pulse": {
    "0%":   { boxShadow: "0 0 0 0px rgba(255,255,255,0.55), 0 0 0 0px rgba(255,255,255,0.15)" },
    "60%":  { boxShadow: "0 0 0 6px rgba(255,255,255,0.08), 0 0 0 12px rgba(255,255,255,0.04)" },
    "100%": { boxShadow: "0 0 0 10px rgba(255,255,255,0), 0 0 0 18px rgba(255,255,255,0)" },
  },
  "shimmer": {
    "0%":   { backgroundPosition: "-200% center" },
    "100%": { backgroundPosition: "200% center" },
  },
  "dot-blink": {
    "0%, 100%": { opacity: "1" },
    "50%":      { opacity: "0.2" },
  },
},
animation: {
  // --- existing ---
  "fade-in":  "fade-in 150ms cubic-bezier(0.4, 0, 0.2, 1)",
  "scale-in": "scale-in 150ms cubic-bezier(0.4, 0, 0.2, 1)",
  spin:       "spin 700ms linear infinite",
  // --- new ---
  "letter-breathe": "letter-breathe 2.8s ease-in-out infinite",
  "halo-pulse":     "halo-pulse 2s ease-out infinite",
  "shimmer":        "shimmer 2.5s linear infinite",
  "dot-blink":      "dot-blink 2s ease-in-out infinite",
},
```

- [ ] **Step 2: Verify Tailwind picks up the new utilities**

```bash
cd frontend/dashboard && npx vite build --mode development 2>&1 | grep -E "error|Error" | head -10
```

Expected: no errors. If the dev server is running, it will hot-reload automatically — no restart needed.

- [ ] **Step 3: Commit**

```bash
git add frontend/dashboard/tailwind.config.ts
git commit -m "feat: add letter-breathe, halo-pulse, shimmer, dot-blink keyframes"
```

---

## Task 2: Rewrite ResearchProgressCard.tsx

**Files:**
- Modify: `frontend/dashboard/src/components/run/ResearchProgressCard.tsx`

The file will contain three components:
1. `ResearchProgressCard` — the exported card
2. `ProgressStepBadge` — numbered circle, replaces `ProgressStepIcon`
3. `WaveText` — splits a string into letter `<span>`s with staggered animation delays

- [ ] **Step 1: Replace the entire file contents**

```tsx
import { Check, ChevronDown, ChevronUp, RotateCcw } from "lucide-react";

import { cx, formatTs } from "../../utils/format";
import type { ResearchProgressCardModel } from "./researchProgress";

type ResearchProgressCardProps = {
  model: ResearchProgressCardModel;
  expanded: boolean;
  onToggleExpanded: () => void;
  onCancel?: () => void;
  onRetry?: () => void;
};

export function ResearchProgressCard({
  model,
  expanded,
  onToggleExpanded,
  onCancel,
  onRetry
}: ResearchProgressCardProps) {
  const isRunning = model.status === "running";
  const isFailed  = model.status === "failed";

  return (
    <div className="mb-6 rounded-[24px] border border-white/[0.07] bg-[#0c0c0c] p-[22px] shadow-[0_24px_64px_rgba(0,0,0,0.5),inset_0_1px_0_rgba(255,255,255,0.04)]">

      {/* ── Header ───────────────────────────────────────────────── */}
      <div className="mb-5 flex items-start justify-between gap-4">
        <div className="min-w-0 flex-1">
          <h3 className="text-[14px] font-semibold leading-snug tracking-tight text-[#f8fafc]">
            {model.title}
          </h3>
          <div className="mt-1 flex items-center gap-1.5">
            {isRunning && (
              <span className="h-[5px] w-[5px] shrink-0 animate-dot-blink rounded-full bg-white/40" />
            )}
            <p
              className={cx(
                "text-[9px] uppercase tracking-[0.18em]",
                isFailed ? "text-[rgba(255,100,100,0.5)]" : "text-white/[0.28]"
              )}
            >
              {isFailed
                ? "Run failed — review or retry"
                : model.status === "canceled"
                  ? "Run stopped before the report finished"
                  : "Live research progress"}
            </p>
          </div>
        </div>

        <button
          type="button"
          onClick={onToggleExpanded}
          className="inline-flex h-9 shrink-0 items-center gap-2 rounded-full border border-white/[0.09] bg-white/[0.04] px-3.5 text-[9px] font-semibold uppercase tracking-[0.12em] text-white/55 transition hover:border-white/20 hover:text-white/70"
        >
          Updates
          {expanded ? <ChevronUp className="h-3.5 w-3.5" /> : <ChevronDown className="h-3.5 w-3.5" />}
        </button>
      </div>

      {/* ── Steps ────────────────────────────────────────────────── */}
      <div className="mb-5 flex flex-col pl-2.5">
        {model.steps.map((step, index) => {
          const isLast = index === model.steps.length - 1;
          return (
            <div key={step.id} className="flex items-start gap-3">
              {/* track: badge + connector */}
              <div className="flex w-7 shrink-0 flex-col items-center">
                <ProgressStepBadge
                  index={index + 1}
                  state={step.state}
                  isFailed={isFailed && step.state === "current"}
                />
                {!isLast && (
                  <div
                    className={cx(
                      "my-[3px] w-px",
                      step.state === "complete" ? "bg-white/25" : "bg-white/[0.07]"
                    )}
                    style={{ height: "16px" }}
                  />
                )}
              </div>

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
            </div>
          );
        })}
      </div>

      {/* ── Footer: summary + metric ──────────────────────────────── */}
      <div className="mb-2.5 flex items-center justify-between gap-4">
        <p className="min-w-0 flex-1 truncate text-[10px]">
          {isRunning ? (
            <WaveText text={model.summaryText} duration={3.2} className="text-white/[0.62]" />
          ) : (
            <span className={isFailed ? "text-[rgba(255,100,100,0.45)]" : "text-white/[0.28]"}>
              {model.summaryText}
            </span>
          )}
        </p>
        <div
          className={cx(
            "shrink-0 text-right text-[11px] font-semibold",
            isFailed
              ? "text-[rgba(255,100,100,0.8)]"
              : model.status === "canceled"
                ? "text-white/35"
                : "text-white/65"
          )}
        >
          {model.metricText}
        </div>
      </div>

      {/* ── Progress bar ─────────────────────────────────────────── */}
      <div className="flex items-center gap-3">
        <div className="h-[2px] flex-1 overflow-hidden rounded-full bg-white/[0.07]">
          <div
            className={cx(
              "h-full rounded-full",
              isRunning
                ? "animate-shimmer bg-[linear-gradient(90deg,rgba(255,255,255,0.4)_0%,rgba(255,255,255,0.85)_40%,#fff_50%,rgba(255,255,255,0.85)_60%,rgba(255,255,255,0.4)_100%)] bg-[length:200%_100%]"
                : isFailed
                  ? "bg-[rgba(255,80,80,0.6)]"
                  : model.status === "canceled"
                    ? "bg-white/20"
                    : "bg-white/75"
            )}
            style={{ width: `${Math.max(6, Math.round(model.progressRatio * 100))}%` }}
          />
        </div>

        {isRunning && onCancel && (
          <button
            type="button"
            onClick={onCancel}
            aria-label="Stop research run"
            className="inline-flex h-7 w-7 shrink-0 items-center justify-center rounded-full border border-white/10 bg-white/[0.04] text-white/60 transition hover:border-white/20 hover:bg-white/[0.08]"
          >
            <svg width="9" height="9" viewBox="0 0 9 9" fill="currentColor">
              <rect width="9" height="9" rx="1" />
            </svg>
          </button>
        )}

        {isFailed && onRetry && (
          <button
            type="button"
            onClick={onRetry}
            className="inline-flex h-7 shrink-0 items-center gap-1.5 rounded-full border border-white/[0.12] bg-white/[0.04] px-3 text-[9px] font-semibold uppercase tracking-[0.12em] text-white/60 transition hover:border-white/25 hover:text-white/80"
          >
            <RotateCcw className="h-3 w-3" />
            Retry
          </button>
        )}
      </div>

      {/* ── Expanded events log (unchanged) ──────────────────────── */}
      {expanded && (
        <div className="mt-5 rounded-2xl border border-slate-800 bg-slate-950/70 p-3 md:p-4">
          <div className="mb-2 flex items-center justify-between">
            <div className="text-xs font-medium uppercase tracking-[0.18em] text-slate-500">
              Recent updates
            </div>
            <div className="text-xs text-slate-600">{model.recentEvents.length} events</div>
          </div>

          {model.recentEvents.length === 0 ? (
            <div className="rounded-xl border border-slate-900 bg-slate-950 px-3 py-4 text-sm text-slate-500">
              Waiting for live updates from the run stream.
            </div>
          ) : (
            <div className="max-h-56 space-y-2 overflow-y-auto pr-1">
              {model.recentEvents.map((event) => (
                <div
                  key={event.id}
                  className="rounded-xl border border-slate-900 bg-slate-950 px-3 py-3"
                >
                  <div className="flex items-center justify-between gap-3">
                    <div
                      className={cx(
                        "text-xs font-medium uppercase tracking-[0.14em]",
                        event.level === "error"
                          ? "text-rose-300"
                          : event.level === "warn"
                            ? "text-amber-300"
                            : "text-slate-500"
                      )}
                    >
                      {event.level}
                    </div>
                    <div className="text-xs text-slate-500">{formatTs(event.ts)}</div>
                  </div>
                  <div className="mt-1 text-sm text-slate-100">{event.message}</div>
                  {event.detail ? (
                    <div className="mt-1 text-xs text-slate-500">{event.detail}</div>
                  ) : null}
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

// ─── ProgressStepBadge ────────────────────────────────────────────────────────

type StepState = ResearchProgressCardModel["steps"][number]["state"];

function ProgressStepBadge({
  index,
  state,
  isFailed
}: {
  index: number;
  state: StepState;
  isFailed: boolean;
}) {
  if (state === "complete") {
    return (
      <span className="inline-flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-white/[0.88]">
        <Check className="h-3 w-3 stroke-[2.5] text-[#0a0a0a]" />
      </span>
    );
  }

  if (isFailed) {
    return (
      <span className="inline-flex h-7 w-7 shrink-0 items-center justify-center rounded-full border border-[rgba(255,80,80,0.3)] bg-[rgba(255,80,80,0.15)] text-[11px] font-bold text-[rgba(255,100,100,0.7)]">
        ✕
      </span>
    );
  }

  if (state === "current") {
    return (
      <span className="animate-halo-pulse inline-flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-white text-[11px] font-bold text-[#0a0a0a]">
        {index}
      </span>
    );
  }

  // pending
  return (
    <span className="inline-flex h-7 w-7 shrink-0 items-center justify-center rounded-full border border-white/[0.12] text-[11px] font-semibold text-white/20">
      {index}
    </span>
  );
}

// ─── WaveText ─────────────────────────────────────────────────────────────────

function WaveText({
  text,
  duration,
  className
}: {
  text: string;
  duration: number;
  className?: string;
}) {
  return (
    <span className={className}>
      {text.split("").map((ch, i, arr) => {
        if (ch === " ") return " ";
        const delay = -(duration * (1 - i / arr.length));
        return (
          <span
            key={i}
            className="animate-letter-breathe inline-block"
            style={{
              animationDuration: `${duration}s`,
              animationDelay: `${delay.toFixed(2)}s`
            }}
          >
            {ch}
          </span>
        );
      })}
    </span>
  );
}
```

- [ ] **Step 2: Check TypeScript compiles cleanly**

```bash
cd frontend/dashboard && npx tsc --noEmit 2>&1
```

Expected: no output (zero errors). Fix any type errors before continuing.

- [ ] **Step 3: Verify in the browser**

Start the dev server if not already running:
```bash
cd frontend/dashboard && npm run dev
```

Open `http://localhost:5173`, log in, open a project with an active research run (or trigger one). Verify:

- [ ] Card background is dark (`#0c0c0c`), rounded corners, subtle white border
- [ ] Header shows blinking dot + "Live research progress" while running
- [ ] Active step has solid white numbered circle with visible expanding halo rings
- [ ] Connector lines appear between steps (brighter for completed steps)
- [ ] Active step label text ripples left-to-right (letter-wave)
- [ ] Summary text at the bottom also ripples (slightly slower, out of phase)
- [ ] Progress bar has a light shimmer sweep while running
- [ ] Completed steps show white checkmark badge, pending show faded number
- [ ] Stop button is a small circle pill; clicking it cancels the run
- [ ] On a failed run: subtitle turns red, failed step shows ✕, retry button appears
- [ ] Expanded events log still opens and shows event rows correctly
- [ ] No console errors

- [ ] **Step 4: Commit**

```bash
git add frontend/dashboard/src/components/run/ResearchProgressCard.tsx
git commit -m "feat: redesign ResearchProgressCard — frosted glass, numbered steps, wave animation"
```

---

## Self-Review

**Spec coverage check:**

| Spec requirement | Covered by |
|-----------------|------------|
| `#0c0c0c` bg, `rgba(255,255,255,0.07)` border, `24px` radius | Task 2 card shell |
| `overflow: visible` for halo | Not needed — `box-shadow` is never clipped by a parent's `overflow: hidden` unless that parent also has `border-radius` and the child's shadow extends beyond the parent's padding-box. The card itself has no `overflow: hidden`, so the halo renders correctly. |
| Blinking dot, subtitle states | Task 2 header section |
| Numbered badges: active/done/pending/failed | Task 2 `ProgressStepBadge` |
| Connector lines with brightness states | Task 2 steps loop |
| Letter-wave on active step label (2.8s) | Task 2 `WaveText`, step label |
| Letter-wave on summary text (3.2s, offset) | Task 2 `WaveText`, footer |
| Halo pulse 2s ease-out | Task 1 keyframe + Task 2 `animate-halo-pulse` |
| Shimmer on running bar | Task 1 keyframe + Task 2 bar fill |
| Dot blink 2s | Task 1 keyframe + Task 2 `animate-dot-blink` |
| All animations off for non-running states | Task 2 — `WaveText` only rendered when `isRunning`, shimmer class only when `isRunning`, dot only when `isRunning`, halo only on `current` state |
| Events log unchanged | Task 2 — copied verbatim |
| No changes to `researchProgress.ts` | Confirmed |

**Placeholder scan:** None found.

**Type consistency:** `StepState` is derived directly from `ResearchProgressCardModel["steps"][number]["state"]` so it can never drift. `WaveText` `className` prop is optional string — consistent across both call sites.
