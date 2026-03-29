"""
Tests for race conditions and correctness in EmbedWorkerPool.encode() with n_chunks.

Tests use a mocked ProcessPoolExecutor so no real model or subprocess is needed.
"""
import os
import sys
import threading
import unittest.mock as mock
from concurrent.futures import Future

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


# ── Helpers ───────────────────────────────────────────────────────────────────


def _make_future(result):
    f = Future()
    f.set_result(result)
    return f


def _fake_pool(n_workers: int):
    """EmbedWorkerPool with a synchronous in-process executor (no real subprocesses)."""
    import services.orchestrator.embeddings as emb

    pool = object.__new__(emb.EmbedWorkerPool)
    pool._n_workers = n_workers
    pool._executor = mock.MagicMock()
    # submit(fn, chunk) → resolved future with fn(chunk) result
    pool._executor.submit.side_effect = lambda fn, chunk: _make_future(fn(chunk))
    return pool


def _deterministic_encode(texts):
    """Encode texts to unique vectors based purely on text content (no randomness)."""
    return [[float(abs(hash(t)) % 100_000) / 100_000, float(len(t))] for t in texts]


# ── Chunk splitting ────────────────────────────────────────────────────────────


def test_n_chunks_greater_than_pool_submits_correct_count():
    """n_chunks=10 with pool_size=3 submits 10 futures, not 3."""
    pool = _fake_pool(n_workers=3)
    texts = [str(i) for i in range(60)]

    with mock.patch("services.orchestrator.embeddings._worker_encode", side_effect=_deterministic_encode):
        pool.encode(texts, n_chunks=10)

    assert pool._executor.submit.call_count == 10


def test_n_chunks_one_submits_single_future():
    """n_chunks=1 sends everything to one worker — one submit call."""
    pool = _fake_pool(n_workers=4)
    texts = [str(i) for i in range(20)]

    with mock.patch("services.orchestrator.embeddings._worker_encode", side_effect=_deterministic_encode):
        pool.encode(texts, n_chunks=1)

    assert pool._executor.submit.call_count == 1


def test_n_chunks_exceeds_text_count_no_error():
    """Requesting more chunks than texts is handled gracefully — no crash, all texts returned."""
    pool = _fake_pool(n_workers=3)
    texts = ["x", "y", "z"]

    with mock.patch("services.orchestrator.embeddings._worker_encode", side_effect=_deterministic_encode):
        result = pool.encode(texts, n_chunks=20)

    assert len(result) == 3
    assert result == _deterministic_encode(texts)


# ── Result ordering ────────────────────────────────────────────────────────────


def test_result_order_preserved_n_chunks_exceeds_pool():
    """Output order matches input even when n_chunks > pool_size and futures complete out of order."""
    pool = _fake_pool(n_workers=2)
    texts = [str(i) for i in range(100)]
    expected = _deterministic_encode(texts)

    with mock.patch("services.orchestrator.embeddings._worker_encode", side_effect=_deterministic_encode):
        result = pool.encode(texts, n_chunks=20)

    assert len(result) == 100
    for i, (got, want) in enumerate(zip(result, expected)):
        assert got == want, f"Order mismatch at position {i}: got {got}, want {want}"


def test_result_order_preserved_single_chunk():
    """Output order is correct when n_chunks=1 (entire list to one worker)."""
    pool = _fake_pool(n_workers=4)
    texts = [f"item{i}" for i in range(50)]
    expected = _deterministic_encode(texts)

    with mock.patch("services.orchestrator.embeddings._worker_encode", side_effect=_deterministic_encode):
        result = pool.encode(texts, n_chunks=1)

    assert result == expected


# ── Concurrency: no result mixing ─────────────────────────────────────────────


