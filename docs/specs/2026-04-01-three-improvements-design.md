# Three High-Impact Improvements — Design Spec

**Date:** 2026-04-01
**Status:** Approved

---

## Overview

Three independent improvements, ordered by implementation risk (lowest first):

1. **Root README with Mermaid architecture diagram and eval metrics** — zero risk, adds project visibility
2. **Langfuse observability via `@observe` on pipeline nodes** — additive, opt-in via env vars
3. **Full async SQLAlchemy** — invasive but contained; API routes + worker both converted, one session implementation

Each improvement is self-contained. They can be implemented and merged independently.

---

## Improvement 1 — Root README

### Goal

Give the repo a visible face. A visitor landing on GitHub currently sees nothing. The README should convey: what the system does, how it works, what it produces, and how to run it.

### File

`README.md` at the repo root.

### Sections

**1. Header**
Project name, one-line description: _"AI-powered research pipeline with automated grounding evaluation."_

**2. What it does**
3–4 sentences: takes a research question, retrieves academic sources via MCP connectors (OpenAlex, arXiv, Europe PMC, CORE), drafts a structured report with inline citations, then runs an automated grounding evaluation scoring each section for faithfulness to the source pack.

**3. Architecture diagram**
Mermaid flowchart (`flowchart LR`) showing:
- User submits question via React frontend
- FastAPI API creates a run and queues a job
- Worker picks up the job and runs the LangGraph pipeline: `Retrieve → Outline → Draft → Evaluate → Repair → Export`
- Postgres (pgvector) stores sources, embeddings, artifacts, and eval results
- Langfuse receives traces from the pipeline (optional)
- Frontend polls for SSE events and renders the report + eval tab

**4. What it produces**
A fenced code block showing representative eval output:

```json
{
  "grounding_pct": 91,
  "faithfulness_pct": 88,
  "sections_passed": 9,
  "sections_total": 11,
  "issues_by_type": {
    "missing_citation": 3,
    "unsupported": 2
  }
}
```

Brief paragraph explaining what these numbers mean: grounding_pct is the share of sections that pass citation verification, faithfulness_pct measures claim-to-source alignment, issues_by_type enumerates detected problems by category.

**5. Quickstart**
Minimal steps:
- Prerequisites: Python 3.11, Node 20, Postgres 16 with pgvector
- Copy `.env.example` → `.env`, fill required vars (`DATABASE_URL`, `HOSTED_LLM_API_KEY`, `HOSTED_LLM_BASE_URL`, `HOSTED_LLM_MODEL`, `TAVILY_API_KEY`)
- `pip install -r requirements.txt`
- `alembic upgrade head`
- Start API: `PYTHONPATH=... python -m main` (backend/services/api)
- Start worker: `PYTHONPATH=... python -m main` (backend/services/workers)
- Start frontend: `cd frontend/dashboard && npm ci && npm run dev`

**6. Tech stack**
Table: FastAPI, LangGraph, SQLAlchemy, pgvector, React + Vite + TanStack Query, Langfuse (optional). Note: the README is written first; update "SQLAlchemy" → "SQLAlchemy (async)" once improvement 3 is merged.

### Not changing
`frontend/dashboard/README.md` is left as-is.

---

## Improvement 2 — Langfuse Observability

### Goal

Wire per-stage latency, token counts, and cost tracking into Langfuse. Every research run becomes a single trace in the Langfuse UI with child spans per pipeline node and generation events per LLM call.

### Dependencies

`langfuse` added to `requirements.txt`. Langfuse is **opt-in** — if `LANGFUSE_PUBLIC_KEY` is not set the integration is a no-op. The codebase must work identically without it.

### New env vars

| Var | Required | Description |
|---|---|---|
| `LANGFUSE_PUBLIC_KEY` | No | Langfuse public key. If absent, tracing is disabled. |
| `LANGFUSE_SECRET_KEY` | No | Langfuse secret key. |
| `LANGFUSE_HOST` | No | Override for self-hosted deployments. Defaults to `https://cloud.langfuse.com`. |

These are added to `.env` as commented-out stubs.

### New module: `libs/observability/langfuse_setup.py`

```
langfuse_enabled() -> bool
    Returns True only if LANGFUSE_PUBLIC_KEY and LANGFUSE_SECRET_KEY are set.

get_langfuse_client() -> Langfuse | None
    Returns a configured Langfuse client, or None if disabled.
    Cached at module level (singleton).
```

Langfuse is imported inside a `try/except ImportError` block so the module is safe even if `langfuse` is not installed.

`libs/observability/__init__.py` exports `langfuse_enabled`.

### Pipeline node instrumentation

Each of the seven orchestrator nodes gets the `@observe` decorator from `langfuse.decorators`:

- `nodes/retriever.py` → `retriever_node`
- `nodes/outliner.py` → `outliner_node`
- `nodes/evidence_packer.py` → `evidence_pack_node`
- `nodes/writer.py` → `writer_node`
- `nodes/evaluator.py` → `evaluator_node`
- `nodes/repair_agent.py` → `repair_agent_node`
- `nodes/exporter.py` → `exporter_node`

`@observe` wraps the function, captures wall-clock latency, and creates a Langfuse span. When `langfuse_enabled()` is False, `@observe` from `langfuse.decorators` is still safe to call — Langfuse's SDK no-ops gracefully when not initialised.

