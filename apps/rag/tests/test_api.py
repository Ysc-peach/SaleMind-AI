"""Authenticated grounded RAG Answer API contracts."""

import json

import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

from apps.accounts.models import UserRole
from apps.knowledge.exceptions import (
    KnowledgeDocumentError,
    KnowledgeDocumentErrorCode,
)
from apps.llm.exceptions import LLMErrorCode, LLMProviderError
from apps.rag.exceptions import RAGErrorCode, RAGServiceError
from apps.rag.services.answering import (
    INSUFFICIENT_EVIDENCE_ANSWER,
    RAGAnswer,
    RAGSource,
)


pytestmark = pytest.mark.django_db

ANSWER_URL = "/api/rag/answer/"
SOURCE_FIELDS = {
    "label",
    "chunk_id",
    "document_id",
    "document_title",
    "document_type",
    "original_filename",
    "page_number",
    "section_title",
    "source_reference",
    "similarity",
}


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
            username=f"rag-api-user-{sequence}",
            email=f"rag-api-user-{sequence}@example.com",
            role=role,
            password="StrongPassword123!",
            is_staff=is_staff,
            is_superuser=is_superuser,
        )

    return factory


def source(*, index=1):
    return RAGSource(
        chunk_id=100 + index,
        document_id=200 + index,
        document_title=f"产品资料 {index}",
        document_type="technical",
        original_filename=f"product-{index}.pdf",
        content=f"安全检索证据 {index}",
        page_number=index if index != 2 else None,
        section_title=None if index == 1 else f"章节 {index}",
        source_reference=f"《产品资料 {index}》来源 {index}",
        similarity=0.9 - (index / 10),
    )


def successful_answer():
    return RAGAnswer(
        answer="根据资料，可以确认该能力。[S1][S2]",
        sources=(source(index=1), source(index=2), source(index=3)),
    )


@pytest.mark.parametrize(
    "role",
    [UserRole.ADMIN, UserRole.SALES, UserRole.PRESALES],
)
def test_v1_business_roles_can_answer(
    api_client,
    user_factory,
    monkeypatch,
    role,
):
    from apps.rag.services import answering

    calls = []
    monkeypatch.setattr(
        answering,
        "answer_question",
        lambda *args, **kwargs: calls.append((args, kwargs)) or successful_answer(),
    )
    actor = user_factory(role)
    api_client.force_authenticate(user=actor)

    response = api_client.post(
        ANSWER_URL,
        {"query": "  是否支持私有化部署？  ", "document_type": "technical"},
        format="json",
    )

    assert response.status_code == 200
    assert calls == [((), {"query": "是否支持私有化部署？", "document_type": "technical"})]


def test_anonymous_user_is_rejected_before_answer_service(api_client, monkeypatch):
    from apps.rag.services import answering

    monkeypatch.setattr(
        answering,
        "answer_question",
        lambda **kwargs: pytest.fail("Anonymous requests must not call RAG."),
    )

    response = api_client.post(ANSWER_URL, {"query": "问题"}, format="json")

    assert response.status_code == 401


@pytest.mark.parametrize(
    "technical_flags",
    [
        {"is_staff": True},
        {"is_superuser": True},
        {"is_staff": True, "is_superuser": True},
    ],
)
def test_unknown_business_role_cannot_bypass_with_django_flags(
    api_client,
    user_factory,
    monkeypatch,
    technical_flags,
):
    from apps.rag.services import answering

    monkeypatch.setattr(
        answering,
        "answer_question",
        lambda **kwargs: pytest.fail("Forbidden requests must not call RAG."),
    )
    actor = user_factory(UserRole.SALES, **technical_flags)
    actor.role = "unknown-role"
    api_client.force_authenticate(user=actor)

    response = api_client.post(ANSWER_URL, {"query": "问题"}, format="json")

    assert response.status_code == 403


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"query": ""},
        {"query": "  \t\n"},
        {"query": "x" * 2001},
        {"query": ["问题"]},
        {"query": {"text": "问题"}},
        {"query": "问题", "document_type": "unknown"},
    ],
)
def test_invalid_request_returns_safe_400_without_answering(
    api_client,
    user_factory,
    monkeypatch,
    payload,
):
    from apps.rag.services import answering

    monkeypatch.setattr(
        answering,
        "answer_question",
        lambda **kwargs: pytest.fail("Invalid input must not call RAG."),
    )
    api_client.force_authenticate(user=user_factory())

    response = api_client.post(ANSWER_URL, payload, format="json")

    assert response.status_code == 400
    assert response.data == {
        "code": "invalid_request",
        "message": "The RAG answer request is invalid.",
    }


@pytest.mark.parametrize(
    "forbidden_field",
    ["top_k", "provider", "model", "system_prompt", "messages", "api_key", "sources"],
)
def test_server_controlled_request_fields_are_explicitly_rejected(
    api_client,
    user_factory,
    monkeypatch,
    forbidden_field,
):
    from apps.rag.services import answering

    monkeypatch.setattr(
        answering,
        "answer_question",
        lambda **kwargs: pytest.fail("Forbidden fields must not call RAG."),
    )
    api_client.force_authenticate(user=user_factory())

    response = api_client.post(
        ANSWER_URL,
        {"query": "问题", forbidden_field: "client-controlled"},
        format="json",
    )

    assert response.status_code == 400
    assert response.data == {
        "code": "invalid_request",
        "message": "The RAG answer request is invalid.",
    }


