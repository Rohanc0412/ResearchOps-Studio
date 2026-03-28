# LLM Routing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add per-stage LLM model routing so users can manually assign models per pipeline stage via a modal, with automatic balanced-profile fallback for any unspecified stage.

**Architecture:** A new `resolve_model_for_stage()` function in `backend/libs/llm/__init__.py` implements a 4-level resolution chain (operator env var → user stage override → balanced profile tier → global default). `stage_models` flows from the frontend modal → chat API → run metrics → OrchestratorState → each node's LLM client call. A new `ConfigureRunModal` component intercepts the send action when "Run research report" is armed.

**Tech Stack:** Python (FastAPI, Pydantic), TypeScript (React, TanStack Query), existing `Modal` UI component, existing `MODEL_OPTIONS` constants.

---

## File Map

**Create:**
- `frontend/dashboard/src/features/chat/components/ConfigureRunModal.tsx` — per-stage model selection modal

**Modify:**
- `backend/libs/llm/__init__.py` — add `BALANCED_PROFILE`, `resolve_model_for_stage()`, update `get_llm_client_for_stage()`
- `backend/libs/core/orchestrator/state.py` — add `stage_models` field to `OrchestratorState`
- `backend/services/api/routes/chat.py` — add `stage_models` to `ChatSendRequest`, save to run usage
- `backend/services/orchestrator/research.py` — extract `stage_models` from metrics, pass to `run_orchestrator()`
- `backend/services/orchestrator/runner.py` — add `stage_models` param, set on `OrchestratorState`
- `backend/services/orchestrator/nodes/retriever.py` — pass `state.stage_models` to `get_llm_client_for_stage()`
- `backend/services/orchestrator/nodes/outliner.py` — same
- `backend/services/orchestrator/nodes/writer.py` — same
- `backend/services/orchestrator/nodes/evaluator.py` — same
- `backend/services/orchestrator/nodes/repair_agent.py` — same
- `frontend/dashboard/src/api/chat.ts` — add `stage_models` to mutation input type
- `frontend/dashboard/src/pages/ChatViewPage.tsx` — intercept send, render modal, pass `stage_models`

**Test:**
- `backend/tests/unit/test_llm_routing.py` — new unit test file for `resolve_model_for_stage()`

---

## Task 1: Backend — `resolve_model_for_stage()` in llm/__init__.py

**Files:**
- Modify: `backend/libs/llm/__init__.py`
- Create: `backend/tests/unit/test_llm_routing.py`

The exact stage name strings used in production calls are: `"retrieve"`, `"outline"`, `"draft"`, `"evaluate"`, `"repair"`.

- [ ] **Step 1: Write failing tests**

Create `backend/tests/unit/test_llm_routing.py`:

