"""Offline contracts for aligning Stage 8 knowledge with production retrieval."""

from hashlib import sha256
from importlib import import_module
from uuid import uuid4

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile

from apps.knowledge.tests.embedding_fakes import DeterministicEmbeddingProvider
from apps.sales.demo_fixtures import DEMO_KNOWLEDGE
from apps.sales.models import SolutionDraftRecord


pytestmark = pytest.mark.django_db


class ProductionSpaceFake(DeterministicEmbeddingProvider):
    provider_name = "openai_compatible"
    model_name = "BAAI/bge-m3"

    def __init__(self):
        self.document_calls = []
        self.query_calls = []

    def embed_documents(self, texts):
        self.document_calls.append(tuple(texts))
        return super().embed_documents(texts)

    def embed_query(self, text):
        self.query_calls.append(text)
        return super().embed_query(text)


class MismatchedSpaceFake(ProductionSpaceFake):
    provider_name = "other-provider"
    model_name = "other-model"


@pytest.fixture(autouse=True)
def benchmark_media_root(settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path


@pytest.fixture
def benchmark_admin(django_user_model):
    return django_user_model.objects.create_user(
        username="stage8-benchmark-admin",
        email="stage8-benchmark-admin@example.com",
        role="admin",
        is_staff=True,
        password="StrongPassword123!",
    )


def _benchmark_module():
    try:
        return import_module("apps.sales.services.real_provider_benchmark")
    except ModuleNotFoundError:
        pytest.fail("The real-provider benchmark retrieval harness is missing.")


def _pending_document(benchmark_admin, *, title="Stage 8 benchmark document"):
    from apps.knowledge.models import KnowledgeDocument

    content = b"# Enterprise knowledge\n\nPrivate deployment is supported.\n"
    return KnowledgeDocument.objects.create(
        title=title,
        document_type="technical",
        source_file=SimpleUploadedFile(
            "stage8-benchmark.md", content, content_type="text/markdown"
        ),
        original_filename="stage8-benchmark.md",
        mime_type="text/markdown",
        file_size=len(content),
        checksum_sha256=sha256(content).hexdigest(),
        status="pending",
        created_by=benchmark_admin,
    )


def test_benchmark_reviewer_can_approve_grounding_facts_without_superuser():
    from apps.knowledge.models import EnterpriseGroundingFact
    from apps.knowledge.services.grounding_fact_approval import _require_reviewer

    subject = _benchmark_module()
    run_id = uuid4()
    reviewer = subject.create_real_benchmark_reviewer(run_id=run_id)
    assert reviewer.role == "admin"
    assert reviewer.is_active is True
    assert reviewer.is_staff is True
    assert reviewer.is_superuser is False
    _require_reviewer(reviewer)

    ownership = subject.create_real_benchmark_knowledge(
        run_id=run_id,
        created_by=reviewer,
        embedding_provider=ProductionSpaceFake(),
        fixtures=(DEMO_KNOWLEDGE[0],),
    )
    facts = EnterpriseGroundingFact.objects.filter(pk__in=ownership.fact_ids)
    assert facts.count() == 3
    assert all(
        fact.approval_status == "approved" and fact.approved_by_id == reviewer.pk
        for fact in facts
    )


def test_real_benchmark_creation_uses_formal_indexing_with_explicit_provider(
    benchmark_admin,
):
    subject = _benchmark_module()
    provider = ProductionSpaceFake()
    run_id = uuid4()

    ownership = subject.create_real_benchmark_knowledge(
        run_id=run_id,
        created_by=benchmark_admin,
        embedding_provider=provider,
        fixtures=(DEMO_KNOWLEDGE[0],),
    )

    from apps.knowledge.models import EnterpriseGroundingFact, KnowledgeDocument

    document = KnowledgeDocument.objects.get(pk=ownership.document_ids[0])
    facts = EnterpriseGroundingFact.objects.filter(pk__in=ownership.fact_ids)
    assert provider.document_calls
    assert document.embedding_provider == "openai_compatible"
    assert document.embedding_model == "BAAI/bge-m3"
    assert document.embedding_dimensions == 1024
    assert document.chunks.count() > 0
    assert facts.count() > 0
    assert not facts.filter(is_stale=True).exists()
    assert not facts.exclude(approval_status="approved").exists()
    assert str(run_id) in document.title


def test_provider_model_dimension_mismatch_fails_before_retrieval(
    benchmark_admin,
):
    subject = _benchmark_module()
    document = _pending_document(benchmark_admin)
    from apps.knowledge.services.indexing import index_document

    index_document(document.pk, provider=ProductionSpaceFake())
    ownership = subject.RealBenchmarkKnowledgeOwnership(
        run_id=uuid4(), document_ids=(document.pk,), fact_ids=()
    )
    mismatched = MismatchedSpaceFake()

    with pytest.raises(subject.RealBenchmarkRetrievalError) as exc:
        subject.preflight_real_benchmark_retrieval(
            ownership,
            query="private deployment",
            embedding_provider=mismatched,
        )

    assert exc.value.category == "embedding_space_mismatch"
    assert mismatched.query_calls == []


def test_compatible_formal_index_passes_retrieval_preflight(benchmark_admin):
    subject = _benchmark_module()
    document = _pending_document(benchmark_admin)
    provider = ProductionSpaceFake()
    from apps.knowledge.services.indexing import index_document

    index_document(document.pk, provider=provider)
    ownership = subject.RealBenchmarkKnowledgeOwnership(
        run_id=uuid4(), document_ids=(document.pk,), fact_ids=()
    )

    result = subject.preflight_real_benchmark_retrieval(
        ownership,
        query="private deployment",
        embedding_provider=provider,
    )

    assert result.provider_name == "openai_compatible"
    assert result.model_name == "BAAI/bge-m3"
    assert result.dimensions == 1024
    assert result.compatible_chunk_count == document.chunks.count()
    assert result.retrieval_result_count > 0
    assert set(result.retrieved_document_ids) == {document.pk}


def test_preflight_failure_happens_before_solution_persistence(benchmark_admin):
    subject = _benchmark_module()
    document = _pending_document(benchmark_admin)
    from apps.knowledge.services.indexing import index_document

    index_document(document.pk, provider=ProductionSpaceFake())
    ownership = subject.RealBenchmarkKnowledgeOwnership(
        run_id=uuid4(), document_ids=(document.pk,), fact_ids=()
    )
    before = SolutionDraftRecord.objects.count()

    with pytest.raises(subject.RealBenchmarkRetrievalError):
        subject.run_real_provider_benchmark_gate(
            opportunity=None,
            analysis=None,
            created_by=None,
            ownership=ownership,
            query="private deployment",
            embedding_provider=MismatchedSpaceFake(),
            llm_provider=None,
            verifier_provider=None,
            idempotency_key=uuid4(),
        )

    assert SolutionDraftRecord.objects.count() == before


def test_cleanup_removes_only_run_owned_knowledge(benchmark_admin):
    subject = _benchmark_module()
    unrelated = _pending_document(
        benchmark_admin, title="Unrelated customer knowledge"
    )
    ownership = subject.create_real_benchmark_knowledge(
        run_id=uuid4(),
        created_by=benchmark_admin,
        embedding_provider=ProductionSpaceFake(),
        fixtures=(DEMO_KNOWLEDGE[0],),
    )

    subject.clear_real_benchmark_knowledge(ownership)

    from apps.knowledge.models import KnowledgeDocument

    assert not KnowledgeDocument.objects.filter(
        pk__in=ownership.document_ids
    ).exists()
    assert KnowledgeDocument.objects.filter(pk=unrelated.pk).exists()


def test_creation_failure_removes_partial_documents_and_proposed_facts(
    benchmark_admin,
    monkeypatch,
):
    subject = _benchmark_module()
    from apps.knowledge.models import EnterpriseGroundingFact, KnowledgeDocument

    before_documents = KnowledgeDocument.objects.count()
    before_facts = EnterpriseGroundingFact.objects.count()

    def fail_approval(*_args, **_kwargs):
        raise PermissionError("controlled approval interruption")

    monkeypatch.setattr(subject, "approve_grounding_facts", fail_approval)

    with pytest.raises(PermissionError, match="controlled approval interruption"):
        subject.create_real_benchmark_knowledge(
            run_id=uuid4(),
            created_by=benchmark_admin,
            embedding_provider=ProductionSpaceFake(),
            fixtures=(DEMO_KNOWLEDGE[0],),
        )

    assert KnowledgeDocument.objects.count() == before_documents
    assert EnterpriseGroundingFact.objects.count() == before_facts
