# LLM Routing — Design Spec

**Date:** 2026-03-28
**Status:** Approved

---

## Overview

Implement per-stage LLM routing to reduce token costs without sacrificing output quality. Users configure model selection per pipeline stage via a modal that appears every time a research run starts. Stages left unspecified fall back to automatic balanced routing (cheap model for low-complexity stages, capable model for high-value stages).

---

## Problem

All 5 LLM-using pipeline stages (Retriever, Outliner, Writer, Evaluator, Repair Agent) currently use the same single model for an entire run. Low-complexity stages (Retriever, Evaluator) do not benefit from a capable model but incur the same cost. Since Evaluator can loop multiple times per section, this compounds across long reports.

---

## Design Decisions

- **Routing strategy:** Per-stage static model routing (not dynamic/complexity-based)
- **Configuration surface:** Modal popup on every run start — always shown, defaults to Auto
- **Default routing:** Balanced profile (cheap model for Retriever + Evaluator, capable model for Outliner + Writer + Repair)
- **Manual override:** User can select a specific model for any stage in the modal; omitted stages use automatic routing

---

## Balanced Profile (Automatic Routing)

| Stage | Tier | Rationale |
|---|---|---|
| Retriever | cheap | Generates search query strings — deterministic, low-complexity |
| Outliner | capable | Synthesises research structure — requires reasoning |
| Writer | capable | Core quality output — most token-intensive, highest impact |
| Evaluator | cheap | Rubric-based scoring — analytical but structured |
| Repair Agent | capable | Surgical precision text fixes — correctness matters |

**Tier → model resolution (env vars):**
- `LLM_MODEL_CHEAP` — default: falls back to `HOSTED_LLM_MODEL`
- `LLM_MODEL_CAPABLE` — default: falls back to `LLM_MODEL_CHEAP` (preserves existing behaviour when not set)

---

## API Contract

### Request

`POST /projects/{project_id}/runs`

New optional field added to the existing request body:

```json
{
  "question": "...",
  "llm_provider": "hosted",
  "llm_model": "openai/gpt-4o-mini",
  "stage_models": {
    "retriever": null,
    "outliner": "openai/gpt-4o",
    "writer": "openai/gpt-4o",
    "evaluator": null,
    "repair": null
  }
}
```

- `stage_models` is optional. If omitted entirely, all stages use automatic balanced routing.
- Per-stage value of `null` or missing key = use automatic balanced routing for that stage.
- Per-stage value of a non-null string = use that model ID explicitly for that stage.

### Valid stage keys

`retriever`, `outliner`, `writer`, `evaluator`, `repair`

> **Implementation note:** These API-facing keys must match the internal stage name strings passed to `get_llm_client_for_stage()` in each node (e.g. if the outliner node calls `get_llm_client_for_stage("outline", ...)`, then the API key must be `"outline"`, not `"outliner"`). Verify exact names in node files before implementing and align the frontend modal labels accordingly.

---

## Backend Resolution Order (per stage, evaluated at node execution time)

```
1. stage_models[stage] from run (explicit user override, non-null)
2. Balanced profile tier → LLM_MODEL_CAPABLE or LLM_MODEL_CHEAP env var
3. HOSTED_LLM_MODEL env var (existing global default)
4. Error if none resolvable (for required stages)
```

Existing `LLM_MODEL_{STAGE}` env var overrides (e.g. `LLM_MODEL_OUTLINE`) retain highest priority and sit above step 1. This preserves operator-level control.

Final resolution order (complete):

```
LLM_MODEL_{STAGE} env var          ← operator override (highest)
  → stage_models[stage] from run   ← user explicit choice
    → balanced profile tier env var ← automatic routing
      → HOSTED_LLM_MODEL           ← global default (lowest)
```

---

## Data Flow

```
User sends message (run pipeline armed)
  → "Configure Research Run" modal appears
  → User configures per-stage models (or leaves as Auto)
  → User clicks "Start Run"
  → sendChat() includes stage_models in payload
  → POST /chat → backend extracts stage_models
  → POST /projects/{id}/runs with stage_models
  → stage_models saved to run_usage_metrics (as JSON metric)
  → Worker picks up run, extracts stage_models from metrics
  → OrchestratorState initialised with stage_models
  → Each node calls get_llm_client_for_stage(stage, provider, model, stage_models)
  → Resolution order applied, correct client returned
  → Run executes with per-stage model assignment
```

