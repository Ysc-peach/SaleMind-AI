"""OpenAI-compatible embedding provider behavior."""

from dataclasses import dataclass
from types import SimpleNamespace

import pytest

from apps.knowledge.embeddings.base import EmbeddingProviderConfig
from apps.knowledge.exceptions import KnowledgeDocumentError


@dataclass(frozen=True)
class _EmbeddingItem:
    index: int
    embedding: list[float]


class _EmbeddingEndpoint:
    def __init__(self, response_builder):
        self._response_builder = response_builder
        self.calls: list[dict] = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(data=self._response_builder(kwargs["input"]))


def _vector(value: float) -> list[float]:
    return [value] * 1024


def _build_provider(monkeypatch, response_builder, *, batch_size=2):
    from apps.knowledge.embeddings import openai_compatible

    endpoint = _EmbeddingEndpoint(response_builder)
    client = SimpleNamespace(embeddings=endpoint)
    client_arguments: dict = {}

    def client_factory(**kwargs):
        client_arguments.update(kwargs)
        return client

    monkeypatch.setattr(openai_compatible, "OpenAI", client_factory)
    config = EmbeddingProviderConfig(
        provider_name="openai_compatible",
        model_name="BAAI/bge-m3",
        dimensions=1024,
        api_key="provider-test-secret",
        base_url="https://embedding.example/v1",
        timeout_seconds=17,
        max_retries=2,
        batch_size=batch_size,
    )
    provider = openai_compatible.OpenAICompatibleEmbeddingProvider(config)
    return provider, endpoint, client_arguments


def test_provider_implements_the_document_and_query_interface(monkeypatch):
    from apps.knowledge.embeddings.base import EmbeddingProvider

    provider, _, _ = _build_provider(
        monkeypatch,
        lambda texts: [_EmbeddingItem(index=0, embedding=_vector(1.0))],
    )

    assert isinstance(provider, EmbeddingProvider)
    assert callable(provider.embed_documents)
    assert callable(provider.embed_query)


def test_provider_constructs_sdk_client_only_from_configuration(monkeypatch):
    _, _, client_arguments = _build_provider(monkeypatch, lambda texts: [])

    assert client_arguments == {
        "api_key": "provider-test-secret",
        "base_url": "https://embedding.example/v1",
        "timeout": 17,
        "max_retries": 2,
    }


def test_query_uses_its_own_entrypoint_and_returns_one_vector(monkeypatch):
    provider, endpoint, _ = _build_provider(
        monkeypatch,
        lambda texts: [_EmbeddingItem(index=0, embedding=_vector(1.5))],
    )

    vector = provider.embed_query("  customer knowledge query  ")

    assert vector == _vector(1.5)
    assert endpoint.calls == [
        {
            "input": ["customer knowledge query"],
            "model": "BAAI/bge-m3",
            "encoding_format": "float",
        }
    ]


def test_documents_restore_provider_response_to_input_order(monkeypatch):
    def reversed_response(texts):
        return [
            _EmbeddingItem(index=1, embedding=_vector(2.0)),
            _EmbeddingItem(index=0, embedding=_vector(1.0)),
        ]

    provider, endpoint, _ = _build_provider(monkeypatch, reversed_response)

    vectors = provider.embed_documents(["first", "second"])

    assert vectors == [_vector(1.0), _vector(2.0)]
    assert endpoint.calls == [
        {
            "input": ["first", "second"],
            "model": "BAAI/bge-m3",
            "encoding_format": "float",
        }
    ]


def test_documents_are_batched_and_keep_global_input_order(monkeypatch):
    vector_values = {
        "document-0": 1.0,
        "document-1": 2.0,
        "document-2": 3.0,
        "document-3": 4.0,
        "document-4": 5.0,
    }

    def reversed_batch_response(texts):
        return [
            _EmbeddingItem(index=index, embedding=_vector(vector_values[text]))
            for index, text in reversed(list(enumerate(texts)))
        ]

    provider, endpoint, _ = _build_provider(
        monkeypatch,
        reversed_batch_response,
        batch_size=2,
    )
    documents = [f"document-{index}" for index in range(5)]

    vectors = provider.embed_documents(documents)

    assert vectors == [_vector(float(index)) for index in range(1, 6)]
    assert [call["input"] for call in endpoint.calls] == [
        ["document-0", "document-1"],
        ["document-2", "document-3"],
        ["document-4"],
    ]


