import sys
import os
import unittest.mock as mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def test_embed_texts_batched_uses_pool_for_local_client():
    """_embed_texts_batched calls pool.encode() when client is SentenceTransformerEmbedClient."""
    import services.orchestrator.nodes.retriever as ret
    import services.orchestrator.embeddings as emb

    # Create a minimal SentenceTransformerEmbedClient without loading a real model
    client = emb.SentenceTransformerEmbedClient.__new__(emb.SentenceTransformerEmbedClient)
    client.model_name = "test"
    client.device = "cpu"
    client.normalize_embeddings = True
    client.max_seq_length = None
    client.dtype = None
    client.trust_remote_code = False
    # Don't call __post_init__ so no real model loads

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


def test_embed_texts_batched_falls_back_when_workers_is_1():
    """_embed_texts_batched uses sequential batching when RETRIEVER_EMBED_WORKERS=1."""
    import services.orchestrator.nodes.retriever as ret
    import services.orchestrator.embeddings as emb

    client = emb.SentenceTransformerEmbedClient.__new__(emb.SentenceTransformerEmbedClient)
    client.model_name = "test"
    client.device = "cpu"
    client.normalize_embeddings = True
    client.max_seq_length = None
    client.dtype = None
    client.trust_remote_code = False

    call_log = []
    original_embed = lambda texts: (call_log.append(texts), [[0.1] * 3 for _ in texts])[1]
    client.embed_texts = original_embed

    with mock.patch.dict(os.environ, {"RETRIEVER_EMBED_WORKERS": "1"}):
        result = ret._embed_texts_batched(client, ["a", "b", "c"], batch_size=2)

    # Should have been called in 2 batches: ["a","b"] and ["c"]
    assert len(call_log) == 2
    assert call_log[0] == ["a", "b"]
    assert call_log[1] == ["c"]
    assert len(result) == 3
