"""Authenticated Knowledge vector search API contracts."""

import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.models import UserRole
from apps.knowledge.exceptions import (
    KnowledgeDocumentError,
    KnowledgeDocumentErrorCode,
)
from apps.knowledge.models import KnowledgeChunk, KnowledgeDocument


pytestmark = pytest.mark.django_db

SEARCH_URL = "/api/knowledge/search/"
SEARCH_RESULT_FIELDS = {
    "chunk_id",
    "document_id",
    "document_title",
    "document_type",
    "original_filename",
    "content",
    "page_number",
    "section_title",
    "source_reference",
    "similarity",
}


def vector(*values):
    return [*values, *([0.0] * (1024 - len(values)))]


class APISearchProvider:
    provider_name = "search-api-fake"
    model_name = "api-unit-space"
    dimensions = 1024

    def __init__(self, query_vector=None):
        self.query_vector = query_vector or vector(1.0, 0.0)
        self.query_calls = []

    def embed_query(self, text):
        self.query_calls.append(text)
        return self.query_vector

    def embed_documents(self, texts):
        raise AssertionError("Search must not call embed_documents().")


class FailingQueryProvider(APISearchProvider):
    def __init__(self, error_code):
        super().__init__()
        self.error_code = error_code

    def embed_query(self, text):
        raise KnowledgeDocumentError(self.error_code)


@pytest.fixture
def api_client():
    return APIClient()


@pytest.fixture
def user_factory():
    sequence = 0

    def factory(role=UserRole.ADMIN, *, is_staff=False, is_superuser=False):
        nonlocal sequence
        sequence += 1
        return get_user_model().objects.create_user(
            username=f"search-api-user-{sequence}",
            email=f"search-api-user-{sequence}@example.com",
            role=role,
            password="StrongPassword123!",
            is_staff=is_staff,
            is_superuser=is_superuser,
        )

    return factory


@pytest.fixture
def search_provider(monkeypatch):
    from apps.knowledge.services import search

    provider = APISearchProvider()
    monkeypatch.setattr(search, "get_embedding_provider", lambda: provider)
    return provider


def create_ready_chunk(
    *,
    owner,
    embedding=None,
    document_type="technical",
    title="SalesMind deployment guide",
    provider_name="search-api-fake",
    model_name="api-unit-space",
    dimensions=1024,
):
    document = KnowledgeDocument.objects.create(
        title=title,
        document_type=document_type,
        source_file="knowledge/documents/test/search-api.txt",
        original_filename="search-api.txt",
        mime_type="text/plain",
        file_size=100,
        checksum_sha256="b" * 64,
        status="ready",
        embedding_provider=provider_name,
        embedding_model=model_name,
        embedding_dimensions=dimensions,
        chunk_count=1,
        last_indexed_at=timezone.now(),
        created_by=owner,
    )
    chunk = KnowledgeChunk.objects.create(
        document=document,
        chunk_index=0,
        content="Private deployment is supported.",
        embedding=embedding or vector(1.0, 0.0),
        page_number=3,
        section_title="Deployment",
        source_reference="《SalesMind deployment guide》第 3 页",
        metadata={"private": "not exposed"},
        char_count=32,
    )
    return document, chunk


def test_admin_can_search_and_receive_safe_citation_results(
    api_client,
    user_factory,
    search_provider,
):
    actor = user_factory(UserRole.ADMIN)
    document, chunk = create_ready_chunk(owner=actor)
    api_client.force_authenticate(user=actor)

    response = api_client.post(
        SEARCH_URL,
        {"query": "private deployment"},
        format="json",
    )

    assert response.status_code == 200
    assert set(response.data) == {"results"}
    assert len(response.data["results"]) == 1
    result = response.data["results"][0]
    assert set(result) == SEARCH_RESULT_FIELDS
    assert result["chunk_id"] == chunk.id
    assert result["document_id"] == document.id
    assert result["document_title"] == document.title
    assert result["document_type"] == document.document_type
    assert result["original_filename"] == document.original_filename
    assert result["source_reference"] == "《SalesMind deployment guide》第 3 页"
    assert result["similarity"] == pytest.approx(1.0)
    assert search_provider.query_calls == ["private deployment"]


@pytest.mark.parametrize("role", [UserRole.SALES, UserRole.PRESALES])
def test_sales_and_presales_can_search(
    api_client,
    user_factory,
    search_provider,
    role,
):
    owner = user_factory(UserRole.ADMIN)
    create_ready_chunk(owner=owner)
    actor = user_factory(role)
    api_client.force_authenticate(user=actor)

    response = api_client.post(SEARCH_URL, {"query": "deployment"}, format="json")

    assert response.status_code == 200
    assert len(response.data["results"]) == 1


