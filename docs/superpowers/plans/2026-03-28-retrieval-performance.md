# Retrieval Performance Optimization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Speed up the retrieval pipeline ~3–4× by parallelizing MCP queries, embedding computation, and evidence packing section searches.

**Architecture:** Three independent changes: (1) fix `RateLimiter` thread-safety and add `EmbedWorkerPool` in `embeddings.py` using `ProcessPoolExecutor` so N worker processes each pre-load the SentenceTransformer model; (2) wrap the MCP query loop in `retriever.py` with `ThreadPoolExecutor`; (3) parallelize per-section `search_snippets` calls in `evidence_packer.py` using `ThreadPoolExecutor`, each thread with its own SQLAlchemy session.

**Tech Stack:** Python `concurrent.futures` (`ProcessPoolExecutor`, `ThreadPoolExecutor`), `sentence_transformers`, SQLAlchemy `session.get_bind()` for per-thread sessions.

---

## File Map

| File | Change |
|---|---|
| `backend/libs/connectors/base.py` | Add `threading.Lock` to `RateLimiter`, fix race condition in `acquire()` |
| `backend/services/orchestrator/embeddings.py` | Add module-level worker functions + `EmbedWorkerPool` class |
| `backend/services/orchestrator/nodes/retriever.py` | Update `_embed_texts_batched` to use pool; parallelize MCP query loop; pass rate limit env var to connector |
| `backend/services/orchestrator/nodes/evidence_packer.py` | Update `_embed_texts_batched` to use pool; parallelize `search_snippets` per section |
| `backend/tests/test_rate_limiter_threadsafe.py` | New test file |
| `backend/tests/test_embed_worker_pool.py` | New test file |
| `backend/tests/test_retriever_mcp_parallel.py` | New test file |
| `backend/tests/test_evidence_packer_parallel.py` | New test file |

---

## Task 1: Fix RateLimiter Thread-Safety

**Files:**
- Modify: `backend/libs/connectors/base.py:114-151`
- Create: `backend/tests/test_rate_limiter_threadsafe.py`

The existing `RateLimiter.acquire()` mutates `self.requests` (a plain list) without a lock. Two threads can simultaneously see `len(self.requests) < self.max_requests` and both append, violating the limit. The recursive retry also risks hitting Python's recursion limit under high concurrency.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_rate_limiter_threadsafe.py
import threading
import time
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from libs.connectors.base import RateLimiter


def test_rate_limiter_does_not_exceed_limit_under_concurrency():
    """With max_requests=1 and window=0.5s, 8 threads must not all pass at once."""
    limiter = RateLimiter(max_requests=1, window_seconds=0.5)
    timestamps: list[float] = []
    lock = threading.Lock()

    def acquire_and_record():
        limiter.acquire()
        with lock:
            timestamps.append(time.monotonic())

    threads = [threading.Thread(target=acquire_and_record) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)

    assert len(timestamps) == 8, "All 8 threads must complete"
    # No two acquisitions within the same 0.5s window (allow 0.05s jitter)
    timestamps.sort()
    for i in range(1, len(timestamps)):
        gap = timestamps[i] - timestamps[i - 1]
        assert gap >= 0.4, f"Gap between acquisitions {i-1} and {i} was {gap:.3f}s (expected >= 0.4s)"
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd backend && python -m pytest tests/test_rate_limiter_threadsafe.py -v
```

Expected: FAIL — concurrent threads bypass the rate limit, gaps are near 0.

- [ ] **Step 3: Fix `RateLimiter` in `base.py`**

Replace lines 114–151 with:

```python
class RateLimiter:
    """
    Thread-safe rate limiter with sliding window.

    Ensures we don't exceed API rate limits.
    """

    def __init__(self, max_requests: int, window_seconds: float):
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self.requests: list[float] = []
        self._lock = threading.Lock()

    def acquire(self) -> None:
        """Block until a request slot is available."""
        while True:
            with self._lock:
                now = time.time()
                cutoff = now - self.window_seconds
                self.requests = [t for t in self.requests if t > cutoff]
                if len(self.requests) < self.max_requests:
                    self.requests.append(now)
                    return
                oldest = self.requests[0]
                sleep_time = self.window_seconds - (now - oldest) + 0.05
            # Sleep outside the lock so other threads can check concurrently
            if sleep_time > 0:
                time.sleep(sleep_time)
```

Also add `import threading` to `base.py` at the top (it already imports `time`; add `threading` next to it).

- [ ] **Step 4: Run test to verify it passes**

```bash
cd backend && python -m pytest tests/test_rate_limiter_threadsafe.py -v
```

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/libs/connectors/base.py backend/tests/test_rate_limiter_threadsafe.py
git commit -m "fix: make RateLimiter thread-safe with Lock, fix recursive acquire"
```

