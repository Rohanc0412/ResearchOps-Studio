# Async Orchestrator Runtime Design

**Date:** 2026-04-02
**Status:** Approved

---

## Goal

Refactor the research-run execution path so orchestration is async end-to-end, with the orchestrator runtime owning session lifecycle, transaction policy, checkpoint cadence, event emission, cancellation checks, and terminal state handling.

The key constraint is explicit: node code must not own hidden session tricks. Nodes may call repositories and services, but they must not decide transaction boundaries, create side sessions, persist checkpoints directly, or emit ad hoc database events outside orchestrator-owned APIs.

---

## Scope

This design covers the research worker and orchestrator runtime only.

In scope:
- Worker claim and dispatch flow for research jobs
- `process_research_run()` handoff into async orchestration
- Async graph execution and node wrappers
- Checkpoint persistence redesign
- Run-event persistence redesign
- Terminal success, failure, and cancellation handling
- UI-facing event semantics for the run updates dropdown

Out of scope:
- Replacing LangGraph with a custom state machine
- Frontend redesign beyond consuming cleaner event semantics
- Broad repository refactors unrelated to research orchestration
- Non-research worker job types

---

## Current Problems

The current codebase already uses `AsyncSession` in the worker, but the orchestrator falls back into synchronous control flow:

- `runner.py` extracts `session.sync_session`
- the graph is executed through sync `graph.invoke(...)`
- checkpoint storage is sync-only
- node instrumentation emits database events from inside node wrappers
- some event emission opens side sessions to make events visible earlier
- checkpoint writes and event writes are not clearly separated by purpose

This produces three architectural problems:

1. The worker is async at the boundary but sync in the core execution path.
2. Session and transaction policy are partially hidden inside node/event utilities.
3. The run updates UI receives duplicate or overly generic event rows instead of a clean, intentional stream of granular progress.

---

## Decision Summary

### 1. Keep LangGraph

The research pipeline keeps LangGraph for graph topology and routing. The refactor does not replace the graph abstraction.

Reasoning:
- lower migration risk
- preserves current node ordering and evaluator loop semantics
- removes sync escape hatches without forcing a second control-plane rewrite

### 2. Add an async orchestration runtime around LangGraph

`process_research_run()` becomes a thin async entrypoint that loads run inputs and invokes a dedicated async runtime. The runtime owns orchestration policy and persistence.

### 3. Keep one `run_events` table

Progress and diagnostics stay in one ordered event stream, but event semantics become explicit instead of overloading a single generic payload shape for every purpose.

### 4. Make checkpoints intentional

`run_checkpoints` becomes the resumability store for committed orchestration state after node execution. It stores only what is required to resume and debug replay, not every kind of event detail.

---

## Target Architecture

### Worker flow

The new worker flow is:

1. Worker claims a queued job using `AsyncSession`
2. Worker loads run inputs
3. Worker invokes `process_research_run(session=..., run_id=..., tenant_id=...)`
4. `process_research_run()` performs light setup and calls the async orchestrator runtime
5. The async runtime executes the graph node-by-node with awaited persistence
6. The runtime persists final artifacts and transitions the run to a terminal state
7. The worker marks the job done or failed outside the orchestrator result

### Runtime boundary

Introduce a dedicated async runtime module under `backend/services/orchestrator/` to own:

- run context initialization
- graph config creation
- async checkpoint reader/writer
- async event writer
- cooperative cancellation checks
- per-node execution wrappers
- explicit offloading for blocking or CPU-heavy code
- terminal success/failure/cancel transitions

The runtime should expose one top-level API for the worker, for example:

```python
async def run_research_orchestrator(
    *,
    session: AsyncSession,
    tenant_id: UUID,
    run_id: UUID,
    inputs: ResearchRunInputs,
) -> OrchestratorState:
    ...
```

The exact function name is flexible. The architectural requirement is not.

---

## Runtime Context

The runtime should initialize a single context object that is passed through orchestration-owned helpers and wrappers.

Suggested responsibilities of the context:

- `session: AsyncSession`
- `tenant_id`
- `run_id`
- loaded run inputs
- graph config values such as `thread_id`
- checkpoint store
- event store
- cancellation service
- clock/timing helpers
- blocking-work offload helper

This context is an orchestrator concern, not a node-owned dependency bag. Nodes should receive only the narrow surface they need through explicit parameters or services exposed by the runtime.

---

## Execution Model

### Async graph execution

The runtime should use LangGraph's async execution path instead of:

- `session.sync_session`
- sync node wrappers
- sync checkpoint saver APIs
- `graph.invoke(...)`

The graph topology remains:

- `retriever -> outliner -> evidence_pack -> writer -> evaluator`
- evaluator routes to `exporter`, `repair_agent`, `retriever`, or `writer`
- `repair_agent -> writer`

### Per-node wrapper responsibilities