```python
from __future__ import annotations

import os
import pytest


def test_balanced_profile_keys_are_valid_stage_names():
    """BALANCED_PROFILE must cover all 5 known stage names."""
    from llm import BALANCED_PROFILE
    assert set(BALANCED_PROFILE.keys()) == {"retrieve", "outline", "draft", "evaluate", "repair"}


def test_balanced_profile_tier_values():
    """Each stage must map to 'cheap' or 'capable'."""
    from llm import BALANCED_PROFILE
    assert BALANCED_PROFILE["retrieve"] == "cheap"
    assert BALANCED_PROFILE["outline"] == "capable"
    assert BALANCED_PROFILE["draft"] == "capable"
    assert BALANCED_PROFILE["evaluate"] == "cheap"
    assert BALANCED_PROFILE["repair"] == "capable"


def test_resolve_uses_stage_models_override(monkeypatch):
    """Explicit stage_models entry wins over balanced profile."""
    monkeypatch.setenv("HOSTED_LLM_BASE_URL", "https://example.com")
    monkeypatch.setenv("HOSTED_LLM_API_KEY", "test-key")
    monkeypatch.setenv("LLM_MODEL_CHEAP", "cheap-model")
    monkeypatch.setenv("LLM_MODEL_CAPABLE", "capable-model")
    from llm import resolve_model_for_stage
    result = resolve_model_for_stage("outline", {"outline": "openai/gpt-4o"}, "hosted", None)
    assert result == "openai/gpt-4o"


def test_resolve_falls_back_to_balanced_capable(monkeypatch):
    """Null stage_models entry uses balanced profile -> LLM_MODEL_CAPABLE."""
    monkeypatch.setenv("LLM_MODEL_CAPABLE", "capable-model")
    monkeypatch.setenv("LLM_MODEL_CHEAP", "cheap-model")
    from llm import resolve_model_for_stage
    result = resolve_model_for_stage("outline", {"outline": None}, "hosted", None)
    assert result == "capable-model"


def test_resolve_falls_back_to_balanced_cheap(monkeypatch):
    """Null stage_models entry uses balanced profile -> LLM_MODEL_CHEAP for cheap stages."""
    monkeypatch.setenv("LLM_MODEL_CHEAP", "cheap-model")
    monkeypatch.setenv("LLM_MODEL_CAPABLE", "capable-model")
    from llm import resolve_model_for_stage
    result = resolve_model_for_stage("retrieve", None, "hosted", None)
    assert result == "cheap-model"


def test_resolve_capable_falls_back_to_cheap_when_unset(monkeypatch):
    """If LLM_MODEL_CAPABLE is unset, capable tier falls back to LLM_MODEL_CHEAP."""
    monkeypatch.delenv("LLM_MODEL_CAPABLE", raising=False)
    monkeypatch.setenv("LLM_MODEL_CHEAP", "only-model")
    from llm import resolve_model_for_stage
    result = resolve_model_for_stage("draft", None, "hosted", None)
    assert result == "only-model"


def test_resolve_falls_back_to_hosted_llm_model(monkeypatch):
    """When no tier env vars set, falls back to HOSTED_LLM_MODEL."""
    monkeypatch.delenv("LLM_MODEL_CHEAP", raising=False)
    monkeypatch.delenv("LLM_MODEL_CAPABLE", raising=False)
    monkeypatch.setenv("HOSTED_LLM_MODEL", "fallback-model")
    from llm import resolve_model_for_stage
    result = resolve_model_for_stage("draft", None, "hosted", None)
    assert result == "fallback-model"


def test_resolve_uses_run_level_model_override(monkeypatch):
    """run-level llm_model is used when stage_models is empty and no tier env vars."""
    monkeypatch.delenv("LLM_MODEL_CHEAP", raising=False)
    monkeypatch.delenv("LLM_MODEL_CAPABLE", raising=False)
    monkeypatch.delenv("HOSTED_LLM_MODEL", raising=False)
    from llm import resolve_model_for_stage
    result = resolve_model_for_stage("draft", {}, "hosted", "run-level-model")
    assert result == "run-level-model"


def test_get_llm_client_for_stage_accepts_stage_models(monkeypatch):
    """get_llm_client_for_stage() accepts stage_models kwarg without error."""
    monkeypatch.setenv("HOSTED_LLM_BASE_URL", "https://example.com")
    monkeypatch.setenv("HOSTED_LLM_API_KEY", "test-key")
    monkeypatch.setenv("HOSTED_LLM_MODEL", "default-model")
    from llm import get_llm_client_for_stage
    client = get_llm_client_for_stage("draft", "hosted", None, stage_models={"draft": None})
    assert client is not None
    assert client.model_name == "default-model"
```

- [ ] **Step 2: Run tests — verify they all fail**

```bash
cd backend && python -m pytest tests/unit/test_llm_routing.py -v 2>&1 | head -40
```

Expected: ImportError or AttributeError on `BALANCED_PROFILE`, `resolve_model_for_stage`.

- [ ] **Step 3: Add BALANCED_PROFILE and resolve_model_for_stage() to llm/__init__.py**

Insert after the `LLMError` class definition (after line 28) and before `OpenAICompatibleClient`:

