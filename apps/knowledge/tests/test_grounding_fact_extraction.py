"""Strict, propose-only grounding fact extraction tests."""

import json
from uuid import uuid4

import pytest
from django.db import connection
from django.utils import timezone

from apps.llm.base import LLMGeneration
from apps.llm.exceptions import LLMErrorCode, LLMProviderError


pytestmark = pytest.mark.django_db(transaction=True)


class ExtractionFakeLLM:
    provider_name = "fake"
    model_name = "fact-extractor"

    def __init__(self, content, callback=None):
        self.content = content
        self.callback = callback
        self.calls = []

    def generate(self, messages, *, max_output_tokens=None):
        self.calls.append(tuple(messages))
        if self.callback:
            self.callback()
        return LLMGeneration(content=self.content)


@pytest.fixture
def ready_document(django_user_model):
    from apps.knowledge.models import KnowledgeChunk, KnowledgeDocument

    actor = django_user_model.objects.create_user(
        username="extract-admin",
        email="extract-admin@example.com",
        role="admin",
        password="StrongPassword123!",
    )
    run_id = uuid4()
    document = KnowledgeDocument.objects.create(
        title="Private deployment",
        document_type="technical",
        source_file="knowledge/documents/private.md",
        original_filename="private.md",
        mime_type="text/markdown",
        file_size=128,
        checksum_sha256="b" * 64,
        status="ready",
        chunk_count=1,
        embedding_provider="fake",
        embedding_model="fake-model",
        embedding_dimensions=1024,
        last_indexed_at=timezone.now(),
        last_index_run_id=run_id,
        created_by=actor,
    )
    chunk = KnowledgeChunk.objects.create(
        document=document,
        chunk_index=0,
        content="SalesMind 明确支持企业私有化部署。",
        embedding=[0.0] * 1024,
        source_reference="Private deployment",
        char_count=24,
    )
    return document, chunk


def payload(chunk_id, **overrides):
    item = {
        "subject_key": "private_deployment",
        "statement": "SalesMind 支持企业私有化部署。",
        "status": "confirmed_supported",
        "source_chunk_id": chunk_id,
        "source_excerpt": "明确支持企业私有化部署",
    }
    item.update(overrides)
    return json.dumps({"facts": [item]}, ensure_ascii=False)


def test_valid_extraction_persists_only_proposed_snapshot(ready_document):
    from apps.knowledge.services.grounding_facts import extract_grounding_facts

    document, chunk = ready_document
    observed = []
    provider = ExtractionFakeLLM(
        payload(chunk.pk),
        callback=lambda: observed.append(connection.in_atomic_block),
    )

    facts = extract_grounding_facts(document.pk, llm_provider=provider)

    assert observed == [False]
    assert len(provider.calls) == 1
    assert len(facts) == 1
    fact = facts[0]
    assert fact.approval_status == "proposed"
    assert fact.approved_by is None
    assert fact.approved_at is None
    assert fact.is_stale is False
    assert fact.source_document_id == document.pk
    assert fact.source_chunk_id == chunk.pk
    assert fact.source_index_run_id == document.last_index_run_id
    assert fact.source_excerpt == "明确支持企业私有化部署"
    assert len(fact.source_content_hash) == 64


@pytest.mark.parametrize(
    "content",
    [
        "not-json",
        json.dumps({"facts": [], "extra": True}),
        json.dumps({"facts": [{"subject_key": "private_deployment"}]}),
        json.dumps({"facts": "invalid"}),
    ],
)
def test_malformed_or_wrong_schema_creates_no_facts(ready_document, content):
    from apps.knowledge.models import EnterpriseGroundingFact
    from apps.knowledge.services.grounding_facts import (
        GroundingFactExtractionError,
        extract_grounding_facts,
    )

    document, _ = ready_document

    with pytest.raises(GroundingFactExtractionError) as exc_info:
        extract_grounding_facts(document.pk, llm_provider=ExtractionFakeLLM(content))

    assert exc_info.value.code == "grounding_fact_invalid_response"
    assert EnterpriseGroundingFact.objects.count() == 0


def test_unknown_subject_key_is_rejected_without_facts(ready_document):
    from apps.knowledge.models import EnterpriseGroundingFact
    from apps.knowledge.services.grounding_facts import (
        GroundingFactExtractionError,
        extract_grounding_facts,
    )

    document, chunk = ready_document
    content = payload(chunk.pk, subject_key="database_compatibility")

    with pytest.raises(GroundingFactExtractionError):
        extract_grounding_facts(document.pk, llm_provider=ExtractionFakeLLM(content))

    assert EnterpriseGroundingFact.objects.count() == 0


@pytest.mark.parametrize(
    "overrides",
    [
        {"source_chunk_id": 999999},
        {"source_excerpt": "不存在于分块中的摘录"},
        {"status": "supported"},
        {"extra": "not allowed"},
    ],
)
def test_invalid_provenance_or_status_is_rejected(ready_document, overrides):
    from apps.knowledge.models import EnterpriseGroundingFact
    from apps.knowledge.services.grounding_facts import (
        GroundingFactExtractionError,
        extract_grounding_facts,
    )

    document, chunk = ready_document

    with pytest.raises(GroundingFactExtractionError):
        extract_grounding_facts(
            document.pk,
            llm_provider=ExtractionFakeLLM(payload(chunk.pk, **overrides)),
        )

    assert EnterpriseGroundingFact.objects.count() == 0


def test_concurrent_new_index_run_rejects_all_proposals(ready_document):
    from apps.knowledge.models import EnterpriseGroundingFact, KnowledgeDocument
    from apps.knowledge.services.grounding_facts import (
        GroundingFactExtractionError,
        extract_grounding_facts,
    )

    document, chunk = ready_document
    provider = ExtractionFakeLLM(
        payload(chunk.pk),
        callback=lambda: KnowledgeDocument.objects.filter(pk=document.pk).update(
            last_index_run_id=uuid4(),
        ),
    )

    with pytest.raises(GroundingFactExtractionError) as exc_info:
        extract_grounding_facts(document.pk, llm_provider=provider)

    assert exc_info.value.code == "grounding_fact_index_changed"
    assert EnterpriseGroundingFact.objects.count() == 0


def test_provider_failure_propagates_and_creates_no_facts(ready_document):
    from apps.knowledge.models import EnterpriseGroundingFact
    from apps.knowledge.services.grounding_facts import extract_grounding_facts

    document, _ = ready_document

    class FailingProvider(ExtractionFakeLLM):
        def generate(self, messages, *, max_output_tokens=None):
            raise LLMProviderError(LLMErrorCode.LLM_PROVIDER_ERROR)

    with pytest.raises(LLMProviderError):
        extract_grounding_facts(document.pk, llm_provider=FailingProvider("unused"))

    assert EnterpriseGroundingFact.objects.count() == 0


def test_prompt_keeps_chunks_in_untrusted_data_boundary(ready_document):
    from apps.knowledge.services.grounding_facts import extract_grounding_facts

    document, chunk = ready_document
    provider = ExtractionFakeLLM(payload(chunk.pk))

    extract_grounding_facts(document.pk, llm_provider=provider)

    system, user = provider.calls[0]
    assert "propose" in system["content"].lower()
    assert "APPROVED" in system["content"]
    assert "不可信" in system["content"]
    assert "<untrusted_knowledge_chunks>" in user["content"]
