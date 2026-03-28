import sys
import os
import unittest.mock as mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def test_embed_texts_batched_uses_pool_for_local_client():
    """_embed_texts_batched calls pool.encode() when client is SentenceTransformerEmbedClient."""
    import sys
    # Ensure the embeddings module resolves the same way as in retriever.py
    import services.orchestrator.nodes.retriever as ret

    # Import SentenceTransformerEmbedClient using same resolution as retriever.py
    from embeddings import SentenceTransformerEmbedClient

    # Create a minimal client without loading a real model
    client = SentenceTransformerEmbedClient.__new__(SentenceTransformerEmbedClient)
    client.model_name = "test"
    client.device = "cpu"
    client.normalize_embeddings = True
    client.max_seq_length = None
    client.dtype = None
    client.trust_remote_code = False

    mock_pool = mock.MagicMock()
    mock_pool.encode.return_value = [[0.1, 0.2], [0.3, 0.4]]

    with mock.patch.dict(os.environ, {"RETRIEVER_EMBED_CHUNKS": "2"}):
        with mock.patch("services.orchestrator.nodes.retriever.get_embed_worker_pool", return_value=mock_pool):
            result = ret._embed_texts_batched(client, ["hello", "world"], batch_size=32)

    mock_pool.encode.assert_called_once_with(["hello", "world"], n_chunks=mock.ANY)
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


def test_embed_texts_batched_falls_back_when_max_workers_is_1():
    """_embed_texts_batched uses sequential batching when RETRIEVER_EMBED_MODELS=1.

    RETRIEVER_EMBED_CHUNKS controls chunk count; RETRIEVER_EMBED_MODELS controls
    pool size (model instances). Setting MAX_WORKERS=1 means pool_size=1 → sequential.
    """
    import services.orchestrator.nodes.retriever as ret
    from embeddings import SentenceTransformerEmbedClient

    client = SentenceTransformerEmbedClient.__new__(SentenceTransformerEmbedClient)
    client.model_name = "test"
    client.device = "cpu"
    client.normalize_embeddings = True
    client.max_seq_length = None
    client.dtype = None
    client.trust_remote_code = False

    call_log = []
    client.embed_texts = lambda texts: (call_log.append(texts), [[0.1] * 3 for _ in texts])[1]

    with mock.patch.dict(os.environ, {"RETRIEVER_EMBED_MODELS": "1"}):
        with mock.patch("services.orchestrator.nodes.retriever.get_embed_worker_pool") as mock_get_pool:
            result = ret._embed_texts_batched(client, ["a", "b", "c"], batch_size=2)

    # Pool should never be created when pool_size (MAX_WORKERS) is 1
    mock_get_pool.assert_not_called()
    # Sequential batching: ["a","b"] then ["c"]
    assert len(call_log) == 2
    assert call_log[0] == ["a", "b"]
    assert call_log[1] == ["c"]
    assert len(result) == 3