```python
# Stage names must match the strings passed to get_llm_client_for_stage() in each node.
BALANCED_PROFILE: dict[str, str] = {
    "retrieve": "cheap",
    "outline": "capable",
    "draft": "capable",
    "evaluate": "cheap",
    "repair": "capable",
}


def resolve_model_for_stage(
    stage: str,
    stage_models: dict[str, str | None] | None,
    provider: str | None,
    model: str | None,
) -> str | None:
    """
    Resolve the model name for a pipeline stage using the 4-level priority chain:
    1. Explicit stage_models[stage] override (non-null)
    2. Balanced profile tier env var (LLM_MODEL_CAPABLE or LLM_MODEL_CHEAP)
    3. run-level llm_model argument
    4. HOSTED_LLM_MODEL env var global default
    """
    # Level 1: explicit user override
    if stage_models is not None:
        override = stage_models.get(stage)
        if override is not None:
            return override

    # Level 2: balanced profile tier
    tier = BALANCED_PROFILE.get(stage)
    if tier == "capable":
        tier_model = os.getenv("LLM_MODEL_CAPABLE") or os.getenv("LLM_MODEL_CHEAP")
    elif tier == "cheap":
        tier_model = os.getenv("LLM_MODEL_CHEAP")
    else:
        tier_model = None
    if tier_model:
        return tier_model.strip() or None

    # Level 3: run-level model
    if model:
        return model

    # Level 4: global default
    return os.getenv("HOSTED_LLM_MODEL")
```

- [ ] **Step 4: Update get_llm_client_for_stage() to accept and use stage_models**

Replace the existing `get_llm_client_for_stage` function (lines 145-162):

```python
def get_llm_client_for_stage(
    stage: str,
    provider: str | None = None,
    model: str | None = None,
    *,
    stage_models: dict[str, str | None] | None = None,
) -> LLMProvider | None:
    stage_key = stage.strip().upper().replace("-", "_")
    # Operator-level env override (highest priority — sits above user stage_models)
    provider_override = os.getenv(f"LLM_PROVIDER_{stage_key}") or os.getenv(
        f"LLM_{stage_key}_PROVIDER"
    )
    model_override = os.getenv(f"LLM_MODEL_{stage_key}") or os.getenv(f"LLM_{stage_key}_MODEL")
    resolved_provider = provider_override or provider
    # If operator has set an explicit stage env var, use it directly (skip routing)
    if model_override:
        resolved_model = model_override
    else:
        resolved_model = resolve_model_for_stage(stage, stage_models, provider, model)
    timeout_seconds = _resolve_timeout_seconds(stage_key)
    return get_llm_client(
        resolved_provider,
        resolved_model,
        timeout_seconds=timeout_seconds,
    )
```

- [ ] **Step 5: Run tests — verify all pass**

```bash
cd backend && python -m pytest tests/unit/test_llm_routing.py -v
```

Expected: All 9 tests PASS.

- [ ] **Step 6: Commit**

```bash
cd backend && git add libs/llm/__init__.py tests/unit/test_llm_routing.py
git commit -m "feat: add BALANCED_PROFILE and resolve_model_for_stage() for per-stage LLM routing"
```

---

## Task 2: Backend — Add stage_models to OrchestratorState

**Files:**
- Modify: `backend/libs/core/orchestrator/state.py:153-154`

- [ ] **Step 1: Add stage_models field to OrchestratorState**

In `backend/libs/core/orchestrator/state.py`, after line 154 (`llm_model: str | None = None`), add:

```python
    stage_models: dict[str, str | None] = Field(default_factory=dict)
```

So the Input block reads:

```python
    # Input
    user_query: str
    research_goal: str | None = None
    constraints: dict[str, Any] = Field(default_factory=dict)
    llm_provider: str | None = None
    llm_model: str | None = None
    stage_models: dict[str, str | None] = Field(default_factory=dict)
```

- [ ] **Step 2: Verify existing tests still pass**

```bash
cd backend && python -m pytest tests/unit/ -v --tb=short 2>&1 | tail -20
```

Expected: All existing unit tests PASS (no regressions from adding a defaulted field).

- [ ] **Step 3: Commit**

```bash
cd backend && git add libs/core/orchestrator/state.py
git commit -m "feat: add stage_models field to OrchestratorState"
```

---

## Task 3: Backend — Thread stage_models through chat route → research → runner

**Files:**
- Modify: `backend/services/api/routes/chat.py`
- Modify: `backend/services/orchestrator/research.py`
- Modify: `backend/services/orchestrator/runner.py`

### Part A — chat.py: accept stage_models in request, save to run metrics

- [ ] **Step 1: Add stage_models to ChatSendRequest**

In `backend/services/api/routes/chat.py`, find the `ChatSendRequest` class (around line 531) and add the field:

```python
class ChatSendRequest(BaseModel):
    project_id: UUID | None = None
    message: str = Field(min_length=1)
    client_message_id: str = Field(min_length=1, max_length=200)
    llm_provider: str | None = Field(default=None, pattern="^(hosted)$")
    llm_model: str | None = Field(default=None, min_length=1)
    force_pipeline: bool = False
    stage_models: dict[str, str | None] | None = None
```

- [ ] **Step 2: Save stage_models to run usage metrics in chat.py**

In chat.py, find the `create_run(...)` call inside the pipeline execution block (around line 919). Its `usage` dict currently ends with `"llm_model": llm_model`. Add `stage_models` to it:

```python
run = create_run(
    session=session,
    tenant_id=tenant_id,
    ...
    usage={
        "job_type": RESEARCH_JOB_TYPE,
        "user_query": pending_prompt,
        "output_type": "report",
        "research_goal": "report",
        "llm_provider": llm_provider,
        "llm_model": llm_model,
        "stage_models": json.dumps(body.stage_models) if body.stage_models else None,
    },
)
```

Confirm `import json` is present at the top of chat.py (it is — check the imports). If not, add it.

Also pass `stage_models` from the request into `_pending_action_payload` and through the pending dict so it survives the two-turn consent flow. Find `_pending_action_payload` (around line 849) and add `stage_models` to its payload dict and signature:

```python
def _pending_action_payload(
    *,
    prompt: str,
    llm_provider: str | None,
    llm_model: str | None,
    stage_models: dict[str, str | None] | None,
    created_at: datetime,
    ambiguous_count: int = 0,
) -> dict:
    payload = {
        "type": "start_research_run",
        "prompt": prompt,
        "created_at": created_at.isoformat(),
        "ambiguous_count": ambiguous_count,
    }
    if llm_provider:
        payload["llm_provider"] = llm_provider
    if llm_model:
        payload["llm_model"] = llm_model
    if stage_models:
        payload["stage_models"] = stage_models
    return payload
```

Then wherever `_pending_action_payload` is called (two call sites around lines 849 and 1141), add `stage_models=body.stage_models`.

When reading back from `pending` (around line 862), extract `stage_models`:

```python
pending_provider = pending.get("llm_provider") or llm_provider
pending_model = pending.get("llm_model") or llm_model
pending_stage_models = pending.get("stage_models") or body.stage_models
```

Use `pending_stage_models` in the `create_run` usage dict instead of `body.stage_models`.

- [ ] **Step 3: Verify chat route tests still pass**

```bash
cd backend && python -m pytest tests/unit/test_chat_flow.py -v --tb=short
```

Expected: All existing tests PASS.

### Part B — research.py: extract stage_models from metrics

- [ ] **Step 4: Extract stage_models in process_research_run()**

In `backend/services/orchestrator/research.py`, after the existing `llm_model = inputs.get("llm_model")` line (around line 31), add:

```python
import json as _json  # add at top of file if not present

# Inside process_research_run():
stage_models_raw = inputs.get("stage_models")
stage_models: dict[str, str | None] | None = None
if isinstance(stage_models_raw, str):
    try:
        stage_models = _json.loads(stage_models_raw)
    except (ValueError, TypeError):
        stage_models = None
elif isinstance(stage_models_raw, dict):
    stage_models = stage_models_raw
```

Add `stage_models=stage_models` to the `run_orchestrator(...)` call:

```python
asyncio.run(
    run_orchestrator(
        session=session,
        tenant_id=tenant_id,
        run_id=run_id,
        user_query=user_query,
        research_goal=research_goal,
        llm_provider=llm_provider,
        llm_model=llm_model,
        stage_models=stage_models,
    )
)
```

Also update the `logger.info` call to include `stage_models` in extra:

```python
logger.info(
    "Starting research pipeline run",
    extra={
        "event": "pipeline.run.start",
        "run_id": str(run_id),
        "tenant_id": str(tenant_id),
        "user_query": user_query,
        "research_goal": research_goal,
        "llm_provider": llm_provider,
        "llm_model": llm_model,
        "stage_models": stage_models,
    },
)
```

### Part C — runner.py: accept stage_models, set on OrchestratorState

- [ ] **Step 5: Add stage_models param to run_orchestrator()**

In `backend/services/orchestrator/runner.py`, update the `run_orchestrator` signature (line 106):

