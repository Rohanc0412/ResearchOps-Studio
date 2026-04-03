# E2E Bug Fixes — Design Spec

**Date:** 2026-04-03  
**Scope:** Four bugs found during a clean end-to-end research run and manual QA.

---

## Bug 1 (High) — `greenlet_spawn` crash blocks all report runs

### Root cause

`evidence_pack_node` is a sync node, dispatched via `runtime.session.run_sync()` in
`ResearchRuntime.execute_node`. Inside, `_parallel_search_sections` spawns a
`ThreadPoolExecutor`. Each thread calls `Session(engine)` where the engine is the
asyncpg-backed async engine. OS threads have no greenlet context; asyncpg's sync facade
requires one. Result: `greenlet_spawn has not been called; can't call await_only() here`.

### Decision

Keep parallelism (user choice). Convert `evidence_pack_node` to an async node so the
runner dispatches it via `await node_func(state, runtime)` with a `ResearchRuntime`.

### Design

**`evidence_packer.py`**

- Replace `_parallel_search_sections(section_queries, engine, ...)` with
  `_parallel_search_sections_async(section_queries, async_engine, ...)`.
- Per-section concurrency uses `asyncio.gather` bounded by an `asyncio.Semaphore`
  (size = `EVIDENCE_PACK_PARALLEL_SECTIONS`, default 4).
- Each concurrent task opens its own `AsyncSession(async_engine)` and calls
  `await session.run_sync(lambda s: _search_one_sync(s, ...))`. `run_sync` provides
  the greenlet context asyncpg requires; no threads involved.
- `_search_one_sync` contains the existing per-section search logic (multi-angle search,
  relaxed fallback, dedup) unchanged — it is a plain sync function called inside `run_sync`.
- Remove `@instrument_node("evidence_pack")` decorator — it is sync-only and incompatible
  with async nodes. Emit stage-start, per-section progress, and stage-finish events
  directly via `runtime.event_store.append(audience=RunEventAudienceDb.progress, ...)`.
- Change signature: `evidence_pack_node(state, session: Session)` →
  `async def evidence_pack_node(state, runtime: ResearchRuntime)`.
- Obtain async engine: `async_engine = runtime.session.get_bind()`.
- Wrap sync DB helpers (`_ensure_snippets_from_abstracts`, `_persist_section_evidence`)
  in `await runtime.session.run_sync(lambda s: fn(s, ...))`.
- Commit via `await runtime.session.commit()` after the abstract-fallback phase so
  per-section sessions see the newly inserted embeddings (same semantics as before).

**`runtime.py`** — no changes needed. `execute_node` already dispatches async node
functions via `await node_func(state, self)`.

---

## Bug 2 (Medium) — Live progress shows 0 events

### Root cause

All queued node events flow through `ResearchRuntime.flush_pending_events()` in
`runtime.py`. That method hardcodes `audience=RunEventAudienceDb.diagnostic` when
writing every queued event. The frontend's `filterProgressContractEvents` in
`researchProgress.ts` only surfaces events with `audience === "progress"`. All
stage-start, stage-finish, and node-progress events are in the DB but invisible to the UI.

Secondary: `append_run_event_sync` in `project_runs.py` has no `audience` parameter,
so events written via the `_RunnerRuntimeAdapter` fallback path also default to
`diagnostic`.

### Design

**`runtime.py`**

- Add `audience: RunEventAudienceDb` field to `_QueuedNodeEvent` dataclass,
  defaulting to `RunEventAudienceDb.progress`.
- Add `audience: RunEventAudienceDb = RunEventAudienceDb.progress` parameter to
  `queue_node_event`. Store it in the queued event.
- In `flush_pending_events`, pass `audience=event.audience` (was hardcoded `diagnostic`).

**`project_runs.py`**

- Add `audience: RunEventAudienceDb = RunEventAudienceDb.progress` parameter to
  `append_run_event_sync`. Pass it through to the `RunEventRow` constructor.

No frontend changes needed — the filter logic is correct; only the backend audience was wrong.

---

## Bug 3 (Medium) — Web search claims to browse but delivers no results

### Root cause

`_generate_quick_answer` in `chat.py` builds result snippets with:

```python
snippets = [
    f"[{i+1}] {r.get('title','')}: {r.get('content','')[:300]}"
    for i, r in enumerate(results)
]
```

`tavily.search()` returns `list[SearchResult]` where `SearchResult` is a `@dataclass`
with fields `title`, `url`, `snippet`. Dataclasses have no `.get()` method, so both
calls raise `AttributeError`. The bare `except Exception` swallows this and sets
`tool_result = "Web search unavailable."`. The LLM then correctly reports no search
results were found, contradicting the "Searching the web…" status already shown.

### Design

**`chat.py`** — two-character fix in the list comprehension:

```python
snippets = [
    f"[{i+1}] {r.title}: {r.snippet[:300]}"
    for i, r in enumerate(results)
]
```

`r.title` (was `r.get('title','')`) and `r.snippet` (was `r.get('content','')` — also
wrong field name; the dataclass field is `snippet`, not `content`).

---

## Bug 4 (Medium) — Layout freezes on browser window resize

### Root cause

`AppLayout` renders `main` as a `flex-col` container. `ChatViewPage`'s root div is a
flex child of that column, but uses `h-full min-h-0` instead of `flex-1 min-h-0`.

`h-full` on a flex child inside a `flex-col` parent does not participate in the flex
grow/shrink algorithm. When the browser window is resized, flex children with `flex-1`
reflow; children with `h-full` do not update because `h-full` resolves against the
scroll container's initial computed height, not the live viewport.

### Design

**`ChatViewPage.tsx:329`** — one class swap:

```tsx
// before
<div className="flex h-full min-h-0 bg-slate-950 text-slate-200">
// after
<div className="flex flex-1 min-h-0 bg-slate-950 text-slate-200">
```

No changes to `AppLayout`, `ReportPane`, or `ChatMessageList`. Those components are
already correctly structured (`flex-1 overflow-y-auto` for scroll areas, `min-h-0` on
flex panels).

---

## Files changed

| File | Bug |
|---|---|
| `backend/services/orchestrator/nodes/evidence_packer.py` | 1 |
| `backend/services/orchestrator/runtime.py` | 1, 2 |
| `backend/data/db/repositories/project_runs.py` | 2 |
| `backend/services/api/routes/chat.py` | 3 |
| `frontend/dashboard/src/pages/ChatViewPage.tsx` | 4 |