The orchestrator wrapper around node execution should own this sequence:

1. Load or derive the current execution context
2. Check cooperative cancellation before the node
3. Invoke the node asynchronously
4. Await all persistence required after the node completes
5. Write the committed checkpoint
6. Emit progress and optional diagnostic events
7. Check cooperative cancellation again before moving on

The wrapper should not auto-emit redundant generic stage events if a node is already producing granular user-facing progress through orchestrator-owned APIs.

### Blocking work

Blocking compute and sync-only libraries must be offloaded explicitly through runtime-owned helpers such as:

```python
result = await runtime.offload_blocking(fn, *args, **kwargs)
```

Node code must not create its own executor policy or thread trickery. This makes blocking boundaries visible and testable.

---

## Transaction Policy

The runtime owns commit cadence.

Recommended policy:
- one short transaction per orchestration step
- node logic may use the shared `AsyncSession`
- nodes do not call `commit()` or `rollback()`
- checkpoint writes, stage updates, and event writes commit together after a step

This means each successful step should follow the pattern:

1. execute node logic
2. persist resulting state changes
3. persist checkpoint row
4. persist ordered events produced during the step
5. commit once

On error:
- rollback the current step transaction
- transition run status in async runtime code only
- emit terminal failure information through async persistence helpers

This avoids a single long transaction across the full run and gives clear replay boundaries.

---

## Node Contract

Nodes may still call repositories and services. They may still read and write through the shared `AsyncSession` inside the step transaction. What changes is ownership of orchestration policy.

Nodes must not:
- call `session.commit()`
- call `session.rollback()` except where a local flush failure must be converted into a domain error and re-raised
- create side database sessions
- write checkpoints directly
- append run-event rows directly
- perform hidden cancellation checks through ad hoc helpers

Nodes should instead use runtime-owned APIs for orchestration-visible behavior:

- `emit_progress(...)`
- `emit_diagnostic(...)`
- `offload_blocking(...)`
- repository/service calls using the provided `AsyncSession`

This preserves node autonomy for business logic while removing hidden orchestration side channels.

---

## Event Model

### Goals

The run updates dropdown should show what is actually happening:

- searching specific sources
- processing papers
- embedding papers
- packing evidence
- drafting sections
- evaluating sections
- exporting artifacts

Granular progress is required. Duplicate ownership is not.

### Storage decision

Keep a single `run_events` table, but make event semantics explicit.

Add a classifier field such as `audience` or `stream`:

- `progress`
- `diagnostic`
- `state`

Suggested direction: use `audience`, because it maps more clearly to UI consumption.

### Event ownership

The orchestrator runtime owns event persistence. Nodes may request events through runtime APIs, but they must not write rows directly.

This removes the current double-emission pattern where:
- generic wrapper events are inserted
- node internals also emit granular updates

### Event granularity

Granular `progress` events are allowed and expected. The constraint is one writer path, not one event per node.

Examples of `progress` events:
- `search_started`
- `connector_query_started`
- `connector_query_completed`
- `paper_processing_started`
- `paper_processed`
- `embedding_started`
- `embedding_progress`
- `embedding_completed`
- `evidence_packed`
- `draft_section_completed`
- `evaluation_section_completed`
- `repair_section_completed`
- `node_completed`

Examples of `diagnostic` events:
- connector retry details
- latency or size metrics not needed in the main UI
- payload summaries for debugging
- exception context beyond the concise progress message

Examples of `state` events:
- `created -> queued`
- `queued -> running`
- `running -> failed`
- `running -> canceled`
- `running -> succeeded`

### UI rule

`ResearchProgressCard` should read:
- `progress` events
- optionally terminal `state` events

It should not treat `diagnostic` events as user-facing updates by default.

### Duplicate prevention

The primary duplicate-prevention mechanism is ownership:
- runtime persistence helpers are the only code path that inserts event rows
- wrapper code stops emitting generic progress rows that duplicate granular node updates

Optional dedupe keys can be added later, but the design should not depend on best-effort deduplication to fix architectural duplication.

---

## Checkpoint Model

### Purpose

`run_checkpoints` should store resumable orchestration state plus minimal metadata needed for replay and debugging.

### Checkpoint write cadence

Write one committed checkpoint after each successful node completion.

That checkpoint should correspond to the exact state from which the next node can resume.

### Checkpoint payload

Recommended contents:
- serialized orchestrator state required for resume
- current node name or last completed node
- iteration count
- checkpoint schema version
- checkpoint timestamp
- compact summary metadata for debugging

Avoid storing:
- repeated user-facing event text
- large diagnostic blobs that belong in `run_events`
- duplicate artifact payloads already stored elsewhere

### Resume semantics

Resume should load the latest checkpoint from `run_checkpoints`, rebuild the runtime context, and continue graph execution from the next step with async-only code paths.

