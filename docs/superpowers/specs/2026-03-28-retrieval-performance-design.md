# Retrieval Performance Optimization Design

**Date:** 2026-03-28
**Status:** Approved
**Context:** End-to-end retrieval is slow (~3–5 minutes). Three primary bottlenecks identified: serial MCP queries, sequential single-process embedding, and sequential per-section evidence packing.

---

## Problem

The retrieval pipeline has three serial bottlenecks:

1. **MCP search (biggest):** 6–10 diverse queries fire one-at-a-time through `npx` subprocess calls, each subject to a 0.5 req/sec rate limit. Estimated 30–60 seconds just for this stage.
2. **Embedding / reranking:** `_embed_texts_batched()` runs batches of 32 sequentially in one process. On CPU, a single SentenceTransformer instance uses only one core.
3. **Evidence packing:** 6–10 outline sections each do an embed + pgvector search sequentially after the outline is produced.

---

## Solution Overview

Three complementary changes, each independent and incrementally deployable:

| Change | Bottleneck addressed | Expected speedup |
|---|---|---|
| Multiprocess embedding pool | Embedding / reranking | ~2× |
| Parallel MCP queries | MCP search | ~4–8× |
| Parallel evidence sections | Evidence packing | ~3–5× |

**Combined end-to-end estimate: ~3–4× faster.**

---

## Change 1: Multiprocess Embedding Pool

### Architecture

A module-level `EmbedWorkerPool` singleton in `backend/services/orchestrator/embeddings.py`. On first use it spawns N worker processes via `concurrent.futures.ProcessPoolExecutor`. Each worker pre-loads the SentenceTransformer model in its own process memory. The main process fans text chunks to workers and collects results.

```
Main process                 Worker processes (N=2 default)
──────────────               ────────────────────────────────
                             Process-0: bge-m3 loaded, idle
                             Process-1: bge-m3 loaded, idle
texts → chunk into N groups
                             Process-0 ← chunk-A
                             Process-1 ← chunk-B
                             Process-0 ← chunk-C (reused)
gather results ─────────────
```

### Key decisions

