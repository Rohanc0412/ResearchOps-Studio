# ResearchProgressCard Redesign

**Date:** 2026-03-27
**Component:** `frontend/dashboard/src/components/run/ResearchProgressCard.tsx`
**Status:** Approved

---

## Summary

Redesign the `ResearchProgressCard` to be visually polished and alive while the research pipeline runs. The approved direction is **Frosted Glass + Numbered + Connected** steps with three active animations.

---

## Visual Design

### Card Shell

- Background: `#0c0c0c`
- Border: `1px solid rgba(255,255,255,0.07)`
- Border radius: `24px`
- Box shadow: `0 24px 64px rgba(0,0,0,0.5), inset 0 1px 0 rgba(255,255,255,0.04)`
- Padding: `22px`
- `overflow: visible` — required so the halo pulse on the active step is not clipped

### Header

- Title: `#f8fafc`, `14px`, `font-weight: 600`, `letter-spacing: -0.01em`
- Subtitle row: blinking dot + "Live research progress" text
  - Dot: `5px` circle, `rgba(255,255,255,0.4)`, blink animation (see Animations)
  - Text: `rgba(255,255,255,0.28)`, `9px`, `uppercase`, `letter-spacing: 0.18em`
  - Failed state: subtitle becomes `rgba(255,100,100,0.5)` + text "Run failed — review or retry"
- Updates button: `rgba(255,255,255,0.04)` background, `rgba(255,255,255,0.09)` border, `20px` border-radius pill

### Step List (Numbered + Connected)

Each step has two parts: a **track column** (circle + connector line) and a **label**.

**Step circle states:**

| State | Style |
|-------|-------|
| `active` | Solid white `#fff`, dark number, halo pulse animation |
| `done` | `rgba(255,255,255,0.88)` fill, dark checkmark SVG (no number) |
| `pending` | `1px solid rgba(255,255,255,0.12)` border, `rgba(255,255,255,0.2)` number |
| `failed` | `rgba(255,80,80,0.15)` bg, `rgba(255,80,80,0.3)` border, `✕` symbol |

**Connector line** between steps:
- `done` → `done`: `rgba(255,255,255,0.25)`
- `done` → `active` or `active` → `pending`: `rgba(255,255,255,0.07)`
- Width: `1px`, height: `16px`, margin `3px 0`

**Step label states:**

| State | Color |
|-------|-------|
| `active` | `#f8fafc`, `font-weight: 500`, **wave animation** |
| `done` | `rgba(255,255,255,0.45)` static |
| `pending` | `rgba(255,255,255,0.16)` static |

### Footer

- Summary text: `rgba(255,255,255,0.62)`, `10px`, **wave animation** (slightly slower cycle than step label)
- Metric text (step counter / source count): `rgba(255,255,255,0.65)`, `11px`, `font-weight: 600`
- Failed metric: `rgba(255,100,100,0.8)` "Needs retry"
- Stopped metric: `rgba(255,255,255,0.35)` "Stopped"

### Progress Bar

- Track: `2px` height, `rgba(255,255,255,0.07)` background
- Fill: shimmer animation (see Animations)
- Failed fill: `rgba(255,80,80,0.6)`, no shimmer
- Stopped fill: `rgba(255,255,255,0.2)`, no shimmer

### Stop / Retry Buttons

- Stop: `28px` circle, `rgba(255,255,255,0.04)` bg, `rgba(255,255,255,0.1)` border, square icon
- Retry: pill button, `rgba(255,255,255,0.04)` bg, `rgba(255,255,255,0.12)` border, `↺ Retry` label

---

## Animations

### 1. Letter-wave (breathing text)

Applies to: active step label and summary text.

Each character is wrapped in its own `<span>` with a staggered `animation-delay` so the opacity wave ripples **left to right** across the full string.

```
delay_i = -(duration * (1 - i / total))   // negative = start mid-cycle immediately
```

Keyframe:
```css
@keyframes letter-breathe {
  0%, 100% { opacity: 1; }
  50%       { opacity: 0.45; }
}
```

- Active step label: `duration = 2.8s`, `ease-in-out`, `infinite`
- Summary text: `duration = 3.2s`, `ease-in-out`, `infinite` (offset so they're never in phase)

**React implementation:** a `WaveText` component that splits `children` string into `<span>` elements and applies inline `animationDelay` style to each. Renders a plain `<span>` when the run is not active (no animation overhead on completed/failed cards).

### 2. Halo pulse (active step circle)

An expanding double-ring that fires from the active step badge outward, then resets.

```css
@keyframes halo-pulse {
  0%   { box-shadow: 0 0 0 0px  rgba(255,255,255,0.55), 0 0 0 0px  rgba(255,255,255,0.15); }
  60%  { box-shadow: 0 0 0 6px  rgba(255,255,255,0.08), 0 0 0 12px rgba(255,255,255,0.04); }
  100% { box-shadow: 0 0 0 10px rgba(255,255,255,0.0),  0 0 0 18px rgba(255,255,255,0.0); }
}
```

- Duration: `2s`, `ease-out`, `infinite`
- Only applied when step state is `current` / `active`

### 3. Progress bar shimmer

A light sweep travelling left-to-right across the filled portion of the bar.

```css
background: linear-gradient(
  90deg,
  rgba(255,255,255,0.4) 0%,
  rgba(255,255,255,0.85) 40%,
  white 50%,
  rgba(255,255,255,0.85) 60%,
  rgba(255,255,255,0.4) 100%
);
background-size: 200% 100%;

@keyframes shimmer {
  0%   { background-position: -200% center; }
  100% { background-position:  200% center; }
}
```

- Duration: `2.5s`, `linear`, `infinite`
- Only applied on `running` status

### 4. Dot blink (subtitle indicator)

```css
@keyframes dot-blink {
  0%, 100% { opacity: 1; }
  50%       { opacity: 0.2; }
}
```

- Duration: `2s`, `ease-in-out`, `infinite`
- Only rendered on `running` status

---

## States

| Status | Subtitle | Metric | Bar | Animations |
|--------|----------|--------|-----|------------|
| `running` | Dot + "Live research progress" | Step N of 5 / source count | White shimmer | All 4 active |
| `succeeded` | "Live research progress" (no dot) | "Done" | Full white, no shimmer | None |
| `failed` | Red "Run failed — review or retry" | Red "Needs retry" | Red bar, no shimmer | None |
| `canceled` | "Run stopped before finishing" | Grey "Stopped" | Grey bar, no shimmer | None |

---

## Out of Scope

- The expanded events log (Updates panel) — structure and styling unchanged
- `researchProgress.ts` model logic — no changes
- Any other component in the codebase