```python
async def run_orchestrator(
    session: Session,
    tenant_id: UUID,
    run_id: UUID,
    user_query: str,
    research_goal: str | None = None,
    llm_provider: str | None = None,
    llm_model: str | None = None,
    stage_models: dict[str, str | None] | None = None,
    max_iterations: int = 5,
) -> OrchestratorState:
```

Add `stage_models=stage_models or {}` to the `OrchestratorState(...)` initialization (around line 155):

```python
initial_state = OrchestratorState(
    tenant_id=tenant_id,
    run_id=run_id,
    user_query=user_query,
    research_goal=research_goal,
    llm_provider=llm_provider,
    llm_model=llm_model,
    stage_models=stage_models or {},
    max_iterations=max_iterations,
    started_at=datetime.now(UTC),
)
```

- [ ] **Step 6: Verify existing orchestrator tests still pass**

```bash
cd backend && python -m pytest tests/ -v --tb=short -k "not integration" 2>&1 | tail -30
```

Expected: All unit tests PASS.

- [ ] **Step 7: Commit**

```bash
cd backend && git add services/api/routes/chat.py services/orchestrator/research.py services/orchestrator/runner.py
git commit -m "feat: thread stage_models through chat route, research, and runner into OrchestratorState"
```

---

## Task 4: Backend — Update nodes to pass stage_models

**Files:**
- Modify: `backend/services/orchestrator/nodes/retriever.py`
- Modify: `backend/services/orchestrator/nodes/outliner.py`
- Modify: `backend/services/orchestrator/nodes/writer.py`
- Modify: `backend/services/orchestrator/nodes/evaluator.py`
- Modify: `backend/services/orchestrator/nodes/repair_agent.py`

Each node calls `get_llm_client_for_stage(stage_name, state.llm_provider, state.llm_model)`. Add `stage_models=state.stage_models` to each call.

- [ ] **Step 1: Update retriever.py**

Find (line 298):
```python
llm_client = get_llm_client_for_stage("retrieve", llm_provider, llm_model)
```

The retriever passes `llm_provider` and `llm_model` as local variables extracted from the state. Find all calls to `get_llm_client_for_stage("retrieve", ...)` in retriever.py (there are 2 — lines 298 and 1255). For each, determine where `llm_provider`/`llm_model` come from and add the corresponding `stage_models` arg.

If the function signature receiving those vars also receives `state`, pass `stage_models=state.stage_models`. If it only receives `llm_provider, llm_model` as separate args, you must also pass `stage_models` as an additional parameter through the call chain.

The cleanest approach: find the function containing each call, add `stage_models: dict[str, str | None] | None = None` to its signature, and pass it through. Both calls at lines 298 and 1255 should become:

```python
llm_client = get_llm_client_for_stage("retrieve", llm_provider, llm_model, stage_models=stage_models)
```

At the node entry point (where `state` is available), extract `stage_models = state.stage_models` and pass it down.

- [ ] **Step 2: Update outliner.py**

Find (line 107):
```python
llm_client = get_llm_client_for_stage("outline", state.llm_provider, state.llm_model)
```

Replace with:
```python
llm_client = get_llm_client_for_stage("outline", state.llm_provider, state.llm_model, stage_models=state.stage_models)
```

- [ ] **Step 3: Update writer.py**

Find (line 376):
```python
llm_client = get_llm_client_for_stage("draft", state.llm_provider, state.llm_model)
```

Replace with:
```python
llm_client = get_llm_client_for_stage("draft", state.llm_provider, state.llm_model, stage_models=state.stage_models)
```

- [ ] **Step 4: Update evaluator.py**

Find (line 395):
```python
llm_client = get_llm_client_for_stage("evaluate", state.llm_provider, state.llm_model)
```

Replace with:
```python
llm_client = get_llm_client_for_stage("evaluate", state.llm_provider, state.llm_model, stage_models=state.stage_models)
```

- [ ] **Step 5: Update repair_agent.py**

Find (line 565):
```python
llm_client = get_llm_client_for_stage("repair", state.llm_provider, state.llm_model)
```

Replace with:
```python
llm_client = get_llm_client_for_stage("repair", state.llm_provider, state.llm_model, stage_models=state.stage_models)
```

- [ ] **Step 6: Run full backend test suite**

