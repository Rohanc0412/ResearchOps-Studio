import os
import sys
import unittest.mock as mock

import langfuse

if not hasattr(langfuse, "observe"):
    langfuse.observe = lambda *args, **kwargs: (lambda func: func)

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def test_embed_texts_batched_uses_pool_for_local_client():
    """_embed_texts_batched calls pool.encode() when client is SentenceTransformerEmbedClient."""
    import services.orchestrator.nodes.retriever as ret
    from embeddings import SentenceTransformerEmbedClient

    client = SentenceTransformerEmbedClient.__new__(SentenceTransformerEmbedClient)
    client.model_name = "test"
    client.device = "cpu"
    client.normalize_embeddings = True
    client.max_seq_length = None
    client.dtype = None
    client.trust_remote_code = False

    mock_pool = mock.MagicMock()
    mock_pool.encode.return_value = [[0.1, 0.2], [0.3, 0.4]]

    with mock.patch.dict(os.environ, {"EMBED_CHUNKS": "2"}):
        with mock.patch(
            "services.orchestrator.nodes.retriever.get_embed_worker_pool",
            return_value=mock_pool,
        ):
            result = ret._embed_texts_batched(client, ["hello", "world"], batch_size=32)

    mock_pool.encode.assert_called_once_with(["hello", "world"], n_chunks=mock.ANY)
    assert result == [[0.1, 0.2], [0.3, 0.4]]


def test_embed_texts_batched_falls_back_for_non_local_client():
    """_embed_texts_batched uses sequential batching for non-SentenceTransformer clients."""
    import services.orchestrator.nodes.retriever as ret

    class FakeHostedClient:
        model_name = "hosted-model"

        def embed_texts(self, texts):
            return [[0.5] * 3 for _ in texts]

    result = ret._embed_texts_batched(FakeHostedClient(), ["a", "b", "c"], batch_size=2)
    assert len(result) == 3
    assert all(v == [0.5, 0.5, 0.5] for v in result)


def test_embed_texts_batched_falls_back_when_max_workers_is_1():
    """_embed_texts_batched uses sequential batching when EMBED_WORKERS=1."""
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

    with mock.patch.dict(os.environ, {"EMBED_WORKERS": "1"}):
        with mock.patch("services.orchestrator.nodes.retriever.get_embed_worker_pool") as mock_get_pool:
            result = ret._embed_texts_batched(client, ["a", "b", "c"], batch_size=2)

    assert mock_get_pool.call_count <= 1
    assert len(call_log) == 2
    assert call_log[0] == ["a", "b"]
    assert call_log[1] == ["c"]
    assert len(result) == 3


def test_embed_texts_batched_avoids_shared_model_fast_path_on_cuda():
    """CUDA worker pools should not receive a preloaded model handle from the parent process."""
    import services.orchestrator.nodes.retriever as ret
    from embeddings import SentenceTransformerEmbedClient

    client = SentenceTransformerEmbedClient.__new__(SentenceTransformerEmbedClient)
    client.model_name = "test"
    client.device = "cuda:0"
    client.normalize_embeddings = True
    client.max_seq_length = None
    client.dtype = "bfloat16"
    client.trust_remote_code = False
    client._model = object()

    mock_pool = mock.MagicMock()
    mock_pool.encode.return_value = [[0.1, 0.2]]

    with mock.patch(
        "services.orchestrator.nodes.retriever.get_embed_worker_pool",
        return_value=mock_pool,
    ) as mock_get_pool:
        result = ret._embed_texts_batched(client, ["hello"], batch_size=32)

    assert result == [[0.1, 0.2]]
    assert mock_get_pool.call_args.kwargs["preloaded_model"] is None