---

## Task 2: Add EmbedWorkerPool to embeddings.py

**Files:**
- Modify: `backend/services/orchestrator/embeddings.py`
- Create: `backend/tests/test_embed_worker_pool.py`

On CPU, a single SentenceTransformer process uses one core. A `ProcessPoolExecutor` with N workers each pre-loading the model allows N parallel encode calls, multiplying throughput. Workers are initialized via the `initializer` parameter (the model cannot be pickled and passed as an argument — it must be loaded inside each worker).

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_embed_worker_pool.py
import sys
import os
import unittest.mock as mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def test_embed_worker_pool_encode_splits_and_reassembles():
    """Pool encode splits texts across workers and returns results in original order."""
    import services.orchestrator.embeddings as emb

    # Patch _worker_encode to return a fake 3-dim vector per text
    fake_vectors = {text: [float(i), 0.0, 0.0] for i, text in enumerate(["a", "b", "c", "d", "e", "f"])}

    def fake_worker_encode(texts):
        return [fake_vectors[t] for t in texts]

    with mock.patch.object(emb, "_worker_encode", side_effect=fake_worker_encode):
        pool = emb.EmbedWorkerPool.__new__(emb.EmbedWorkerPool)
        pool._n_workers = 2
        pool._executor = None  # will not be used since we mock submit

        # Directly test the chunk-and-reassemble logic
        texts = list(fake_vectors.keys())  # ["a", "b", "c", "d", "e", "f"]

        # Simulate what pool.encode does: split into 2 chunks, encode each, merge
        chunk_size = (len(texts) + 1) // 2  # ceil(6/2) = 3
        chunks = [texts[i : i + chunk_size] for i in range(0, len(texts), chunk_size)]
        results = []
        for chunk in chunks:
            results.extend(fake_worker_encode(chunk))

        assert len(results) == 6
        assert results[0] == [0.0, 0.0, 0.0]  # "a" → index 0
        assert results[5] == [5.0, 0.0, 0.0]  # "f" → index 5
        # Order preserved
        for i, text in enumerate(texts):
            assert results[i] == fake_vectors[text], f"Order mismatch at index {i}"


def test_get_embed_worker_pool_returns_singleton():
    """get_embed_worker_pool returns the same object on repeated calls."""
    import services.orchestrator.embeddings as emb

    # Reset singleton for test isolation
    emb._EMBED_WORKER_POOL = None

    with mock.patch.object(emb, "EmbedWorkerPool") as MockPool:
        MockPool.return_value = mock.MagicMock()
        p1 = emb.get_embed_worker_pool(
            model_name="test-model", device="cpu", normalize_embeddings=True,
            max_seq_length=None, dtype=None, trust_remote_code=False, n_workers=2,
        )
        p2 = emb.get_embed_worker_pool(
            model_name="test-model", device="cpu", normalize_embeddings=True,
            max_seq_length=None, dtype=None, trust_remote_code=False, n_workers=2,
        )
        assert p1 is p2
        assert MockPool.call_count == 1  # only constructed once
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd backend && python -m pytest tests/test_embed_worker_pool.py -v
```

Expected: FAIL — `EmbedWorkerPool` and `get_embed_worker_pool` don't exist yet.

- [ ] **Step 3: Add pool code to `embeddings.py`**

Add the following to the **bottom** of `backend/services/orchestrator/embeddings.py` (after the existing `get_hf_client` function, before end of file):

```python
import atexit
import math
import os
import threading
from concurrent.futures import ProcessPoolExecutor

# ── Multiprocess embedding pool (local SentenceTransformer only) ──────────────

# Module-level state inside each worker process
_worker_model = None


def _worker_init(
    model_name: str,
    device: str,
    normalize_embeddings: bool,
    max_seq_length: int | None,
    dtype: str | None,
    trust_remote_code: bool,
) -> None:
    """Load the SentenceTransformer model inside the worker process."""
    global _worker_model
    from sentence_transformers import SentenceTransformer

    model_kwargs: dict = {}
    _dtype = None
    if dtype:
        try:
            import torch
            _dtype = getattr(torch, dtype)
            model_kwargs["dtype"] = _dtype
        except Exception:
            pass

    init_kwargs: dict = {"device": device}
    if model_kwargs:
        init_kwargs["model_kwargs"] = model_kwargs
    if trust_remote_code:
        init_kwargs["trust_remote_code"] = True
    try:
        _worker_model = SentenceTransformer(model_name, **init_kwargs)
    except TypeError:
        init_kwargs.pop("model_kwargs", None)
        init_kwargs.pop("trust_remote_code", None)
        _worker_model = SentenceTransformer(model_name, **init_kwargs)
        if _dtype is not None:
            _worker_model = _worker_model.to(dtype=_dtype)
    if max_seq_length:
        _worker_model.max_seq_length = max_seq_length