---

## Backend Changes

### `backend/libs/llm/__init__.py`

- Add `BALANCED_PROFILE: dict[str, str]` mapping stage names to tier (`"cheap"` or `"capable"`)
- Add `resolve_model_for_stage(stage, stage_models, provider, model)` function implementing the full resolution order
- Modify `get_llm_client_for_stage()` to accept `stage_models: dict[str, str | None] | None` and use `resolve_model_for_stage`

### `backend/libs/core/orchestrator/state.py`

- Add field: `stage_models: dict[str, str | None] = {}`

### `backend/services/api/routes/chat.py`

- Accept `stage_models: dict[str, str | None] | None` in the chat request body
- Forward to run creation logic

### `backend/services/api/app_services/project_runs.py`

- Accept `stage_models` in `create_project_run()`
- Serialise to JSON and save as a metric: `metric_name="stage_models"`, `metric_text=json.dumps(stage_models)`

### `backend/services/orchestrator/research.py`

- Extract `stage_models` from run metrics (deserialise JSON)
- Pass into `run_orchestrator()` → `OrchestratorState`

### Node files (retriever, outliner, writer, evaluator, repair_agent)

- Each passes `state.stage_models` into `get_llm_client_for_stage()`
- No structural change to nodes beyond this added argument

---

## Frontend Changes

### New component: `ConfigureRunModal`

**Location:** `frontend/dashboard/src/features/chat/components/ConfigureRunModal.tsx`

**Trigger:** Replaces the direct `onSend()` call when `runPipelineArmed` is true. Instead of sending immediately, the modal opens.

**Content:**

```
┌─────────────────────────────────────────────┐
│  Configure Research Run                   × │
├─────────────────────────────────────────────┤
│  Stage          Model                        │
│  ─────────────────────────────────────────  │
│  Retriever      [ Auto (balanced)        ▼ ] │
│  Outliner       [ Auto (balanced)        ▼ ] │
│  Writer         [ Auto (balanced)        ▼ ] │
│  Evaluator      [ Auto (balanced)        ▼ ] │
│  Repair Agent   [ Auto (balanced)        ▼ ] │
│                                             │
│              [Cancel]  [Start Run]          │
└─────────────────────────────────────────────┘
```

**Model options per stage dropdown:**
- `Auto (balanced)` (value: `null`) — default
- All existing `MODEL_OPTIONS` from the current model selector
- `Custom…` — reveals a text input for a manual model ID (same pattern as existing custom model input)

**On "Start Run":** Calls `onSend()` with `stage_models` derived from the modal state. Stages left as Auto emit `null`.

**On "Cancel":** Closes modal, draft preserved, no send.

### `ChatViewPage.tsx`

- Add `showRunModal: boolean` state
- When `runPipelineArmed` is true and user presses Enter or clicks send: set `showRunModal = true` instead of calling `onSend()` directly
- Pass `stage_models` into the `sendChat()` payload (alongside existing `llm_provider` / `llm_model`)
- Render `<ConfigureRunModal>` conditionally

### Existing "LLM model" toolbar dropdown

- No change — continues to apply to regular chat messages (non-pipeline)
- Not shown in the modal (modal manages its own per-stage model state)

---

## Error Handling

- If `stage_models` contains an unrecognised stage key, the backend ignores unknown keys silently (only known stages are used)
- If a specified model ID is invalid or unavailable, the LLM client raises the same error as today (no special handling needed)
- Modal cancel does not send the message — draft is preserved

---

## Testing

- **Unit:** `resolve_model_for_stage()` — test all resolution priority combinations (env override wins, explicit stage_models wins over auto, balanced profile applied correctly, fallback to global default)
- **Integration:** Run creation with `stage_models` — verify correct model assigned per stage in OrchestratorState
- **Frontend:** Modal renders with Auto defaults, model selection propagates to payload, cancel preserves draft

---

## Out of Scope

- Token counting or cost tracking per run
- Provider-level routing (multi-provider fallback)
- Saving/restoring modal preferences between sessions
- Admin UI for configuring `LLM_MODEL_CHEAP` / `LLM_MODEL_CAPABLE`
