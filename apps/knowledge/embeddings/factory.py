"""Explicit factory for configured knowledge embedding providers."""

from django.conf import settings

from apps.knowledge.embeddings.base import EmbeddingProviderConfig
from apps.knowledge.embeddings.openai_compatible import (
    OpenAICompatibleEmbeddingProvider,
)
from apps.knowledge.exceptions import (
    KnowledgeDocumentError,
    KnowledgeDocumentErrorCode,
)


_VECTOR_STORAGE_DIMENSIONS = 1024


def get_embedding_provider() -> OpenAICompatibleEmbeddingProvider:
    """Build the configured provider without dynamic imports or fallback."""

    configured_provider = settings.EMBEDDING_PROVIDER
    if not isinstance(configured_provider, str) or not configured_provider.strip():
        raise KnowledgeDocumentError(
            KnowledgeDocumentErrorCode.EMBEDDING_NOT_CONFIGURED
        )
    if configured_provider.strip() != "openai_compatible":
        raise KnowledgeDocumentError(
            KnowledgeDocumentErrorCode.UNSUPPORTED_EMBEDDING_PROVIDER
        )
    config = _config_from_settings()
    return OpenAICompatibleEmbeddingProvider(config)


def _config_from_settings() -> EmbeddingProviderConfig:
    string_values = (
        settings.EMBEDDING_PROVIDER,
        settings.EMBEDDING_MODEL,
        settings.EMBEDDING_API_KEY,
        settings.EMBEDDING_BASE_URL,
    )
    if any(not isinstance(value, str) or not value.strip() for value in string_values):
        raise KnowledgeDocumentError(
            KnowledgeDocumentErrorCode.EMBEDDING_NOT_CONFIGURED
        )

    positive_integers = (
        settings.EMBEDDING_DIMENSIONS,
        settings.EMBEDDING_TIMEOUT_SECONDS,
        settings.EMBEDDING_BATCH_SIZE,
    )
    values_are_positive_integers = all(
        isinstance(value, int) and not isinstance(value, bool) and value > 0
        for value in positive_integers
    )
    dimensions_match_storage = (
        settings.EMBEDDING_DIMENSIONS == _VECTOR_STORAGE_DIMENSIONS
    )
    retries_are_valid = (
        isinstance(settings.EMBEDDING_MAX_RETRIES, int)
        and not isinstance(settings.EMBEDDING_MAX_RETRIES, bool)
        and settings.EMBEDDING_MAX_RETRIES >= 0
    )
    if (
        not values_are_positive_integers
        or not dimensions_match_storage
        or not retries_are_valid
    ):
        raise KnowledgeDocumentError(
            KnowledgeDocumentErrorCode.EMBEDDING_NOT_CONFIGURED
        )

    return EmbeddingProviderConfig(
        provider_name=settings.EMBEDDING_PROVIDER.strip(),
        model_name=settings.EMBEDDING_MODEL.strip(),
        dimensions=settings.EMBEDDING_DIMENSIONS,
        api_key=settings.EMBEDDING_API_KEY.strip(),
        base_url=settings.EMBEDDING_BASE_URL.strip(),
        timeout_seconds=settings.EMBEDDING_TIMEOUT_SECONDS,
        max_retries=settings.EMBEDDING_MAX_RETRIES,
        batch_size=settings.EMBEDDING_BATCH_SIZE,
    )