def _worker_encode(texts: list[str]) -> list[list[float]]:
    """Encode texts in a worker process using the pre-loaded model."""
    return _worker_model.encode(
        texts,
        normalize_embeddings=True,
        show_progress_bar=False,
        convert_to_numpy=True,
    ).tolist()


class EmbedWorkerPool:
    """
    Pool of worker processes each pre-loading a SentenceTransformer model.

    Splits text lists across workers and collects results in original order.
    Only useful for local (CPU/GPU) SentenceTransformer inference.
    """

    def __init__(
        self,
        model_name: str,
        device: str,
        normalize_embeddings: bool,
        max_seq_length: int | None,
        dtype: str | None,
        trust_remote_code: bool,
        n_workers: int,
    ) -> None:
        self._n_workers = n_workers
        self._executor = ProcessPoolExecutor(
            max_workers=n_workers,
            initializer=_worker_init,
            initargs=(model_name, device, normalize_embeddings, max_seq_length, dtype, trust_remote_code),
        )
        atexit.register(self.shutdown)

    def encode(self, texts: list[str]) -> list[list[float]]:
        """Distribute texts across workers and return embeddings in original order."""
        if not texts:
            return []
        if self._n_workers <= 1 or len(texts) <= 1:
            return _worker_encode(texts) if _worker_model is not None else self._encode_via_pool(texts)
        # Split into N equal chunks
        chunk_size = math.ceil(len(texts) / self._n_workers)
        chunks = [texts[i : i + chunk_size] for i in range(0, len(texts), chunk_size)]
        futures = [self._executor.submit(_worker_encode, chunk) for chunk in chunks]
        result: list[list[float]] = []
        for f in futures:
            result.extend(f.result())
        return result

    def _encode_via_pool(self, texts: list[str]) -> list[list[float]]:
        """Single-chunk encode via pool (used when worker model not in main process)."""
        return self._executor.submit(_worker_encode, texts).result()

    def shutdown(self) -> None:
        try:
            self._executor.shutdown(wait=False)
        except Exception:
            pass


# Singleton pool (one per process, created lazily)
_EMBED_WORKER_POOL: EmbedWorkerPool | None = None
_EMBED_WORKER_POOL_LOCK = threading.Lock()


def get_embed_worker_pool(
    *,
    model_name: str,
    device: str,
    normalize_embeddings: bool,
    max_seq_length: int | None,
    dtype: str | None,
    trust_remote_code: bool,
    n_workers: int,
) -> EmbedWorkerPool:
    """Return the singleton EmbedWorkerPool, creating it on first call."""
    global _EMBED_WORKER_POOL
    with _EMBED_WORKER_POOL_LOCK:
        if _EMBED_WORKER_POOL is None:
            _EMBED_WORKER_POOL = EmbedWorkerPool(
                model_name=model_name,
                device=device,
                normalize_embeddings=normalize_embeddings,
                max_seq_length=max_seq_length,
                dtype=dtype,
                trust_remote_code=trust_remote_code,
                n_workers=n_workers,
            )
        return _EMBED_WORKER_POOL
```

Also add to the top-level imports of `embeddings.py` (line 1-6 area):
```python
import atexit
import math
import os
import threading
from concurrent.futures import ProcessPoolExecutor
```

- [ ] **Step 4: Run test to verify it passes**

```bash
cd backend && python -m pytest tests/test_embed_worker_pool.py -v
```

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/services/orchestrator/embeddings.py backend/tests/test_embed_worker_pool.py
git commit -m "feat: add EmbedWorkerPool for parallel SentenceTransformer inference"
```

---

## Task 3: Use EmbedWorkerPool in retriever.py

**Files:**
- Modify: `backend/services/orchestrator/nodes/retriever.py:646-655`

