"""Shared configuration for knowledge embedding providers."""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Sequence


class EmbeddingProvider(ABC):
    """Minimal interface shared by document indexing and query search."""

    @property
    @abstractmethod
    def provider_name(self) -> str:
        """Stable provider identifier."""

    @property
    @abstractmethod
    def model_name(self) -> str:
        """Configured embedding model identifier."""

    @property
    @abstractmethod
    def dimensions(self) -> int:
        """Required vector dimensions."""

    @abstractmethod
    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        """Embed document chunks while preserving input order."""

    @abstractmethod
    def embed_query(self, text: str) -> list[float]:
        """Embed one search query through a distinct entrypoint."""


@dataclass(frozen=True, slots=True)
class EmbeddingProviderConfig:
    """Provider configuration with secret-safe representation."""

    provider_name: str
    model_name: str
    dimensions: int
    api_key: str = field(repr=False)
    base_url: str
    timeout_seconds: int
    max_retries: int
    batch_size: int