The old sync-only `PostgresCheckpointSaver` path should be retired or replaced by an async persistence adapter that targets `run_checkpoints`.

---

## Run Lifecycle Ownership

The async runtime owns terminal behavior completely.

### Success

On completion:
- persist final artifacts in async code
- update final run stage and metadata
- transition run status to `succeeded`
- emit any final user-facing completion event through the same async runtime path

### Failure

On failure:
- rollback the in-flight step transaction
- write failure transition in async code only
- emit concise user-facing failure progress/state event
- optionally emit richer diagnostic event

### Cancellation

On cooperative cancellation:
- the runtime detects cancellation before or after steps
- no sync side channel handles rollback or terminal transition
- the runtime transitions the run to `canceled`
- final cancellation event/state is written through async persistence helpers

This ensures success, failure, and cancellation all pass through the same orchestration-owned policy layer.

---

## Data Model Changes

### `run_events`

Add explicit classification:
- `audience` enum/string with `progress`, `diagnostic`, `state`

Keep existing useful fields:
- `event_number`
- `ts`
- `stage`
- `event_type`
- `level`
- `message`
- `payload_json`

Potential follow-up refinement:
- add lightweight validation conventions per `audience`/`event_type` rather than making the schema much wider immediately

### `run_checkpoints`

Retain the table, but make its payload contract explicit and versioned.

Potential additions:
- `checkpoint_version`
- `node_name`
- `iteration_count`
- optional `summary_json` if replay/debug metadata should stay distinct from resumable state

The exact column set can be finalized during implementation once current resume requirements are mapped against `OrchestratorState`.

---

## Backend Module Changes

Expected module responsibilities after refactor:

- `services/workers/main.py`
  - claim job with `AsyncSession`
  - call `process_research_run()`
  - mark job done/failed

- `services/orchestrator/research.py`
  - load run inputs
  - warm embed pool if needed
  - invoke the async runtime

- `services/orchestrator/runner.py` or a new runtime module
  - initialize runtime context
  - manage graph execution
  - own transitions, events, checkpoints, artifacts, failure handling

- `services/orchestrator/graph.py`
  - define async graph nodes/wrappers
  - remove sync-session assumptions

- `services/orchestrator/checkpoints.py`
  - replace sync saver behavior with async persistence adapter for `run_checkpoints`

- `libs/core/pipeline_events/*`
  - replace direct DB-writing helpers with runtime-facing event interfaces or async persistence helpers

- orchestrator node modules
  - stop direct event-row writes
  - stop hidden session side effects
  - use runtime-provided event emission helpers where needed

---

## Testing Strategy

### Unit tests

Add or update tests for:
- async runtime transitions through success, failure, and cancellation
- checkpoint writes after successful node completion
- resume from latest checkpoint using async code path
- event classification and event ordering
- granular progress emission without duplicate rows
- node wrappers enforcing runtime-owned cancellation and persistence
- offload helper behavior for blocking work

### Integration tests

Update orchestration integration tests to cover:
- full async research run with persisted events/checkpoints
- cancellation during a multi-step run
- failure mid-node or post-node persistence failure
- `ResearchProgressCard` event feed semantics through API event listing

### Regression focus

Specific regressions to guard against:
- reintroduction of `session.sync_session`
- duplicate progress events for the same sub-step
- writes to `run_events` from side sessions
- node code calling `commit()` or `rollback()` directly

---

## Migration Strategy

Implement in bounded phases:

1. Introduce async runtime context and event/checkpoint persistence adapters
2. Convert graph execution to async wrappers
3. Migrate node event emission from direct DB writes to runtime APIs
4. Redesign `run_events` classification and checkpoint payload contract
5. Update tests and UI event consumption assumptions
6. Remove obsolete sync checkpoint/event paths

This sequence reduces risk by moving ownership first, then deleting sync fallbacks once coverage exists.

---

## Risks And Mitigations

### Risk: LangGraph async integration still leaves hidden sync edges

Mitigation:
- ban `session.sync_session` usage in orchestrator modules
- add tests or grep-based checks around runtime code paths

### Risk: granular progress becomes noisy again

Mitigation:
- define event taxonomy up front
- route all event writes through one runtime API
- make the UI consume only `progress` plus terminal `state`

### Risk: checkpoint payload grows uncontrolled

Mitigation:
- version checkpoint schema
- document allowed contents
- keep large diagnostics in `run_events`

### Risk: node conversion causes broad churn

Mitigation:
- preserve node business logic where possible
- change orchestration surface first
- offload blocking internals explicitly instead of rewriting every service at once

---

## Open Questions

None blocking for implementation planning.

The remaining details are implementation-level choices:
- exact runtime module names
- exact `audience` enum implementation
- whether checkpoint metadata stays in one JSON blob or is split into explicit columns

These should be resolved in the implementation plan, not through another architecture round.