Replace `_embed_texts_batched` to use the pool when the client is a local `SentenceTransformerEmbedClient` and `RETRIEVER_EMBED_WORKERS > 1`.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_retriever_embed_pool.py
import sys
import os
import unittest.mock as mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def test_embed_texts_batched_uses_pool_for_local_client():
    """_embed_texts_batched calls pool.encode() when client is SentenceTransformerEmbedClient."""
    import importlib
    import services.orchestrator.nodes.retriever as ret
    import services.orchestrator.embeddings as emb

    # Create a minimal SentenceTransformerEmbedClient (do NOT actually load a model)
    client = emb.SentenceTransformerEmbedClient.__new__(emb.SentenceTransformerEmbedClient)
    client.model_name = "test"
    client.device = "cpu"
    client.normalize_embeddings = True
    client.max_seq_length = None
    client.dtype = None
    client.trust_remote_code = False
    # Skip __post_init__ so no real model loads
    client._model = None

    mock_pool = mock.MagicMock()
    mock_pool.encode.return_value = [[0.1, 0.2], [0.3, 0.4]]

    with mock.patch.dict(os.environ, {"RETRIEVER_EMBED_WORKERS": "2"}):
        with mock.patch("services.orchestrator.nodes.retriever.get_embed_worker_pool", return_value=mock_pool):
            result = ret._embed_texts_batched(client, ["hello", "world"], batch_size=32)

    mock_pool.encode.assert_called_once_with(["hello", "world"])
    assert result == [[0.1, 0.2], [0.3, 0.4]]


