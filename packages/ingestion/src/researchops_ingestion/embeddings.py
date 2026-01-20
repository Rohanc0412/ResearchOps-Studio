"""
Embedding provider interface and stub implementation.

This module provides:
- Abstract embedding provider interface
- Stub provider for testing (returns random vectors)
- Support for future OpenAI, Cohere, local model providers
"""

from __future__ import annotations

import hashlib
import logging
import os
import random
from abc import ABC, abstractmethod
from functools import lru_cache
from typing import Protocol

logger = logging.getLogger(__name__)


class EmbeddingProvider(Protocol):
    """Protocol for embedding providers."""

    @property
    @abstractmethod
    def model_name(self) -> str:
        """Return the model identifier (e.g., 'text-embedding-3-small')."""
        ...

    @property
    @abstractmethod
    def dimensions(self) -> int:
        """Return the embedding vector dimensions."""
        ...

    @abstractmethod
    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        """
        Embed a batch of texts.

        Args:
            texts: List of text strings to embed

        Returns:
            List of embedding vectors (one per input text)

        Raises:
            RuntimeError: If embedding fails
        """
        ...


class StubEmbeddingProvider:
    """
    Stub embedding provider for testing.

    Generates deterministic "embeddings" by hashing text and using it as a seed.
    This is NOT suitable for production but useful for:
    - Unit tests
    - Integration tests
    - Development without API keys
    """

    def __init__(self, dimensions: int = 1536, model_name: str = "stub-embedder-1536"):
        """
        Initialize stub provider.

        Args:
            dimensions: Vector dimensions (default 1536 to match OpenAI)
            model_name: Model identifier for tracking
        """
        self._dimensions = dimensions
        self._model_name = model_name

    @property
    def model_name(self) -> str:
        return self._model_name

    @property
    def dimensions(self) -> int:
        return self._dimensions

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        """
        Generate deterministic stub embeddings.

        Uses SHA256 hash of text as random seed for reproducibility.

        Args:
            texts: List of texts to embed

        Returns:
            List of "embedding" vectors (random but deterministic)
        """
        embeddings = []
        logger.info(
            "embedding_batch",
            extra={"provider": "stub", "model": self._model_name, "count": len(texts)},
        )
        for text in texts:
            # Use hash of text as seed for deterministic randomness
            seed = int(hashlib.sha256(text.encode("utf-8")).hexdigest()[:16], 16)
            rng = random.Random(seed)

            # Generate random vector in [-1, 1]
            vector = [rng.uniform(-1.0, 1.0) for _ in range(self._dimensions)]

            # Normalize to unit length (cosine similarity works better)
            magnitude = sum(x * x for x in vector) ** 0.5
            if magnitude > 0:
                vector = [x / magnitude for x in vector]

            embeddings.append(vector)

        return embeddings


# Local model provider for production-quality embeddings
class SentenceTransformerEmbeddingProvider:
    """
    Embedding provider using sentence-transformers.

    Defaults to BAAI/bge-large-en-v1.5 for strong English retrieval performance.
    """

    def __init__(
        self,
        model_name: str = "BAAI/bge-large-en-v1.5",
        device: str | None = None,
        normalize_embeddings: bool = True,
    ):
        self._model_name = model_name
        self._normalize = normalize_embeddings

        try:
            from sentence_transformers import SentenceTransformer
        except Exception as exc:
            raise RuntimeError(
                "sentence-transformers is required for local embeddings. Install it via pip."
            ) from exc

        resolved_device = device or _default_device()
        logger.info(
            "embedding_model_load",
            extra={
                "provider": "sentence-transformers",
                "model": model_name,
                "device": resolved_device,
            },
        )
        self._model = SentenceTransformer(model_name, device=resolved_device)
        self._dimensions = self._model.get_sentence_embedding_dimension()

    @property
    def model_name(self) -> str:
        return self._model_name

    @property
    def dimensions(self) -> int:
        return self._dimensions

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        logger.info(
            "embedding_batch",
            extra={
                "provider": "sentence-transformers",
                "model": self._model_name,
                "count": len(texts),
            },
        )
        embeddings = self._model.encode(
            texts,
            normalize_embeddings=self._normalize,
            show_progress_bar=False,
            convert_to_numpy=True,
        )
        return embeddings.tolist()


def _default_device() -> str:
    forced = os.getenv("EMBEDDING_DEVICE")
    if forced:
        return forced
    try:
        import torch

        return "cuda" if torch.cuda.is_available() else "cpu"
    except Exception:
        return "cpu"


@lru_cache(maxsize=1)
def get_embedding_provider() -> EmbeddingProvider:
    provider = os.getenv("EMBEDDING_PROVIDER", "sentence-transformers").lower()
    if provider in {"stub", "fake"}:
        logger.info("embedding_provider_selected", extra={"provider": provider})
        return StubEmbeddingProvider()
    if provider in {"sentence-transformers", "bge", "local"}:
        model_name = os.getenv("EMBEDDING_MODEL", "BAAI/bge-large-en-v1.5")
        normalize_env = os.getenv("EMBEDDING_NORMALIZE", "true").lower()
        normalize = normalize_env not in {"0", "false", "no"}
        device = os.getenv("EMBEDDING_DEVICE")
        logger.info(
            "embedding_provider_selected",
            extra={
                "provider": provider,
                "model": model_name,
                "normalize": normalize,
                "device": device or "auto",
            },
        )
        return SentenceTransformerEmbeddingProvider(
            model_name=model_name,
            device=device,
            normalize_embeddings=normalize,
        )
    raise ValueError(f"Unknown EMBEDDING_PROVIDER: {provider}")


# Future providers can be added here:
#
# class OpenAIEmbeddingProvider:
#     def __init__(self, api_key: str, model: str = "text-embedding-3-small"):
#         self.client = OpenAI(api_key=api_key)
#         self._model = model
#
#     @property
#     def model_name(self) -> str:
#         return self._model
#
#     @property
#     def dimensions(self) -> int:
#         return 1536 if "3-small" in self._model else 3072
#
#     def embed_texts(self, texts: list[str]) -> list[list[float]]:
#         response = self.client.embeddings.create(input=texts, model=self._model)
#         return [item.embedding for item in response.data]