```bash
cd backend && python -m pytest tests/unit/ -v --tb=short 2>&1 | tail -30
```

Expected: All tests PASS.

- [ ] **Step 7: Commit**

```bash
cd backend && git add services/orchestrator/nodes/retriever.py services/orchestrator/nodes/outliner.py services/orchestrator/nodes/writer.py services/orchestrator/nodes/evaluator.py services/orchestrator/nodes/repair_agent.py
git commit -m "feat: pass stage_models into get_llm_client_for_stage() in all pipeline nodes"
```

---

## Task 5: Frontend — ConfigureRunModal component

**Files:**
- Create: `frontend/dashboard/src/features/chat/components/ConfigureRunModal.tsx`

The modal uses the existing `Modal` component from `frontend/dashboard/src/components/ui/Modal.tsx` and `MODEL_OPTIONS`/`CUSTOM_MODEL_VALUE` from `frontend/dashboard/src/features/chat/constants.ts`.

- [ ] **Step 1: Read the existing Modal component to understand its props**

```bash
head -40 frontend/dashboard/src/components/ui/Modal.tsx
```

Note the props interface (likely `isOpen`, `onClose`, `title`, `children`).

- [ ] **Step 2: Create ConfigureRunModal.tsx**

```tsx
import { useState } from "react";
import { Modal } from "../../../components/ui/Modal";
import { MODEL_OPTIONS, CUSTOM_MODEL_VALUE } from "../constants";

export type StageModels = {
  retrieve: string | null;
  outline: string | null;
  draft: string | null;
  evaluate: string | null;
  repair: string | null;
};

const STAGES: { key: keyof StageModels; label: string }[] = [
  { key: "retrieve", label: "Retriever" },
  { key: "outline", label: "Outliner" },
  { key: "draft", label: "Writer" },
  { key: "evaluate", label: "Evaluator" },
  { key: "repair", label: "Repair Agent" },
];

const AUTO_VALUE = "__auto__";

const STAGE_OPTIONS = [
  { value: AUTO_VALUE, label: "Auto (balanced)" },
  ...MODEL_OPTIONS.filter((o) => o.value !== CUSTOM_MODEL_VALUE),
  { value: CUSTOM_MODEL_VALUE, label: "Custom…" },
];

const defaultStageModels = (): StageModels => ({
  retrieve: null,
  outline: null,
  draft: null,
  evaluate: null,
  repair: null,
});

interface Props {
  isOpen: boolean;
  onCancel: () => void;
  onStart: (stageModels: StageModels) => void;
}

export function ConfigureRunModal({ isOpen, onCancel, onStart }: Props) {
  const [selected, setSelected] = useState<Record<keyof StageModels, string>>(
    () => ({
      retrieve: AUTO_VALUE,
      outline: AUTO_VALUE,
      draft: AUTO_VALUE,
      evaluate: AUTO_VALUE,
      repair: AUTO_VALUE,
    })
  );
  const [custom, setCustom] = useState<Record<keyof StageModels, string>>(
    () => ({ retrieve: "", outline: "", draft: "", evaluate: "", repair: "" })
  );

  function handleStart() {
    const stageModels: StageModels = defaultStageModels();
    for (const { key } of STAGES) {
      const val = selected[key];
      if (val === AUTO_VALUE) {
        stageModels[key] = null;
      } else if (val === CUSTOM_MODEL_VALUE) {
        const trimmed = custom[key].trim();
        stageModels[key] = trimmed || null;
      } else {
        stageModels[key] = val;
      }
    }
    onStart(stageModels);
  }

  return (
    <Modal isOpen={isOpen} onClose={onCancel} title="Configure Research Run">
      <div className="space-y-4">
        <table className="w-full text-sm">
          <thead>
            <tr className="text-left text-xs text-slate-400">
              <th className="pb-2 pr-4 font-medium">Stage</th>
              <th className="pb-2 font-medium">Model</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-800">
            {STAGES.map(({ key, label }) => (
              <tr key={key}>
                <td className="py-2 pr-4 text-slate-300">{label}</td>
                <td className="py-2">
                  <div className="flex flex-col gap-1">
                    <select
                      value={selected[key]}
                      onChange={(e) =>
                        setSelected((prev) => ({ ...prev, [key]: e.target.value }))
                      }
                      className="rounded-md border border-slate-700 bg-slate-900 px-2 py-1 text-xs text-slate-200 focus:border-emerald-500/50 focus:outline-none"
                    >
                      {STAGE_OPTIONS.map((opt) => (
                        <option key={opt.value} value={opt.value}>
                          {opt.label}
                        </option>
                      ))}
                    </select>
                    {selected[key] === CUSTOM_MODEL_VALUE && (
                      <input
                        value={custom[key]}
                        onChange={(e) =>
                          setCustom((prev) => ({ ...prev, [key]: e.target.value }))
                        }
                        placeholder="Enter model id"
                        className="rounded-md border border-slate-700 bg-slate-900 px-2 py-1 text-xs text-slate-200 focus:border-emerald-500/50 focus:outline-none"
                      />
                    )}
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>

        <div className="flex justify-end gap-3 pt-2">
          <button
            type="button"
            onClick={onCancel}
            className="rounded-lg border border-slate-700 px-4 py-2 text-xs text-slate-400 hover:border-slate-500 hover:text-slate-200 transition-colors"
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={handleStart}
            className="rounded-lg bg-emerald-600 px-4 py-2 text-xs text-white hover:bg-emerald-500 transition-colors"
          >
            Start Run
          </button>
        </div>
      </div>
    </Modal>
  );
}
```

