"""Embedding provider interface for ingestion."""

from __future__ import annotations

from abc import abstractmethod
from typing import Protocol


class EmbeddingProvider(Protocol):
    """Protocol for embedding providers."""

    @property
    @abstractmethod
    def model_name(self) -> str:
        ...

    @property
    @abstractmethod
    def dimensions(self) -> int:
        ...

    @abstractmethod
    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        ...