def test_unauthenticated_search_is_rejected(api_client, search_provider):
    response = api_client.post(SEARCH_URL, {"query": "deployment"}, format="json")

    assert response.status_code == 401
    assert search_provider.query_calls == []


@pytest.mark.parametrize(
    "technical_flags",
    [
        {"is_staff": True},
        {"is_superuser": True},
        {"is_staff": True, "is_superuser": True},
    ],
)
def test_unknown_business_role_cannot_search_with_django_technical_flags(
    api_client,
    user_factory,
    search_provider,
    technical_flags,
):
    actor = user_factory(UserRole.SALES, **technical_flags)
    actor.role = "unknown-role"
    api_client.force_authenticate(user=actor)

    response = api_client.post(SEARCH_URL, {"query": "deployment"}, format="json")

    assert response.status_code == 403
    assert search_provider.query_calls == []


@pytest.mark.parametrize(
    ("payload", "field"),
    [
        ({}, "query"),
        ({"query": "   \t\n"}, "query"),
        ({"query": "x" * 2001}, "query"),
        ({"query": ["deployment"]}, "query"),
        ({"query": {"text": "deployment"}}, "query"),
        ({"query": "deployment", "top_k": 0}, "top_k"),
        ({"query": "deployment", "top_k": 21}, "top_k"),
        ({"query": "deployment", "document_type": "unknown"}, "document_type"),
    ],
)
def test_invalid_search_input_returns_400_without_embedding(
    api_client,
    user_factory,
    search_provider,
    payload,
    field,
):
    actor = user_factory(UserRole.ADMIN)
    api_client.force_authenticate(user=actor)

    response = api_client.post(SEARCH_URL, payload, format="json")

    assert response.status_code == 400
    assert field in response.data
    assert search_provider.query_calls == []


@pytest.mark.parametrize("top_k", [1, 20])
def test_search_accepts_top_k_boundaries(
    api_client,
    user_factory,
    search_provider,
    top_k,
):
    actor = user_factory(UserRole.ADMIN)
    api_client.force_authenticate(user=actor)

    response = api_client.post(
        SEARCH_URL,
        {"query": "deployment", "top_k": top_k},
        format="json",
    )

    assert response.status_code == 200
    assert response.data == {"results": []}


def test_search_trims_query_and_defaults_top_k_to_five(
    api_client,
    user_factory,
    search_provider,
):
    actor = user_factory(UserRole.ADMIN)
    document, _ = create_ready_chunk(owner=actor)
    for chunk_index in range(1, 7):
        KnowledgeChunk.objects.create(
            document=document,
            chunk_index=chunk_index,
            content=f"Additional result {chunk_index}",
            embedding=vector(1.0, float(chunk_index) / 10),
            page_number=None,
            section_title="",
            source_reference=f"Section {chunk_index}",
            metadata={},
            char_count=20,
        )
    api_client.force_authenticate(user=actor)

    response = api_client.post(
        SEARCH_URL,
        {"query": "  deployment  "},
        format="json",
    )

    assert response.status_code == 200
    assert len(response.data["results"]) == 5
    assert search_provider.query_calls == ["deployment"]


def test_search_filters_by_document_type(
    api_client,
    user_factory,
    search_provider,
):
    actor = user_factory(UserRole.ADMIN)
    technical_document, _ = create_ready_chunk(owner=actor)
    product_document, _ = create_ready_chunk(
        owner=actor,
        document_type="product",
        title="Product guide",
    )
    api_client.force_authenticate(user=actor)

    response = api_client.post(
        SEARCH_URL,
        {
            "query": "deployment",
            "document_type": "product",
        },
        format="json",
    )

    assert response.status_code == 200
    assert [item["document_id"] for item in response.data["results"]] == [
        product_document.id
    ]
    assert technical_document.id != product_document.id


def test_document_type_filter_with_no_matches_returns_empty_results(
    api_client,
    user_factory,
    search_provider,
):
    actor = user_factory(UserRole.ADMIN)
    create_ready_chunk(owner=actor, document_type="technical")
    api_client.force_authenticate(user=actor)

    response = api_client.post(
        SEARCH_URL,
        {"query": "deployment", "document_type": "faq"},
        format="json",
    )

    assert response.status_code == 200
    assert response.data == {"results": []}


