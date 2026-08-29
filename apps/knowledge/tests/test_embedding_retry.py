"""Retry and error-sanitization behavior using the real OpenAI SDK transport."""

import logging

import httpx2
import openai
import pytest

from apps.knowledge.embeddings.base import EmbeddingProviderConfig
from apps.knowledge.exceptions import KnowledgeDocumentError


def _success_response(request, *, value=1.0):
    return httpx2.Response(
        200,
        request=request,
        json={
            "object": "list",
            "data": [
                {
                    "object": "embedding",
                    "index": 0,
                    "embedding": [value] * 1024,
                }
            ],
            "model": "BAAI/bge-m3",
            "usage": {"prompt_tokens": 1, "total_tokens": 1},
        },
    )


@pytest.fixture
def transport_provider(monkeypatch, request):
    from apps.knowledge.embeddings import openai_compatible

    clients = []
    original_client_class = openai.OpenAI
    monkeypatch.setattr(openai._base_client.time, "sleep", lambda seconds: None)

    def build(handler, *, max_retries=2):
        http_client = httpx2.Client(transport=httpx2.MockTransport(handler))
        clients.append(http_client)

        def client_factory(**kwargs):
            return original_client_class(**kwargs, http_client=http_client)

        monkeypatch.setattr(openai_compatible, "OpenAI", client_factory)
        config = EmbeddingProviderConfig(
            provider_name="openai_compatible",
            model_name="BAAI/bge-m3",
            dimensions=1024,
            api_key="provider-test-secret",
            base_url="https://embedding.example/v1",
            timeout_seconds=17,
            max_retries=max_retries,
            batch_size=2,
        )
        return openai_compatible.OpenAICompatibleEmbeddingProvider(config)

    request.addfinalizer(lambda: [client.close() for client in clients])
    return build


def test_connection_errors_stop_after_configured_retry_limit(transport_provider):
    attempts = 0

    def handler(request):
        nonlocal attempts
        attempts += 1
        raise httpx2.ConnectError("temporary connection failure", request=request)

    provider = transport_provider(handler, max_retries=2)

    with pytest.raises(KnowledgeDocumentError) as exc_info:
        provider.embed_query("query")

    assert exc_info.value.code == "embedding_provider_error"
    assert attempts == 3


def test_connection_error_can_recover_within_retry_limit(transport_provider):
    attempts = 0

    def handler(request):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise httpx2.ConnectError("temporary connection failure", request=request)
        return _success_response(request, value=1.5)

    provider = transport_provider(handler, max_retries=2)

    vector = provider.embed_query("query")

    assert vector == [1.5] * 1024
    assert attempts == 2


@pytest.mark.parametrize("status_code", [429, 500, 503])
def test_recoverable_http_status_is_retried(transport_provider, status_code):
    attempts = 0

    def handler(request):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            return httpx2.Response(
                status_code,
                request=request,
                headers={"retry-after-ms": "0"},
                json={"error": {"message": "temporary provider failure"}},
            )
        return _success_response(request)

    provider = transport_provider(handler, max_retries=2)

    vector = provider.embed_query("query")

    assert vector == [1.0] * 1024
    assert attempts == 2


@pytest.mark.parametrize("status_code", [400, 401, 403])
def test_non_recoverable_http_status_is_not_retried(
    transport_provider,
    status_code,
):
    attempts = 0

    def handler(request):
        nonlocal attempts
        attempts += 1
        return httpx2.Response(
            status_code,
            request=request,
            json={"error": {"message": "permanent provider failure"}},
        )

    provider = transport_provider(handler, max_retries=2)

    with pytest.raises(KnowledgeDocumentError) as exc_info:
        provider.embed_query("query")

    assert exc_info.value.code == "embedding_provider_error"
    assert attempts == 1


def test_provider_error_does_not_leak_secret_or_document_text(
    transport_provider,
    caplog,
):
    secret = "provider-test-secret"
    document_text = "confidential customer acquisition details"

    def handler(request):
        return httpx2.Response(
            401,
            request=request,
            json={
                "error": {
                    "message": f"bad key {secret}; rejected {document_text}",
                }
            },
        )

    caplog.set_level(logging.INFO)
    provider = transport_provider(handler, max_retries=2)

    with pytest.raises(KnowledgeDocumentError) as exc_info:
        provider.embed_query(document_text)

    rendered_error = str(exc_info.value)
    assert exc_info.value.code == "embedding_provider_error"
    assert secret not in rendered_error
    assert document_text not in rendered_error
    assert secret not in caplog.text
    assert document_text not in caplog.text