- [ ] **Step 3: Verify TypeScript compiles**

```bash
cd frontend/dashboard && npx tsc --noEmit 2>&1 | grep -i error | head -20
```

Expected: No errors related to `ConfigureRunModal.tsx`.

- [ ] **Step 4: Commit**

```bash
git add frontend/dashboard/src/features/chat/components/ConfigureRunModal.tsx
git commit -m "feat: add ConfigureRunModal component for per-stage model selection"
```

---

## Task 6: Frontend — Wire modal into ChatViewPage and update API client

**Files:**
- Modify: `frontend/dashboard/src/api/chat.ts`
- Modify: `frontend/dashboard/src/pages/ChatViewPage.tsx`

### Part A — Update API client type

- [ ] **Step 1: Add stage_models to useSendChatMessageMutationInfinite input type**

In `frontend/dashboard/src/api/chat.ts`, find the `mutationFn` input type inside `useSendChatMessageMutationInfinite` (around line 662):

```typescript
mutationFn: async (input: {
  conversation_id: string;
  project_id?: string;
  message: string;
  client_message_id: string;
  llm_provider?: "hosted";
  llm_model?: string;
  force_pipeline?: boolean;
  stage_models?: Record<string, string | null>;
}) =>
```

Also update the same type in `useSendChatMessageMutation` (around line 447) for consistency:

```typescript
mutationFn: async (input: {
  conversation_id: string;
  project_id?: string;
  message: string;
  client_message_id: string;
  llm_provider?: "hosted";
  llm_model?: string;
  force_pipeline?: boolean;
  stage_models?: Record<string, string | null>;
}) =>
```

### Part B — Wire modal into ChatViewPage

- [ ] **Step 2: Add imports and state to ChatViewPage**

At the top of `ChatViewPage.tsx`, add the import:

```typescript
import { ConfigureRunModal, type StageModels } from "../features/chat/components/ConfigureRunModal";
```

Inside the component body, after the existing `const [customModel, setCustomModel] = useState("")` line, add:

```typescript
const [showRunModal, setShowRunModal] = useState(false);
const [pendingDraft, setPendingDraft] = useState<string | null>(null);
```

- [ ] **Step 3: Intercept send when pipeline is armed**

In the `onSend` function (or `sendMessage` — whichever handles the keyboard submit), find the early return guard and modify the flow so that when `runPipelineArmed` is true, the modal opens instead of sending directly.

Find the `onSend` / `sendMessage` function. It currently calls `sendMessage(draft)` or similar. Modify it to:

```typescript
async function onSend() {
  const text = draft.trim();
  if (!text) return;
  if (runPipelineArmed) {
    setPendingDraft(text);
    setShowRunModal(true);
    return;
  }
  await sendMessage(text);
}
```

- [ ] **Step 4: Add handleStartRun callback**

Add this function inside the component (after `onSend`):

```typescript
async function handleStartRun(stageModels: StageModels) {
  setShowRunModal(false);
  if (!pendingDraft) return;
  const text = pendingDraft;
  setPendingDraft(null);
  setDraft("");
  await sendMessage(text, stageModels);
}
```