def test_search_returns_empty_results_for_incompatible_embedding_space(
    api_client,
    user_factory,
    search_provider,
):
    actor = user_factory(UserRole.ADMIN)
    create_ready_chunk(owner=actor, model_name="old-model")
    api_client.force_authenticate(user=actor)

    response = api_client.post(SEARCH_URL, {"query": "deployment"}, format="json")

    assert response.status_code == 200
    assert response.data == {"results": []}


def test_search_response_does_not_expose_vectors_files_or_internal_state(
    api_client,
    user_factory,
    search_provider,
):
    actor = user_factory(UserRole.ADMIN)
    _, chunk = create_ready_chunk(owner=actor)
    api_client.force_authenticate(user=actor)

    response = api_client.post(SEARCH_URL, {"query": "deployment"}, format="json")

    assert response.status_code == 200
    result = response.data["results"][0]
    assert set(result) == SEARCH_RESULT_FIELDS
    forbidden_fields = {
        "embedding",
        "metadata",
        "source_file",
        "indexing_run_id",
        "checksum_sha256",
        "status",
    }
    assert forbidden_fields.isdisjoint(result)
    assert result["page_number"] == chunk.page_number
    assert result["section_title"] == chunk.section_title
    assert result["source_reference"] == chunk.source_reference


def test_search_does_not_write_knowledge_business_state(
    api_client,
    user_factory,
    search_provider,
):
    actor = user_factory(UserRole.ADMIN)
    document, chunk = create_ready_chunk(owner=actor)
    before = {
        "document_count": KnowledgeDocument.objects.count(),
        "chunk_count": KnowledgeChunk.objects.count(),
        "updated_at": document.updated_at,
        "last_indexed_at": document.last_indexed_at,
        "content": chunk.content,
    }
    api_client.force_authenticate(user=actor)

    response = api_client.post(SEARCH_URL, {"query": "deployment"}, format="json")

    assert response.status_code == 200
    document.refresh_from_db()
    chunk.refresh_from_db()
    assert KnowledgeDocument.objects.count() == before["document_count"]
    assert KnowledgeChunk.objects.count() == before["chunk_count"]
    assert document.updated_at == before["updated_at"]
    assert document.last_indexed_at == before["last_indexed_at"]
    assert chunk.content == before["content"]


@pytest.mark.parametrize(
    ("error_code", "expected_status"),
    [
        (KnowledgeDocumentErrorCode.EMBEDDING_PROVIDER_ERROR, 502),
        (KnowledgeDocumentErrorCode.EMBEDDING_INVALID_RESPONSE, 502),
        (KnowledgeDocumentErrorCode.EMBEDDING_DIMENSION_MISMATCH, 502),
        (KnowledgeDocumentErrorCode.EMBEDDING_NOT_CONFIGURED, 503),
        (KnowledgeDocumentErrorCode.UNSUPPORTED_EMBEDDING_PROVIDER, 503),
    ],
)
def test_embedding_failure_returns_stable_safe_http_error(
    monkeypatch,
    api_client,
    user_factory,
    search_provider,
    error_code,
    expected_status,
):
    from apps.knowledge.services import search

    secret = "super-secret-api-key"

    if error_code in {
        KnowledgeDocumentErrorCode.EMBEDDING_NOT_CONFIGURED,
        KnowledgeDocumentErrorCode.UNSUPPORTED_EMBEDDING_PROVIDER,
    }:
        def fail_provider():
            try:
                raise RuntimeError(f"Authorization: Bearer {secret}")
            except RuntimeError:
                raise KnowledgeDocumentError(error_code) from None

        monkeypatch.setattr(search, "get_embedding_provider", fail_provider)
    else:
        monkeypatch.setattr(
            search,
            "get_embedding_provider",
            lambda: FailingQueryProvider(error_code),
        )
    actor = user_factory(UserRole.ADMIN)
    api_client.force_authenticate(user=actor)

    response = api_client.post(
        SEARCH_URL,
        {"query": "sensitive enterprise query body"},
        format="json",
    )

    assert response.status_code == expected_status
    assert response.data == {
        "code": error_code.value,
        "message": KnowledgeDocumentError(error_code).safe_message,
    }
    response_text = str(response.data)
    assert secret not in response_text
    assert "Authorization" not in response_text
    assert "sensitive enterprise query body" not in response_text


def test_search_only_accepts_post(
    api_client,
    user_factory,
    search_provider,
):
    actor = user_factory(UserRole.ADMIN)
    api_client.force_authenticate(user=actor)

    response = api_client.get(SEARCH_URL)

    assert response.status_code == 405
    assert search_provider.query_calls == []