### Parent trace per run

In `runner.py`, after transitioning the run to `running`, call:

```python
langfuse_context.update_current_trace(
    name="research_run",
    id=str(run_id),
    metadata={"tenant_id": str(tenant_id), "query": user_query},
)
```

This makes all node spans nest under a single trace keyed by `run_id` in the Langfuse UI.

### Token extraction

`OpenAICompatibleClient.generate()` and `generate_with_tools()` currently discard `response.json()["usage"]`. Both methods are updated to extract `usage.prompt_tokens`, `usage.completion_tokens` and emit them via:

```python
langfuse_context.update_current_observation(
    usage={"input": prompt_tokens, "output": completion_tokens},
    model=self.model_name,
)
```

This runs inside the node's `@observe` span, so costs roll up per node and per run.

### Structured logs unchanged

`log_llm_exchange()` stays as-is. Langfuse is purely additive — token counts are also added to the existing log entry's `extra` dict (`prompt_tokens`, `completion_tokens`).

### Not changing

API routes, worker poll loop, frontend, alembic, DB models.

---

## Improvement 3 — Full Async SQLAlchemy

### Goal

Eliminate sync DB blocking in both the FastAPI event loop (API routes) and the worker. One session implementation — async throughout.

### Scope

- **`db/session.py`** — fully replaced with async-only implementation
- **All API route handlers** — converted to `async def` with `await` on DB operations
- **Worker** (`services/workers/main.py`) — wraps async calls with `asyncio.run()`
- **`db/init_db.py`** — converted to async
- **Repository functions** — converted to accept `AsyncSession`

**Not in scope:** `alembic/env.py` (constructs its own sync engine from URL string directly, not from `session.py`).

### Driver

The async SQLAlchemy engine requires `asyncpg`. Added to `requirements.txt`. The Settings `database_url` value remains `postgresql+psycopg://...` in `.env` — at engine creation time, `session.py` substitutes the driver: `psycopg` → `asyncpg` (or accepts `postgresql+asyncpg://` directly). `.env` and `alembic.ini` are unchanged.

### `db/session.py` — new implementation

```python
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

def create_db_engine(settings: Settings) -> AsyncEngine:
    url = settings.database_url.replace(
        "postgresql+psycopg://", "postgresql+asyncpg://"
    )
    return create_async_engine(url, pool_pre_ping=True, future=True)

def create_sessionmaker(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(bind=engine, expire_on_commit=False, autoflush=False)

@asynccontextmanager
async def session_scope(
    SessionLocal: async_sessionmaker[AsyncSession],
) -> AsyncIterator[AsyncSession]:
    async with SessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
```

Public API (`create_db_engine`, `create_sessionmaker`, `session_scope`) is **name-identical** to the current sync version. This minimises diff noise in callers.

### FastAPI `app.py`

No change to structure — `AsyncSessionLocal` replaces `SessionLocal` on `app.state`. A reusable dependency is added:

```python
async def get_db(request: Request) -> AsyncIterator[AsyncSession]:
    async with session_scope(request.app.state.SessionLocal) as session:
        yield session

DBDep = Annotated[AsyncSession, Depends(get_db)]
```

Routes switch from the manual `with session_scope(SessionLocal) as session:` pattern to accepting `session: DBDep`.

### Route handlers

All route handlers in:
- `routes/projects.py`
- `routes/artifacts.py`
- `routes/auth.py`
- `routes/runs.py`
- `routes/chat.py`
- `routes/evidence.py`
- `routes/health.py`

...become `async def`. All `session.execute(...)`, `session.add(...)`, `session.commit()`, `session.flush()` calls become `await session.execute(...)` etc.

### Repository functions

Repository functions in `data/db/repositories/` currently take `Session`. They are converted to take `AsyncSession`. Since these are called only from routes (via `get_db`) and from the worker (wrapped in `asyncio.run()`), there is no need for dual sync/async versions.

### Worker (`services/workers/main.py`)

The worker's sync poll loop calls async DB operations via `asyncio.run()`:

```python
def run_once(*, SessionLocal) -> bool:
    async def _inner():
        async with session_scope(SessionLocal) as session:
            job = await _claim_next_job(session)
            ...
    return asyncio.run(_inner())
```

`recover_orphaned_jobs`, `_claim_next_job`, `_mark_job_done`, `_mark_job_failed`, `_mark_run_failed` all become `async def` with `await` on DB calls. `run_forever` remains synchronous (it's a blocking loop by design).

### `db/init_db.py`

```python
async def init_db(engine: AsyncEngine) -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
```

Called with `await init_db(engine)` in `app.py` lifespan and `asyncio.run(init_db(engine))` in the worker startup.

### Error handling

`session_scope` behaviour is identical to the sync version: commit on clean exit, rollback on exception, always close. No semantic change.

### Not changing

- `alembic/env.py` — untouched, builds its own sync engine
- `alembic.ini` — untouched
- `.env` — untouched
- Orchestrator graph, pipeline nodes, LLM client — untouched
- Frontend — untouched

---

## Implementation Order

1. README (no risk, immediate value)
2. Langfuse (additive, opt-in)
3. Async SQLAlchemy (most invasive, do last so 1 and 2 are already merged)

---

## Open Questions

None. All decisions resolved during brainstorming.