def test_embed_texts_batched_falls_back_for_non_local_client():
    """_embed_texts_batched uses sequential batching for non-SentenceTransformer clients."""
    import services.orchestrator.nodes.retriever as ret

    class FakeOllamaClient:
        model_name = "ollama-model"
        def embed_texts(self, texts):
            return [[0.5] * 3 for _ in texts]

    result = ret._embed_texts_batched(FakeOllamaClient(), ["a", "b", "c"], batch_size=2)
    assert len(result) == 3
    assert all(v == [0.5, 0.5, 0.5] for v in result)
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd backend && python -m pytest tests/test_retriever_embed_pool.py -v
```

Expected: FAIL — `_embed_texts_batched` doesn't call the pool yet; `get_embed_worker_pool` import doesn't exist in retriever.

- [ ] **Step 3: Update `_embed_texts_batched` in `retriever.py`**

Find `_embed_texts_batched` at line 646. Replace the entire function:

```python
def _embed_texts_batched(
    client: EmbeddingClient, texts: list[str], *, batch_size: int
) -> list[list[float]]:
    if not texts:
        return []
    # Use multiprocess pool for local SentenceTransformer when workers > 1
    from embeddings import SentenceTransformerEmbedClient, get_embed_worker_pool

    if isinstance(client, SentenceTransformerEmbedClient):
        n_workers = _env_int(
            "RETRIEVER_EMBED_WORKERS",
            min(2, max(1, (os.cpu_count() or 2) // 2)),
            min_value=1,
        )
        if n_workers > 1:
            try:
                pool = get_embed_worker_pool(
                    model_name=client.model_name,
                    device=client.device,
                    normalize_embeddings=client.normalize_embeddings,
                    max_seq_length=client.max_seq_length,
                    dtype=client.dtype,
                    trust_remote_code=client.trust_remote_code,
                    n_workers=n_workers,
                )
                return pool.encode(texts)
            except Exception as exc:  # noqa: BLE001
                logger.warning("EmbedWorkerPool failed, falling back to sequential: %s", exc)
    # Sequential fallback (Ollama, HF, or pool unavailable)
    embeddings: list[list[float]] = []
    for start in range(0, len(texts), batch_size):
        batch = texts[start : start + batch_size]
        embeddings.extend(client.embed_texts(batch))
    return embeddings
```

Verify `os` is imported at the top of `retriever.py` (it should already be — search for `import os`).

- [ ] **Step 4: Run test to verify it passes**

```bash
cd backend && python -m pytest tests/test_retriever_embed_pool.py -v
```

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/services/orchestrator/nodes/retriever.py backend/tests/test_retriever_embed_pool.py
git commit -m "feat: use EmbedWorkerPool in retriever _embed_texts_batched"
```

---

## Task 4: Parallelize MCP Queries in retriever.py

**Files:**
- Modify: `backend/services/orchestrator/nodes/retriever.py:1292-1322`
- Create: `backend/tests/test_retriever_mcp_parallel.py`

The serial loop at line 1296 fires 6–10 queries one at a time. Replace with `ThreadPoolExecutor`. Also make the MCP rate limit and connector parallelism configurable via env vars.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_retriever_mcp_parallel.py
import sys
import os
import threading
import time
import unittest.mock as mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def test_mcp_queries_fire_in_parallel():
    """
    With 4 plan entries and RETRIEVER_MCP_PARALLEL_QUERIES=4,
    all 4 searches should overlap in time (not run serially).
    """
    call_times: list[float] = []
    call_lock = threading.Lock()

    def fake_search(query, max_results):
        with call_lock:
            call_times.append(time.monotonic())
        time.sleep(0.05)  # simulate network latency
        return []  # no sources for this test

    from dataclasses import dataclass

    @dataclass
    class FakePlan:
        query: str
        intent: str

    plans = [FakePlan(query=f"q{i}", intent="survey") for i in range(4)]
    mock_connector = mock.MagicMock()
    mock_connector.search.side_effect = lambda query, max_results: fake_search(query, max_results)
    mock_connector.sources = ["openalex"]

    # Import the helper we'll add
    import services.orchestrator.nodes.retriever as ret

    start = time.monotonic()
    with mock.patch.dict(os.environ, {"RETRIEVER_MCP_PARALLEL_QUERIES": "4"}):
        results = ret._parallel_mcp_search(plans, mock_connector, mcp_max_per_source=5)
    elapsed = time.monotonic() - start

    # 4 parallel calls each sleeping 0.05s should finish in ~0.05-0.15s, not 0.2s
    assert elapsed < 0.18, f"Queries did not run in parallel: elapsed={elapsed:.3f}s"
    assert mock_connector.search.call_count == 4


def test_mcp_search_results_combined_correctly():
    """All sources from all queries are returned."""
    from dataclasses import dataclass
    from datetime import datetime, timezone

    @dataclass
    class FakePlan:
        query: str
        intent: str

    from libs.connectors.base import RetrievedSource, CanonicalIdentifier, SourceType

    def make_source(title, connector="openalex"):
        return RetrievedSource(
            canonical_id=CanonicalIdentifier(openalex_id=title),
            title=title,
            authors=[],
            year=2024,
            source_type=SourceType.PAPER,
            abstract=None,
            full_text=None,
            url=None,
            pdf_url=None,
            connector=connector,
            retrieved_at=datetime.now(timezone.utc),
        )

    import services.orchestrator.nodes.retriever as ret

    plans = [FakePlan(query="q1", intent="survey"), FakePlan(query="q2", intent="methods")]
    mock_connector = mock.MagicMock()
    mock_connector.search.side_effect = [
        [make_source("paper-A"), make_source("paper-B")],
        [make_source("paper-C")],
    ]

    results = ret._parallel_mcp_search(plans, mock_connector, mcp_max_per_source=5)
    titles = {s.title for s in results}
    assert titles == {"paper-A", "paper-B", "paper-C"}
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd backend && python -m pytest tests/test_retriever_mcp_parallel.py -v
```

Expected: FAIL — `_parallel_mcp_search` function does not exist.

- [ ] **Step 3: Add `_parallel_mcp_search` helper and update the MCP search block**

First, add this helper function anywhere above the `retriever_node` function in `retriever.py`:

```python
def _parallel_mcp_search(
    query_plan: list,
    connector,
    *,
    mcp_max_per_source: int,
) -> list:
    """Search all query-plan entries in parallel using ThreadPoolExecutor."""
    import concurrent.futures

    parallel_queries = _env_int("RETRIEVER_MCP_PARALLEL_QUERIES", 6, min_value=1)

    def _search_one(plan) -> list:
        try:
            sources = connector.search(query=plan.query, max_results=mcp_max_per_source)
            for src in sources:
                meta = dict(src.extra_metadata or {})
                meta.update({"intent": plan.intent, "query": plan.query})
                src.extra_metadata = meta
            return sources
        except Exception as exc:
            logger.warning("MCP retrieval failed for query '%s': %s", plan.query, exc)
            return []

    all_sources: list = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=parallel_queries) as executor:
        futures = [executor.submit(_search_one, plan) for plan in query_plan]
        for future in concurrent.futures.as_completed(futures):
            all_sources.extend(future.result())
    return all_sources
```

Then replace the serial MCP loop in `retriever_node` (currently lines 1292–1305):

**Before:**
```python
mcp_connector = ScientificPapersMCPConnector()
mcp_max_per_source = _env_int("RETRIEVER_MCP_MAX_PER_SOURCE", 5, min_value=1)
retrieved_by_source: dict[str, list[RetrievedSource]] = {}

for plan in query_plan:
    try:
        sources = mcp_connector.search(query=plan.query, max_results=mcp_max_per_source)
        for src in sources:
            meta = dict(src.extra_metadata or {})
            meta.update({"intent": plan.intent, "query": plan.query})
            src.extra_metadata = meta
            retrieved_by_source.setdefault(src.connector, []).append(src)
    except Exception as exc:
        logger.warning("MCP retrieval failed for query '%s': %s", plan.query, exc)
```

**After:**
```python
mcp_rate = float(os.getenv("RETRIEVER_MCP_MAX_REQUESTS_PER_SECOND") or "2.0")
mcp_connector = ScientificPapersMCPConnector(max_requests_per_second=mcp_rate)
mcp_max_per_source = _env_int("RETRIEVER_MCP_MAX_PER_SOURCE", 5, min_value=1)
retrieved_by_source: dict[str, list[RetrievedSource]] = {}

all_sources = _parallel_mcp_search(query_plan, mcp_connector, mcp_max_per_source=mcp_max_per_source)
for src in all_sources:
    retrieved_by_source.setdefault(src.connector, []).append(src)
```

- [ ] **Step 4: Run test to verify it passes**

```bash
cd backend && python -m pytest tests/test_retriever_mcp_parallel.py -v
```

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/services/orchestrator/nodes/retriever.py backend/tests/test_retriever_mcp_parallel.py
git commit -m "feat: parallelize MCP queries with ThreadPoolExecutor, configurable rate limit"
```

---

## Task 5: Parallelize Evidence Packing Section Searches

**Files:**
- Modify: `backend/services/orchestrator/nodes/evidence_packer.py:131-190, 363-485`
- Create: `backend/tests/test_evidence_packer_parallel.py`

The embedding of all section queries is already batched together (lines 398–402 — this is good). The bottleneck is the sequential `search_snippets` pgvector call per section (line 407). Parallelize by running `search_snippets` in threads, each with its own SQLAlchemy session created from `session.get_bind()`. Post-processing and DB writes remain sequential in the main thread.

Also update `_embed_texts_batched` in `evidence_packer.py` identically to Task 3.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_evidence_packer_parallel.py
import sys
import os
import threading
import time
import unittest.mock as mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def test_section_searches_run_in_parallel():
    """_parallel_search_sections runs search_snippets for all sections concurrently."""
    call_times: list[float] = []
    call_lock = threading.Lock()

    def fake_search_snippets(**kwargs):
        with call_lock:
            call_times.append(time.monotonic())
        time.sleep(0.05)  # simulate pgvector query latency
        return []

    import services.orchestrator.nodes.evidence_packer as ep

    fake_engine = mock.MagicMock()
    # Session created from engine: context manager returns a mock session
    fake_session_instance = mock.MagicMock()
    fake_engine_session_ctx = mock.MagicMock()
    fake_engine_session_ctx.__enter__ = mock.Mock(return_value=fake_session_instance)
    fake_engine_session_ctx.__exit__ = mock.Mock(return_value=False)

    section_queries = [(f"s{i}", [0.1 * i] * 10) for i in range(4)]

    with mock.patch("services.orchestrator.nodes.evidence_packer.search_snippets", side_effect=fake_search_snippets):
        with mock.patch("services.orchestrator.nodes.evidence_packer.Session", return_value=fake_engine_session_ctx):
            with mock.patch.dict(os.environ, {"EVIDENCE_PACK_PARALLEL_SECTIONS": "4"}):
                start = time.monotonic()
                results = ep._parallel_search_sections(
                    section_queries=section_queries,
                    engine=fake_engine,
                    tenant_id="t1",
                    embedding_model="test-model",
                    source_ids=["s1"],
                    search_limit=60,
                    min_similarity=0.35,
                )
                elapsed = time.monotonic() - start

    # 4 parallel calls each sleeping 0.05s should finish in ~0.05–0.15s, not 0.2s
    assert elapsed < 0.18, f"Searches did not run in parallel: elapsed={elapsed:.3f}s"
    assert len(results) == 4
    assert all(section_id in results for section_id, _ in section_queries)
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd backend && python -m pytest tests/test_evidence_packer_parallel.py -v
```

Expected: FAIL — `_parallel_search_sections` does not exist; `Session` not imported in evidence_packer.

- [ ] **Step 3: Update `evidence_packer.py`**

**3a. Add imports** at the top of `evidence_packer.py` (after existing imports):

```python
import concurrent.futures
from sqlalchemy.orm import Session
```

**3b. Add `_parallel_search_sections` helper** (insert after `_embed_texts_batched`, around line 191):

```python
def _parallel_search_sections(
    section_queries: list[tuple[str, list[float]]],
    engine,
    *,
    tenant_id,
    embedding_model: str,
    source_ids: list,
    search_limit: int,
    min_similarity: float,
) -> dict[str, list[dict]]:
    """
    Run search_snippets for each section in parallel.

    Each thread creates its own SQLAlchemy session (sessions are not thread-safe).
    Returns a dict mapping section_id → raw search results.
    """
    parallel = _env_int("EVIDENCE_PACK_PARALLEL_SECTIONS", 4, min_value=1)

    def _search_one(section_id: str, query_embedding: list[float]) -> tuple[str, list[dict]]:
        with Session(engine) as s:
            results = list(search_snippets(
                session=s,
                tenant_id=tenant_id,
                query_embedding=query_embedding,
                embedding_model=embedding_model,
                limit=search_limit,
                min_similarity=min_similarity,
                source_ids=source_ids or None,
            ))
            if len(results) < 5:  # min_required
                relaxed = list(search_snippets(
                    session=s,
                    tenant_id=tenant_id,
                    query_embedding=query_embedding,
                    embedding_model=embedding_model,
                    limit=search_limit + 30,
                    min_similarity=max(0.0, min_similarity - 0.15),
                    source_ids=source_ids or None,
                ))
                results = _dedupe_results(results + relaxed)
        return section_id, results

    out: dict[str, list[dict]] = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=parallel) as executor:
        futures = {
            executor.submit(_search_one, section_id, query_embedding): section_id
            for section_id, query_embedding in section_queries
        }
        for future in concurrent.futures.as_completed(futures):
            section_id, results = future.result()
            out[section_id] = results
    return out
