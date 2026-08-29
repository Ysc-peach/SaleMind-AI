"""Embedding provider abstraction and factory contracts."""

import pytest
from django.test import override_settings

from apps.knowledge.exceptions import KnowledgeDocumentError


@override_settings(
    EMBEDDING_PROVIDER="openai_compatible",
    EMBEDDING_MODEL="BAAI/bge-m3",
    EMBEDDING_DIMENSIONS=1024,
    EMBEDDING_API_KEY="factory-test-secret",
    EMBEDDING_BASE_URL="https://embedding.example/v1",
    EMBEDDING_TIMEOUT_SECONDS=15,
    EMBEDDING_MAX_RETRIES=2,
    EMBEDDING_BATCH_SIZE=8,
)
def test_factory_creates_configured_openai_compatible_provider():
    from apps.knowledge.embeddings import get_embedding_provider
    from apps.knowledge.embeddings.openai_compatible import (
        OpenAICompatibleEmbeddingProvider,
    )

    provider = get_embedding_provider()

    assert isinstance(provider, OpenAICompatibleEmbeddingProvider)
    assert provider.provider_name == "openai_compatible"
    assert provider.model_name == "BAAI/bge-m3"
    assert provider.dimensions == 1024


@override_settings(
    EMBEDDING_PROVIDER="unknown",
    EMBEDDING_MODEL="BAAI/bge-m3",
    EMBEDDING_DIMENSIONS=1024,
    EMBEDDING_API_KEY="factory-test-secret",
    EMBEDDING_BASE_URL="https://embedding.example/v1",
)
def test_factory_rejects_unknown_provider_without_fallback():
    from apps.knowledge.embeddings import get_embedding_provider

    with pytest.raises(KnowledgeDocumentError) as exc_info:
        get_embedding_provider()

    assert exc_info.value.code == "unsupported_embedding_provider"


@override_settings(
    EMBEDDING_PROVIDER="unknown",
    EMBEDDING_MODEL="",
    EMBEDDING_API_KEY="",
    EMBEDDING_BASE_URL="",
)
def test_unknown_provider_error_takes_precedence_over_its_missing_configuration():
    from apps.knowledge.embeddings import get_embedding_provider

    with pytest.raises(KnowledgeDocumentError) as exc_info:
        get_embedding_provider()

    assert exc_info.value.code == "unsupported_embedding_provider"


@pytest.mark.parametrize(
    ("missing_setting", "missing_value"),
    [
        ("EMBEDDING_API_KEY", ""),
        ("EMBEDDING_BASE_URL", ""),
        ("EMBEDDING_MODEL", ""),
    ],
)
def test_factory_rejects_missing_required_configuration(
    settings,
    missing_setting,
    missing_value,
):
    from apps.knowledge.embeddings import get_embedding_provider

    settings.EMBEDDING_PROVIDER = "openai_compatible"
    settings.EMBEDDING_MODEL = "BAAI/bge-m3"
    settings.EMBEDDING_DIMENSIONS = 1024
    settings.EMBEDDING_API_KEY = "factory-test-secret"
    settings.EMBEDDING_BASE_URL = "https://embedding.example/v1"
    setattr(settings, missing_setting, missing_value)

    with pytest.raises(KnowledgeDocumentError) as exc_info:
        get_embedding_provider()

    assert exc_info.value.code == "embedding_not_configured"


@pytest.mark.parametrize(
    ("invalid_setting", "invalid_value"),
    [
        ("EMBEDDING_DIMENSIONS", 0),
        ("EMBEDDING_DIMENSIONS", 1023),
        ("EMBEDDING_DIMENSIONS", 1025),
        ("EMBEDDING_TIMEOUT_SECONDS", 0),
        ("EMBEDDING_MAX_RETRIES", -1),
        ("EMBEDDING_BATCH_SIZE", 0),
    ],
)
def test_factory_rejects_invalid_numeric_configuration(
    settings,
    invalid_setting,
    invalid_value,
):
    from apps.knowledge.embeddings import get_embedding_provider

    settings.EMBEDDING_PROVIDER = "openai_compatible"
    settings.EMBEDDING_MODEL = "BAAI/bge-m3"
    settings.EMBEDDING_DIMENSIONS = 1024
    settings.EMBEDDING_API_KEY = "factory-test-secret"
    settings.EMBEDDING_BASE_URL = "https://embedding.example/v1"
    settings.EMBEDDING_TIMEOUT_SECONDS = 30
    settings.EMBEDDING_MAX_RETRIES = 2
    settings.EMBEDDING_BATCH_SIZE = 32
    setattr(settings, invalid_setting, invalid_value)

    with pytest.raises(KnowledgeDocumentError) as exc_info:
        get_embedding_provider()

    assert exc_info.value.code == "embedding_not_configured"


def test_embedding_configuration_repr_redacts_api_key():
    from apps.knowledge.embeddings.base import EmbeddingProviderConfig

    config = EmbeddingProviderConfig(
        provider_name="openai_compatible",
        model_name="BAAI/bge-m3",
        dimensions=1024,
        api_key="never-print-this-secret",
        base_url="https://embedding.example/v1",
        timeout_seconds=30,
        max_retries=2,
        batch_size=32,
    )

    assert "never-print-this-secret" not in repr(config)


@override_settings(
    EMBEDDING_PROVIDER="openai_compatible",
    EMBEDDING_MODEL="BAAI/bge-m3",
    EMBEDDING_DIMENSIONS=1024,
    EMBEDDING_API_KEY="factory-test-secret",
    EMBEDDING_BASE_URL="https://embedding.example/v1",
)
@pytest.mark.django_db
def test_factory_performs_no_database_queries(django_assert_num_queries):
    from apps.knowledge.embeddings import get_embedding_provider

    with django_assert_num_queries(0):
        provider = get_embedding_provider()

    assert provider.provider_name == "openai_compatible"
