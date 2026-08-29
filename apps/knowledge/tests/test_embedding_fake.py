"""Deterministic embedding fake reserved for later knowledge tests."""

import math

import pytest

from apps.knowledge.embeddings.base import EmbeddingProvider
from apps.knowledge.exceptions import KnowledgeDocumentError


def test_fake_provider_is_stable_and_implements_the_provider_interface():
    from apps.knowledge.tests.embedding_fakes import DeterministicEmbeddingProvider

    provider = DeterministicEmbeddingProvider()

    first = provider.embed_query("abc")
    second = provider.embed_documents(["abc"])[0]

    assert isinstance(provider, EmbeddingProvider)
    assert provider.provider_name == "fake"
    assert provider.model_name == "sha256-test"
    assert provider.dimensions == 1024
    assert first == second
    assert len(first) == 1024
    assert first[:4] == [0.73046875, 0.47265625, 0.08984375, 0.75]
    assert all(math.isfinite(value) for value in first)
    assert any(value != 0.0 for value in first)


def test_fake_provider_preserves_document_order_and_distinguishes_text():
    from apps.knowledge.tests.embedding_fakes import DeterministicEmbeddingProvider

    provider = DeterministicEmbeddingProvider()

    vectors = provider.embed_documents(["first", "second", "first"])

    assert vectors[0] != vectors[1]
    assert vectors[0] == vectors[2]


@pytest.mark.parametrize("invalid_input", [[], [""], ["   "]])
def test_fake_provider_rejects_empty_document_input(invalid_input):
    from apps.knowledge.tests.embedding_fakes import DeterministicEmbeddingProvider

    provider = DeterministicEmbeddingProvider()

    with pytest.raises(KnowledgeDocumentError) as exc_info:
        provider.embed_documents(invalid_input)

    assert exc_info.value.code == "embedding_empty_input"
