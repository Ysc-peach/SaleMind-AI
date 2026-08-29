"""Deterministic embedding test doubles; never used as production providers."""

from hashlib import sha256
from typing import NoReturn, Sequence

from apps.knowledge.embeddings.base import EmbeddingProvider
from apps.knowledge.exceptions import (
    KnowledgeDocumentError,
    KnowledgeDocumentErrorCode,
)


class DeterministicEmbeddingProvider(EmbeddingProvider):
    """Cross-process stable vectors for indexing and search tests."""

    provider_name = "fake"
    model_name = "sha256-test"
    dimensions = 1024

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        if isinstance(texts, str) or not texts:
            self._raise_empty_input()
        if any(not isinstance(text, str) or not text.strip() for text in texts):
            self._raise_empty_input()
        return [self._embed(text) for text in texts]

    def embed_query(self, text: str) -> list[float]:
        if not isinstance(text, str) or not text.strip():
            self._raise_empty_input()
        return self._embed(text.strip())

    def _embed(self, text: str) -> list[float]:
        digest = sha256(text.encode("utf-8")).digest()
        return [
            (digest[index % len(digest)] + 1) / 256.0
            for index in range(self.dimensions)
        ]

    def _raise_empty_input(self) -> NoReturn:
        raise KnowledgeDocumentError(KnowledgeDocumentErrorCode.EMBEDDING_EMPTY_INPUT)