- [ ] **Step 5: Update sendMessage to accept and forward stage_models**

`sendMessage` currently sends with `llm_provider`, `llm_model`, `force_pipeline`. Update its signature and the `sendChat.mutateAsync` call:

```typescript
async function sendMessage(text: string, stageModels?: StageModels) {
  const trimmed = text.trim();
  if (!trimmed || !chatId) return;
  const isAction = trimmed.startsWith("__ACTION__:");
  const modelValue =
    selectedModel === CUSTOM_MODEL_VALUE ? customModel.trim() : selectedModel.trim();

  setIsTyping(true);

  try {
    const response = await sendChat.mutateAsync({
      conversation_id: chatId,
      project_id: id || undefined,
      message: trimmed,
      client_message_id: generateClientMessageId(),
      llm_provider: "hosted",
      llm_model: modelValue ? modelValue : undefined,
      force_pipeline: runPipelineArmed && !isAction,
      stage_models: stageModels ?? undefined,
    });
    // ... rest of existing handler unchanged
```

- [ ] **Step 6: Render ConfigureRunModal**

Find the JSX return in `ChatViewPage`. Add the modal just before the closing `</div>` of the root element:

```tsx
<ConfigureRunModal
  isOpen={showRunModal}
  onCancel={() => {
    setShowRunModal(false);
    setPendingDraft(null);
  }}
  onStart={handleStartRun}
/>
```

- [ ] **Step 7: Verify TypeScript compiles without errors**

```bash
cd frontend/dashboard && npx tsc --noEmit 2>&1 | grep -i error | head -20
```

Expected: No errors.

- [ ] **Step 8: Verify frontend builds**

```bash
cd frontend/dashboard && npm run build 2>&1 | tail -20
```

Expected: Build succeeds with no errors.

- [ ] **Step 9: Commit**

```bash
git add frontend/dashboard/src/api/chat.ts frontend/dashboard/src/pages/ChatViewPage.tsx
git commit -m "feat: wire ConfigureRunModal into ChatViewPage for per-stage model selection on run start"
```

---

## Self-Review

**Spec coverage check:**

| Spec requirement | Covered by |
|---|---|
| Per-stage static routing with balanced profile | Task 1 (`BALANCED_PROFILE`, `resolve_model_for_stage`) |
| `null` stage = auto balanced routing | Task 1 (`resolve_model_for_stage` level 2) |
| Explicit stage override wins over auto | Task 1 (`resolve_model_for_stage` level 1) |
| Operator env var wins over everything | Task 1 (`get_llm_client_for_stage` model_override check) |
| `stage_models` field on `OrchestratorState` | Task 2 |
| API accepts `stage_models` | Task 3A (`ChatSendRequest`) |
| `stage_models` persisted to run metrics | Task 3A (usage dict) |
| `stage_models` extracted in `research.py` | Task 3B |
| `stage_models` passed to `run_orchestrator` | Task 3B |
| `stage_models` set on `OrchestratorState` | Task 3C |
| All 5 nodes pass `stage_models` to client | Task 4 |
| Frontend modal with per-stage dropdowns | Task 5 |
| Auto (balanced) default in modal | Task 5 (`AUTO_VALUE`) |
| Custom model input per stage | Task 5 |
| Modal intercepts send when armed | Task 6 |
| Cancel preserves draft | Task 6 (Step 3: `return` without clearing draft, Step 6 cancel handler only closes modal) |
| `stage_models` forwarded in `sendChat` payload | Task 6 (Step 5) |
| Existing "LLM model" toolbar unchanged | Not touched — no changes to toolbar selects |

**Type consistency check:**

- `StageModels` defined in `ConfigureRunModal.tsx`, imported in `ChatViewPage.tsx` ✓
- `stage_models: dict[str, str | None]` in Python matches `Record<string, string | null>` in TS ✓
- Stage keys `retrieve`, `outline`, `draft`, `evaluate`, `repair` match actual `get_llm_client_for_stage()` call strings in nodes ✓
- `resolve_model_for_stage()` used inside `get_llm_client_for_stage()` consistently ✓

**Placeholder scan:** No TBDs or "implement later" entries. All code blocks are complete.
