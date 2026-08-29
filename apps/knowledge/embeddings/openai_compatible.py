"""OpenAI-compatible embedding provider."""

from math import isfinite
from typing import NoReturn, Sequence

from openai import OpenAI, OpenAIError

from apps.knowledge.embeddings.base import (
    EmbeddingProvider,
    EmbeddingProviderConfig,
)
from apps.knowledge.exceptions import (
    KnowledgeDocumentError,
    KnowledgeDocumentErrorCode,
)


class OpenAICompatibleEmbeddingProvider(EmbeddingProvider):
    """Embedding provider backed by an OpenAI-compatible HTTP endpoint."""

    def __init__(self, config: EmbeddingProviderConfig):
        self._config = config
        self._client = OpenAI(
            api_key=config.api_key,
            base_url=config.base_url,
            timeout=config.timeout_seconds,
            max_retries=config.max_retries,
        )

    @property
    def provider_name(self) -> str:
        return self._config.provider_name

    @property
    def model_name(self) -> str:
        return self._config.model_name

    @property
    def dimensions(self) -> int:
        return self._config.dimensions

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        validated_texts = self._validate_documents(texts)
        vectors: list[list[float]] = []
        for start in range(0, len(validated_texts), self._config.batch_size):
            batch = validated_texts[start : start + self._config.batch_size]
            vectors.extend(self._embed_batch(batch))
        return vectors

    def embed_query(self, text: str) -> list[float]:
        if not isinstance(text, str) or not text.strip():
            self._raise_empty_input()
        return self._embed_batch([self._prepare_query_text(text)])[0]

    def _embed_batch(self, texts: list[str]) -> list[list[float]]:
        try:
            response = self._client.embeddings.create(
                input=texts,
                model=self.model_name,
                encoding_format="float",
            )
        except OpenAIError:
            raise KnowledgeDocumentError(
                KnowledgeDocumentErrorCode.EMBEDDING_PROVIDER_ERROR
            ) from None
        return self._validate_response(response, expected_count=len(texts))

    def _validate_response(
        self,
        response,
        *,
        expected_count: int,
    ) -> list[list[float]]:
        try:
            items = list(response.data)
            indices = [item.index for item in items]
        except (AttributeError, TypeError):
            self._raise_invalid_response()

        if len(items) != expected_count:
            self._raise_invalid_response()
        invalid_index_exists = any(
            not isinstance(index, int) or isinstance(index, bool)
            for index in indices
        )
        if invalid_index_exists:
            self._raise_invalid_response()
        if sorted(indices) != list(range(expected_count)):
            self._raise_invalid_response()

        ordered_items = sorted(items, key=lambda item: item.index)
        vectors: list[list[float]] = []
        for item in ordered_items:
            try:
                embedding = item.embedding
            except AttributeError:
                self._raise_invalid_response()
            vectors.append(self._validate_vector(embedding))
        return vectors

    def _validate_vector(self, embedding) -> list[float]:
        try:
            vector = list(embedding)
        except TypeError:
            self._raise_invalid_response()

        if not vector:
            self._raise_invalid_response()
        if len(vector) != self.dimensions:
            raise KnowledgeDocumentError(
                KnowledgeDocumentErrorCode.EMBEDDING_DIMENSION_MISMATCH
            )

        values_are_finite_numbers = all(
            isinstance(value, (int, float))
            and not isinstance(value, bool)
            and isfinite(value)
            for value in vector
        )
        if not values_are_finite_numbers:
            self._raise_invalid_response()

        normalized_vector = [float(value) for value in vector]
        if all(value == 0.0 for value in normalized_vector):
            self._raise_invalid_response()
        return normalized_vector

    def _validate_documents(self, texts: Sequence[str]) -> list[str]:
        if isinstance(texts, str) or not texts:
            self._raise_empty_input()
        if any(not isinstance(text, str) or not text.strip() for text in texts):
            self._raise_empty_input()
        return [self._prepare_document_text(text) for text in texts]

    def _prepare_document_text(self, text: str) -> str:
        """Hook for provider-specific document instructions; currently identity."""

        return text

    def _prepare_query_text(self, text: str) -> str:
        """Hook for provider-specific query instructions; currently trims only."""

        return text.strip()

    def _raise_empty_input(self) -> NoReturn:
        raise KnowledgeDocumentError(
            KnowledgeDocumentErrorCode.EMBEDDING_EMPTY_INPUT
        )

    def _raise_invalid_response(self) -> NoReturn:
        raise KnowledgeDocumentError(
            KnowledgeDocumentErrorCode.EMBEDDING_INVALID_RESPONSE
        )