- **`ProcessPoolExecutor`** over raw `multiprocessing.Queue` — simpler API, futures integrate with existing `concurrent.futures` patterns already in the codebase.
- **Lazy init** — pool is created on first `embed_texts()` call, not at import time. Guarded by a module-level lock so concurrent first calls are safe.
- **Chunk distribution** — texts split into N equal chunks, one per worker. Each worker handles its chunk in one call (not split further into batches; the worker's internal batch size is `RETRIEVER_EMBED_BATCH`).
- **Fallback** — if pool init fails (e.g., pickling error), fall back silently to existing single-process path.
- **Shutdown** — pool is shut down via `atexit` handler; no explicit teardown needed from node code.

### Configuration

```
RETRIEVER_EMBED_WORKERS=2   # number of worker processes (default: min(2, cpu_count//2))
                            # each worker ≈ 1.5 GB RAM for bge-m3
```

### Integration

Replace the body of `_embed_texts_batched()` in both `retriever.py` and `evidence_packer.py` with a call to `EmbedWorkerPool.encode(texts)`. The function signature stays identical — callers don't change.

---

## Change 2: Parallel MCP Queries

### Architecture

The MCP search loop in `retriever.py` (~line 1296) currently iterates queries serially. Replace with `ThreadPoolExecutor`:

```python
# Before
for query in query_plan.queries:
    results = connector.search(query, max_results=...)
    all_results.extend(results)

# After
with ThreadPoolExecutor(max_workers=RETRIEVER_MCP_PARALLEL_QUERIES) as pool:
    futures = {pool.submit(_search_one, query): query for query in query_plan.queries}
    for future in as_completed(futures):
        all_results.extend(future.result())
```

### Why threads, not asyncio

MCP calls spawn `npx` subprocesses — blocking OS calls. `ThreadPoolExecutor` is the correct tool: threads release the GIL during subprocess waits, achieving true parallelism. Converting to `asyncio.create_subprocess_exec` would require making all orchestrator nodes `async def`, a large refactor. The codebase already uses `ThreadPoolExecutor` for the content-fetch phase; this is the same pattern.

### Rate limit adjustment

The existing 0.5 req/sec limit was conservative for serial use. With parallel queries, threads stagger naturally. Raise the default to 2.0 req/sec to allow the pool to actually run concurrently without each thread sleeping 2 seconds:

```
RETRIEVER_MCP_MAX_REQUESTS_PER_SECOND=2.0  # raised from 0.5
```

This is configurable — lower it if external API rate limits become an issue.

### Configuration

```
RETRIEVER_MCP_PARALLEL_QUERIES=6        # max concurrent queries (default: 6, max: 10)
RETRIEVER_MCP_MAX_REQUESTS_PER_SECOND=2.0  # per-connector rate limit
```

### Thread safety

The MCP connector's `RateLimiter` in `base.py` uses a sliding window with `time.time()`. It must be confirmed thread-safe (or given a `threading.Lock` if not). The search call itself spawns a subprocess per call — no shared state.

---

## Change 3: Parallel Evidence Packing

### Architecture

`evidence_packer.py` currently loops over sections sequentially. Replace the loop with a `ThreadPoolExecutor`:

```python
with ThreadPoolExecutor(max_workers=EVIDENCE_PACK_PARALLEL_SECTIONS) as pool:
    futures = {pool.submit(_pack_one_section, section, db_session_factory): section
               for section in outline.sections}
    for future in as_completed(futures):
        results[future_to_section[future]] = future.result()
```

Each `_pack_one_section` call:
1. Creates its own SQLAlchemy session (session is NOT shared across threads — SQLAlchemy sessions are not thread-safe).
2. Calls `EmbedWorkerPool.encode()` for the section query (dispatches to the process pool).
3. Runs the pgvector search (read-only).
4. Closes its session.

### Configuration

```
EVIDENCE_PACK_PARALLEL_SECTIONS=4   # sections processed in parallel (default: 4)
```

---

## Files to Modify

| File | Change |
|---|---|
| `backend/services/orchestrator/embeddings.py` | Add `EmbedWorkerPool` class with `encode()` and `shutdown()` |
| `backend/services/orchestrator/nodes/retriever.py` | Replace `_embed_texts_batched()` body with pool call; wrap MCP query loop in `ThreadPoolExecutor` |
| `backend/services/orchestrator/nodes/evidence_packer.py` | Replace `_embed_texts_batched()` body with pool call; wrap section loop in `ThreadPoolExecutor` |
| `backend/libs/connectors/scientific_papers_mcp.py` | Add thread-safety to `RateLimiter` if needed; make rate limit configurable |
| `backend/libs/connectors/base.py` | Add `threading.Lock` to `RateLimiter` sliding window if not present; expose `max_requests_per_second` as config |

---

## New Environment Variables

| Variable | Default | Description |
|---|---|---|
| `RETRIEVER_EMBED_WORKERS` | `min(2, cpu_count//2)` | Embedding worker processes |
| `RETRIEVER_MCP_PARALLEL_QUERIES` | `6` | Max concurrent MCP search queries |
| `RETRIEVER_MCP_MAX_REQUESTS_PER_SECOND` | `2.0` | Per-connector rate limit (was hardcoded 0.5) |
| `EVIDENCE_PACK_PARALLEL_SECTIONS` | `4` | Outline sections packed in parallel |

---

## Risks & Mitigations

| Risk | Mitigation |
|---|---|
| bge-m3 OOM with N workers | `RETRIEVER_EMBED_WORKERS` default is conservative (2); document RAM requirement (~1.5 GB/worker) |
| ProcessPoolExecutor pickling issues | Fallback to single-process path on `PicklingError`; log warning |
| External API rate limits hit with parallel MCP | `RETRIEVER_MCP_MAX_REQUESTS_PER_SECOND` is configurable; default 2.0 is still modest |
| SQLAlchemy session sharing bug | Each evidence-packing thread creates its own session via factory; never shares across threads |
| `RateLimiter` race condition | Audit `base.py` and add `threading.Lock` if the sliding window list is mutated without a lock |

---

## Verification

1. Run a full pipeline end-to-end and compare wall time before/after. Check `duration_ms` in `run_events` for each stage.
2. Confirm embedding output is identical to the single-process path (same vectors ± float precision).
3. Check logs for `embedded_now`, `cache_hits`, `cache_misses` — ratios should be unchanged.
4. Stress test with `RETRIEVER_EMBED_WORKERS=4` and monitor RSS memory of worker processes.
5. Confirm no "session is already closed" or "DetachedInstanceError" from parallel evidence packing threads.