def test_success_response_uses_ranked_authoritative_source_metadata(
    api_client,
    user_factory,
    monkeypatch,
):
    from apps.rag.services import answering

    monkeypatch.setattr(answering, "answer_question", lambda **kwargs: successful_answer())
    api_client.force_authenticate(user=user_factory())

    response = api_client.post(ANSWER_URL, {"query": "问题"}, format="json")

    assert response.status_code == 200
    assert set(response.data) == {"answer", "sources"}
    assert response.data["answer"] == "根据资料，可以确认该能力。[S1][S2]"
    assert [item["label"] for item in response.data["sources"]] == ["S1", "S2", "S3"]
    assert [item["chunk_id"] for item in response.data["sources"]] == [101, 102, 103]
    first = response.data["sources"][0]
    assert set(first) == SOURCE_FIELDS
    assert first == {
        "label": "S1",
        "chunk_id": 101,
        "document_id": 201,
        "document_title": "产品资料 1",
        "document_type": "technical",
        "original_filename": "product-1.pdf",
        "page_number": 1,
        "section_title": None,
        "source_reference": "《产品资料 1》来源 1",
        "similarity": pytest.approx(0.8),
    }
    rendered = json.dumps(response.data, ensure_ascii=False)
    assert "embedding" not in rendered
    assert "source_file" not in rendered
    assert "indexing_run_id" not in rendered
    assert "安全检索证据" not in rendered


def test_no_evidence_is_a_normal_200_response(
    api_client,
    user_factory,
    monkeypatch,
):
    from apps.rag.services import answering

    monkeypatch.setattr(
        answering,
        "answer_question",
        lambda **kwargs: RAGAnswer(
            answer=INSUFFICIENT_EVIDENCE_ANSWER,
            sources=(),
        ),
    )
    api_client.force_authenticate(user=user_factory())

    response = api_client.post(ANSWER_URL, {"query": "未知问题"}, format="json")

    assert response.status_code == 200
    assert response.data == {
        "answer": INSUFFICIENT_EVIDENCE_ANSWER,
        "sources": [],
    }


@pytest.mark.parametrize(
    ("error", "expected_status"),
    [
        (
            KnowledgeDocumentError(
                KnowledgeDocumentErrorCode.EMBEDDING_NOT_CONFIGURED
            ),
            503,
        ),
        (
            KnowledgeDocumentError(
                KnowledgeDocumentErrorCode.UNSUPPORTED_EMBEDDING_PROVIDER
            ),
            503,
        ),
        (
            KnowledgeDocumentError(
                KnowledgeDocumentErrorCode.EMBEDDING_PROVIDER_ERROR
            ),
            502,
        ),
        (LLMProviderError(LLMErrorCode.LLM_NOT_CONFIGURED), 503),
        (LLMProviderError(LLMErrorCode.UNSUPPORTED_LLM_PROVIDER), 503),
        (LLMProviderError(LLMErrorCode.LLM_PROVIDER_ERROR), 502),
        (LLMProviderError(LLMErrorCode.LLM_INVALID_RESPONSE), 502),
        (RAGServiceError(RAGErrorCode.INVALID_QUERY), 400),
    ],
)
def test_domain_errors_map_to_safe_http_responses(
    api_client,
    user_factory,
    monkeypatch,
    error,
    expected_status,
):
    from apps.rag.services import answering

    secret = "never-expose-provider-secret"
    error.__cause__ = RuntimeError(f"Authorization: Bearer {secret}")

    def fail(**kwargs):
        raise error

    monkeypatch.setattr(answering, "answer_question", fail)
    api_client.force_authenticate(user=user_factory())

    response = api_client.post(ANSWER_URL, {"query": "问题"}, format="json")

    assert response.status_code == expected_status
    assert response.data == {
        "code": error.code,
        "message": error.safe_message,
    }
    rendered = json.dumps(response.data)
    assert secret not in rendered
    assert "traceback" not in rendered.lower()


def test_view_only_calls_rag_service_not_provider_layers(
    api_client,
    user_factory,
    monkeypatch,
):
    from apps.knowledge.services import search
    from apps.llm import factory
    from apps.rag.services import answering

    calls = []
    monkeypatch.setattr(
        answering,
        "answer_question",
        lambda **kwargs: calls.append(kwargs) or successful_answer(),
    )
    monkeypatch.setattr(
        search,
        "search_knowledge",
        lambda **kwargs: pytest.fail("View must not call Search directly."),
    )
    monkeypatch.setattr(
        factory,
        "get_llm_provider",
        lambda: pytest.fail("View must not construct an LLM directly."),
    )
    api_client.force_authenticate(user=user_factory())

    response = api_client.post(ANSWER_URL, {"query": "问题"}, format="json")

    assert response.status_code == 200
    assert calls == [{"query": "问题"}]


def test_answer_api_adds_no_database_queries_after_authentication(
    api_client,
    user_factory,
    monkeypatch,
    django_assert_num_queries,
):
    from apps.rag.services import answering

    monkeypatch.setattr(answering, "answer_question", lambda **kwargs: successful_answer())
    api_client.force_authenticate(user=user_factory())

    with django_assert_num_queries(0):
        response = api_client.post(ANSWER_URL, {"query": "只读请求"}, format="json")

    assert response.status_code == 200


def test_non_post_methods_are_not_available(api_client, user_factory, monkeypatch):
    from apps.rag.services import answering

    monkeypatch.setattr(
        answering,
        "answer_question",
        lambda **kwargs: pytest.fail("GET must not call RAG."),
    )
    api_client.force_authenticate(user=user_factory())

    response = api_client.get(ANSWER_URL)

    assert response.status_code == 405