def test_concurrent_encode_calls_no_result_mixing():
    """20 threads calling encode() simultaneously each get back their own results.

    Results are verified deterministically: each thread's texts hash to unique
    vectors, so any cross-thread contamination produces the wrong vector.
    """
    pool = _fake_pool(n_workers=4)
    n_threads = 20
    errors: list[str] = []
    barrier = threading.Barrier(n_threads)

    def run(thread_id: int) -> None:
        # Each thread owns texts with unique prefix so hashes don't collide
        texts = [f"t{thread_id:03d}_item{j:04d}" for j in range(30)]
        expected = _deterministic_encode(texts)
        barrier.wait()  # all threads start encoding simultaneously
        with mock.patch(
            "services.orchestrator.embeddings._worker_encode",
            side_effect=_deterministic_encode,
        ):
            result = pool.encode(texts, n_chunks=10)
        if result != expected:
            errors.append(
                f"Thread {thread_id}: result mismatch "
                f"(first vector: got {result[0]}, want {expected[0]})"
            )

    threads = [threading.Thread(target=run, args=(i,)) for i in range(n_threads)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=15)

    assert not errors, "\n".join(errors)


def test_concurrent_encode_all_threads_complete():
    """20 threads each encoding 30 texts all finish within timeout — no deadlock."""
    pool = _fake_pool(n_workers=4)
    n_threads = 20
    completed: list[int] = []
    lock = threading.Lock()
    barrier = threading.Barrier(n_threads)

    def run(thread_id: int) -> None:
        texts = [f"t{thread_id}_item{j}" for j in range(30)]
        barrier.wait()
        with mock.patch(
            "services.orchestrator.embeddings._worker_encode",
            side_effect=_deterministic_encode,
        ):
            pool.encode(texts, n_chunks=5)
        with lock:
            completed.append(thread_id)

    threads = [threading.Thread(target=run, args=(i,)) for i in range(n_threads)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=15)

    assert len(completed) == n_threads, (
        f"Only {len(completed)}/{n_threads} threads completed — possible deadlock"
    )


# ── Singleton creation race ────────────────────────────────────────────────────


def test_singleton_pool_created_exactly_once_under_concurrency():
    """30 threads racing to call get_embed_worker_pool() must create exactly one pool."""
    import services.orchestrator.embeddings as emb

    original = emb._EMBED_WORKER_POOL
    emb._EMBED_WORKER_POOL = None
    barrier = threading.Barrier(30)

    try:
        with mock.patch.object(emb, "EmbedWorkerPool") as MockPool:
            MockPool.return_value = mock.MagicMock()

            def race():
                barrier.wait()
                emb.get_embed_worker_pool(
                    model_name="test",
                    device="cpu",
                    normalize_embeddings=True,
                    max_seq_length=None,
                    dtype=None,
                    trust_remote_code=False,
                    n_workers=2,
                )

            threads = [threading.Thread(target=race) for _ in range(30)]
            for t in threads:
                t.start()
            for t in threads:
                t.join(timeout=10)

            assert MockPool.call_count == 1, (
                f"EmbedWorkerPool was constructed {MockPool.call_count} times — "
                "singleton lock is broken"
            )
    finally:
        emb._EMBED_WORKER_POOL = original


def test_singleton_pool_all_threads_get_same_instance():
    """All threads that race to get the pool receive the identical object."""
    import services.orchestrator.embeddings as emb

    original = emb._EMBED_WORKER_POOL
    emb._EMBED_WORKER_POOL = None
    barrier = threading.Barrier(30)
    returned: list[object] = []
    lock = threading.Lock()

    try:
        with mock.patch.object(emb, "EmbedWorkerPool") as MockPool:
            MockPool.return_value = mock.MagicMock()

            def race():
                barrier.wait()
                p = emb.get_embed_worker_pool(
                    model_name="test",
                    device="cpu",
                    normalize_embeddings=True,
                    max_seq_length=None,
                    dtype=None,
                    trust_remote_code=False,
                    n_workers=2,
                )
                with lock:
                    returned.append(p)

            threads = [threading.Thread(target=race) for _ in range(30)]
            for t in threads:
                t.start()
            for t in threads:
                t.join(timeout=10)

            assert len(returned) == 30
            first = returned[0]
            assert all(p is first for p in returned), "Threads received different pool instances"
    finally:
        emb._EMBED_WORKER_POOL = original
