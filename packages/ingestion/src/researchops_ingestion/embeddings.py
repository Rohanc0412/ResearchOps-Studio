"""
Embedding provider interface and stub implementation.

This module provides:
- Abstract embedding provider interface
- Stub provider for testing (returns random vectors)
- Support for future OpenAI, Cohere, local model providers
"""

from __future__ import annotations

import hashlib
import random
from abc import ABC, abstractmethod
from typing import Protocol


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