```

**3c. Update `_embed_texts_batched` in `evidence_packer.py`** (lines 181–190) to use the pool — identical to Task 3:

```python
def _embed_texts_batched(
    client: EmbeddingClient, texts: list[str], *, batch_size: int
) -> list[list[float]]:
    if not texts:
        return []
    from embeddings import SentenceTransformerEmbedClient, get_embed_worker_pool

    if isinstance(client, SentenceTransformerEmbedClient):
        n_workers = _env_int(
            "RETRIEVER_EMBED_WORKERS",
            min(2, max(1, (os.cpu_count() or 2) // 2)),
            min_value=1,
        )
        if n_workers > 1:
            try:
                pool = get_embed_worker_pool(
                    model_name=client.model_name,
                    device=client.device,
                    normalize_embeddings=client.normalize_embeddings,
                    max_seq_length=client.max_seq_length,
                    dtype=client.dtype,
                    trust_remote_code=client.trust_remote_code,
                    n_workers=n_workers,
                )
                return pool.encode(texts)
            except Exception as exc:  # noqa: BLE001
                import logging
                logging.getLogger(__name__).warning(
                    "EmbedWorkerPool failed, falling back to sequential: %s", exc
                )
    embeddings: list[list[float]] = []
    for start in range(0, len(texts), batch_size):
        batch = texts[start : start + batch_size]
        embeddings.extend(client.embed_texts(batch))
    return embeddings
```

Also add `import os` to evidence_packer.py top imports if not already present (it is — line 11).

**3d. Update `evidence_pack_node` to use `_parallel_search_sections`**

In `evidence_pack_node` (starting at line 364), replace the section loop and the inline relaxed-search logic. The new flow:

1. Keep lines 365–402 unchanged (setup + batch embedding of section queries).
2. After `query_vectors` is built (line 402), replace the `for (section, _), query_embedding in zip(...)` loop with:

```python
    # Build input for parallel section search
    engine = session.get_bind()
    search_inputs = [
        (section.section_id, query_embedding)
        for (section, _), query_embedding in zip(section_queries, query_vectors, strict=True)
    ]
    section_raw_results = _parallel_search_sections(
        search_inputs,
        engine,
        tenant_id=state.tenant_id,
        embedding_model=embedding_model,
        source_ids=source_ids,
        search_limit=search_limit,
        min_similarity=min_similarity,
    )

    # Sequential post-processing and persistence (DB writes use main session)
    for (section, _), query_embedding in zip(section_queries, query_vectors, strict=True):
        results = section_raw_results.get(section.section_id, [])
        results = sorted(results, key=lambda item: item["similarity"], reverse=True)
        selected = _select_diverse_snippets(
            results,
            max_count=max_snippets,
            per_source_cap=per_source_cap,
        )

        if len(selected) < min_snippets and len(results) > len(selected):
            selected = _select_diverse_snippets(
                results,
                max_count=min_snippets,
                per_source_cap=max(per_source_cap, min_snippets),
            )

        snippet_ids = [item["snippet_id"] for item in selected]
        _persist_section_evidence(
            session,
            tenant_id=state.tenant_id,
            run_id=state.run_id,
            section_id=section.section_id,
            snippet_ids=snippet_ids,
        )

        section_refs: list[EvidenceSnippetRef] = []
        for item in selected:
            snippet_id = str(item["snippet_id"])
            ref = evidence_refs.get(snippet_id)
            if ref is None:
                snippet_text = item["snippet_text"] or ""
                char_start = item["char_start"] if item["char_start"] is not None else 0
                char_end = item["char_end"] if item["char_end"] is not None else len(snippet_text)
                ref = EvidenceSnippetRef(
                    snippet_id=item["snippet_id"],
                    source_id=item["source_id"],
                    text=snippet_text,
                    char_start=char_start,
                    char_end=char_end,
                )
                evidence_refs[snippet_id] = ref
            section_refs.append(ref)
        section_snippet_refs[section.section_id] = section_refs

        emit_run_event(
            session=session,
            tenant_id=state.tenant_id,
            run_id=state.run_id,
            event_type="evidence_pack.created",
            stage="evidence_pack",
            data={
                "section_id": section.section_id,
                "snippet_count": len(snippet_ids),
            },
        )

    state.evidence_snippets = list(evidence_refs.values())
    state.section_evidence_snippets = section_snippet_refs
    return state
```

Also remove the variables `min_required`, `embed_batch_size` from the `evidence_pack_node` if they were only used in the old loop (they are at lines 383–387). The relaxed-search threshold (`min_required=5`) is now hardcoded in `_parallel_search_sections`'s `_search_one` inner function — make it consistent. Change the hardcoded `5` in `_search_one` to match `min_required`:

Actually, keep `min_required = _env_int("EVIDENCE_MIN_REQUIRED", 5, min_value=1)` in `evidence_pack_node` and pass it to `_parallel_search_sections`:

```python
def _parallel_search_sections(
    section_queries: list[tuple[str, list[float]]],
    engine,
    *,
    tenant_id,
    embedding_model: str,
    source_ids: list,
    search_limit: int,
    min_similarity: float,
    min_required: int,   # ← add this
) -> dict[str, list[dict]]:
    ...
    def _search_one(section_id, query_embedding):
        with Session(engine) as s:
            results = list(search_snippets(...))
            if len(results) < min_required:   # ← use parameter
                ...
```

And call it as:
```python
section_raw_results = _parallel_search_sections(
    search_inputs,
    engine,
    ...,
    min_required=min_required,
)
```

- [ ] **Step 4: Run test to verify it passes**

```bash
cd backend && python -m pytest tests/test_evidence_packer_parallel.py -v
```

Expected: PASS

- [ ] **Step 5: Run all new tests together**

```bash
cd backend && python -m pytest tests/test_rate_limiter_threadsafe.py tests/test_embed_worker_pool.py tests/test_retriever_embed_pool.py tests/test_retriever_mcp_parallel.py tests/test_evidence_packer_parallel.py -v
```

Expected: All PASS

- [ ] **Step 6: Commit**

```bash
git add backend/services/orchestrator/nodes/evidence_packer.py backend/tests/test_evidence_packer_parallel.py
git commit -m "feat: parallelize evidence packing section searches and use EmbedWorkerPool"
```

---

## Verification

**End-to-end timing check:**
1. Run a full research pipeline and note the `duration_ms` values in `run_events` for stages `retrieve`, `evidence_pack`.
2. Compare against a baseline run with `RETRIEVER_EMBED_WORKERS=1`, `RETRIEVER_MCP_PARALLEL_QUERIES=1`, `EVIDENCE_PACK_PARALLEL_SECTIONS=1`.
3. Expected: retrieve stage ~4–8× faster; evidence_pack ~3–5× faster.

**Correctness check:**
1. Compare `embedded_now`, `cache_hits`, `cache_misses` counts between parallel and sequential runs — they should be identical.
2. Confirm final report content is the same (same sources selected, same snippets).

**Memory check:**
1. With `RETRIEVER_EMBED_WORKERS=2` and bge-m3, expect ~3 GB RSS total (1 main + 2 workers × ~1.5 GB each).
2. If OOM, reduce to `RETRIEVER_EMBED_WORKERS=1` (pool is bypassed at n_workers=1).

**New environment variables summary:**

| Variable | Default | Effect |
|---|---|---|
| `RETRIEVER_EMBED_WORKERS` | `min(2, cpu_count//2)` | Worker processes for SentenceTransformer |
| `RETRIEVER_MCP_PARALLEL_QUERIES` | `6` | Concurrent MCP query threads |
| `RETRIEVER_MCP_MAX_REQUESTS_PER_SECOND` | `2.0` | MCP rate limit (was hardcoded 0.5) |
| `EVIDENCE_PACK_PARALLEL_SECTIONS` | `4` | Concurrent section search threads |
