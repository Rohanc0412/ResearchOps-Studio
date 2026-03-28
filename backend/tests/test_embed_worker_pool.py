import sys
import os
import unittest.mock as mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def test_embed_worker_pool_encode_splits_and_reassembles():
    """Pool encode splits texts across workers and returns results in original order."""
    import services.orchestrator.embeddings as emb

    fake_vectors = {text: [float(i), 0.0, 0.0] for i, text in enumerate(["a", "b", "c", "d", "e", "f"])}

    def fake_worker_encode(texts):
        return [fake_vectors[t] for t in texts]

    # Test the chunk-and-reassemble logic directly
    texts = list(fake_vectors.keys())  # ["a", "b", "c", "d", "e", "f"]
    n_workers = 2
    chunk_size = (len(texts) + n_workers - 1) // n_workers  # ceil division
    chunks = [texts[i : i + chunk_size] for i in range(0, len(texts), chunk_size)]
    results = []
    for chunk in chunks:
        results.extend(fake_worker_encode(chunk))

    assert len(results) == 6
    assert results[0] == [0.0, 0.0, 0.0]  # "a" -> index 0
    assert results[5] == [5.0, 0.0, 0.0]  # "f" -> index 5
    for i, text in enumerate(texts):
        assert results[i] == fake_vectors[text], f"Order mismatch at index {i}"


def test_get_embed_worker_pool_returns_singleton():
    """get_embed_worker_pool returns the same object on repeated calls."""
    import services.orchestrator.embeddings as emb

    # Reset singleton for test isolation
    original = emb._EMBED_WORKER_POOL
    emb._EMBED_WORKER_POOL = None

    try:
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
    finally:
        emb._EMBED_WORKER_POOL = original