@pytest.mark.django_db
def test_embedding_performs_no_database_queries(monkeypatch, django_assert_num_queries):
    provider, _, _ = _build_provider(
        monkeypatch,
        lambda texts: [
            _EmbeddingItem(index=index, embedding=_vector(float(index + 1)))
            for index, _ in enumerate(texts)
        ],
    )

    with django_assert_num_queries(0):
        vectors = provider.embed_documents(["first", "second"])

    assert vectors == [_vector(1.0), _vector(2.0)]


@pytest.mark.parametrize("documents", [[], [""], ["valid", "   \n"]])
def test_documents_reject_empty_input_before_request(monkeypatch, documents):
    provider, endpoint, _ = _build_provider(monkeypatch, lambda texts: [])

    with pytest.raises(KnowledgeDocumentError) as exc_info:
        provider.embed_documents(documents)

    assert exc_info.value.code == "embedding_empty_input"
    assert endpoint.calls == []


@pytest.mark.parametrize("query", ["", "   \n"])
def test_query_rejects_empty_input_before_request(monkeypatch, query):
    provider, endpoint, _ = _build_provider(monkeypatch, lambda texts: [])

    with pytest.raises(KnowledgeDocumentError) as exc_info:
        provider.embed_query(query)

    assert exc_info.value.code == "embedding_empty_input"
    assert endpoint.calls == []


@pytest.mark.parametrize(
    "items",
    [
        [],
        [
            _EmbeddingItem(index=0, embedding=_vector(1.0)),
            _EmbeddingItem(index=1, embedding=_vector(2.0)),
        ],
    ],
    ids=["fewer-than-input", "more-than-input"],
)
def test_response_count_must_equal_input_count(monkeypatch, items):
    provider, _, _ = _build_provider(monkeypatch, lambda texts: items)

    with pytest.raises(KnowledgeDocumentError) as exc_info:
        provider.embed_query("query")

    assert exc_info.value.code == "embedding_invalid_response"


def test_response_indices_must_be_complete_and_unique(monkeypatch):
    provider, _, _ = _build_provider(
        monkeypatch,
        lambda texts: [
            _EmbeddingItem(index=0, embedding=_vector(1.0)),
            _EmbeddingItem(index=0, embedding=_vector(2.0)),
        ],
    )

    with pytest.raises(KnowledgeDocumentError) as exc_info:
        provider.embed_documents(["first", "second"])

    assert exc_info.value.code == "embedding_invalid_response"


def test_malformed_embedding_item_is_rejected_with_stable_error(monkeypatch):
    provider, _, _ = _build_provider(
        monkeypatch,
        lambda texts: [SimpleNamespace(index=0)],
    )

    with pytest.raises(KnowledgeDocumentError) as exc_info:
        provider.embed_query("query")

    assert exc_info.value.code == "embedding_invalid_response"


@pytest.mark.parametrize("dimensions", [1023, 1025])
def test_vector_dimension_mismatch_is_rejected(monkeypatch, dimensions):
    provider, _, _ = _build_provider(
        monkeypatch,
        lambda texts: [
            _EmbeddingItem(index=0, embedding=[1.0] * dimensions),
        ],
    )

    with pytest.raises(KnowledgeDocumentError) as exc_info:
        provider.embed_query("query")

    assert exc_info.value.code == "embedding_dimension_mismatch"


@pytest.mark.parametrize(
    "invalid_vector",
    [
        [],
        [float("nan"), *([1.0] * 1023)],
        [float("inf"), *([1.0] * 1023)],
        [float("-inf"), *([1.0] * 1023)],
        [0.0] * 1024,
        ["not-a-number", *([1.0] * 1023)],
    ],
    ids=["empty", "nan", "positive-infinity", "negative-infinity", "zero", "text"],
)
def test_invalid_vector_values_are_rejected(monkeypatch, invalid_vector):
    provider, _, _ = _build_provider(
        monkeypatch,
        lambda texts: [_EmbeddingItem(index=0, embedding=invalid_vector)],
    )

    with pytest.raises(KnowledgeDocumentError) as exc_info:
        provider.embed_query("query")

    assert exc_info.value.code == "embedding_invalid_response"
