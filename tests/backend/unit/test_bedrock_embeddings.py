from __future__ import annotations

import io
import json
import threading
import time

import pytest
from nodes import retriever as retriever_module


def test_resolve_embed_provider_stays_explicit(monkeypatch):
    monkeypatch.delenv("EMBED_PROVIDER", raising=False)
    monkeypatch.delenv("RETRIEVER_EMBED_PROVIDER", raising=False)
    monkeypatch.setenv("LLM_PROVIDER", "bedrock")

    from embeddings import resolve_embed_provider

    assert resolve_embed_provider("bedrock") == "local"


def test_bedrock_embed_client_preserves_order_with_bounded_parallelism():
    from embeddings import BedrockEmbedClient

    delays = {
        "doc-1": 0.05,
        "doc-2": 0.04,
        "doc-3": 0.01,
        "doc-4": 0.0,
        "doc-5": 0.02,
    }
    lock = threading.Lock()
    in_flight = 0
    max_in_flight = 0

    class FakeRuntimeClient:
        def invoke_model(self, *, body: str, **_: object) -> dict[str, object]:
            nonlocal in_flight, max_in_flight
            payload = json.loads(body)
            text = payload["inputText"]
            with lock:
                in_flight += 1
                max_in_flight = max(max_in_flight, in_flight)
            time.sleep(delays[text])
            with lock:
                in_flight -= 1
            return {
                "body": io.BytesIO(
                    json.dumps({"embedding": [float(text.split("-")[1])]}).encode(
                        "utf-8"
                    )
                )
            }

    client = BedrockEmbedClient(
        model_name="amazon.titan-embed-text-v2:0",
        region_name="us-east-1",
        batch_size=2,
        max_concurrency=2,
        timeout_seconds=5,
    )
    client._runtime_client = FakeRuntimeClient()

    vectors = client.embed_texts(["doc-1", "doc-2", "doc-3", "doc-4", "doc-5"])

    assert vectors == [[1.0], [2.0], [3.0], [4.0], [5.0]]
    assert max_in_flight <= 2


def test_bedrock_embed_client_raises_on_response_count_mismatch():
    from embeddings import BedrockEmbedClient

    client = BedrockEmbedClient(
        model_name="amazon.titan-embed-text-v2:0",
        region_name="us-east-1",
        batch_size=2,
        max_concurrency=2,
        timeout_seconds=5,
    )

    client._embed_batch = lambda texts: [[1.0] for _ in texts[:-1]]

    with pytest.raises(RuntimeError, match="count mismatch"):
        client.embed_texts(["alpha", "beta"])


def test_retriever_get_embed_client_selects_bedrock_when_explicit(monkeypatch):
    sentinel = object()
    monkeypatch.setenv("EMBED_PROVIDER", "bedrock")
    monkeypatch.setenv("BEDROCK_EMBED_MODEL", "amazon.titan-embed-text-v2:0")
    monkeypatch.setenv("BEDROCK_EMBED_REGION", "us-east-1")
    monkeypatch.setattr(retriever_module, "get_bedrock_client", lambda **_: sentinel)

    assert retriever_module._get_embed_client("hosted") is sentinel


def test_retriever_get_embed_client_requires_bedrock_region(monkeypatch):
    monkeypatch.setenv("EMBED_PROVIDER", "bedrock")
    monkeypatch.setenv("BEDROCK_EMBED_MODEL", "amazon.titan-embed-text-v2:0")
    monkeypatch.delenv("BEDROCK_EMBED_REGION", raising=False)
    monkeypatch.delenv("BEDROCK_REGION", raising=False)
    monkeypatch.delenv("AWS_REGION", raising=False)
    monkeypatch.delenv("AWS_DEFAULT_REGION", raising=False)

    with pytest.raises(retriever_module.EmbedError, match="BEDROCK_EMBED_REGION"):
        retriever_module._get_embed_client("hosted")
