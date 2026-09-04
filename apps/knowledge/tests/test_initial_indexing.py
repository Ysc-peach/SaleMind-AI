"""Initial knowledge indexing orchestration contracts."""

from hashlib import sha256
from uuid import uuid4

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import IntegrityError, connection
from django.db.models.query import QuerySet
from django.utils import timezone

from apps.knowledge.exceptions import (
    KnowledgeDocumentError,
    KnowledgeDocumentErrorCode,
)
from apps.knowledge.tests.parser_fixtures import build_pdf
from apps.knowledge.tests.embedding_fakes import DeterministicEmbeddingProvider


pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def knowledge_media_root(settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path


@pytest.fixture
def creator(django_user_model):
    return django_user_model.objects.create_user(
        username="indexing-admin",
        email="indexing-admin@example.com",
        role="admin",
        password="StrongPassword123!",
    )


@pytest.fixture
def make_document(creator):
    from apps.knowledge.models import KnowledgeDocument

    sequence = 0

    def factory(*, content: bytes | None = None, filename: str = "guide.md", **overrides):
        nonlocal sequence
        sequence += 1
        file_content = content or (
            b"# Deployment\n\nShared deployment guide.\n\n"
            b"## PostgreSQL\n\nPostgreSQL configuration details.\n"
        )
        values = {
            "title": f"Knowledge document {sequence}",
            "document_type": "technical",
            "source_file": SimpleUploadedFile(
                filename,
                file_content,
                content_type="text/markdown",
            ),
            "original_filename": filename,
            "mime_type": "text/markdown",
            "file_size": len(file_content),
            "checksum_sha256": sha256(file_content).hexdigest(),
            "status": "pending",
            "created_by": creator,
        }
        values.update(overrides)
        return KnowledgeDocument.objects.create(**values)

    return factory


class ObservingEmbeddingProvider(DeterministicEmbeddingProvider):
    def __init__(self, document_id: int):
        self.document_id = document_id
        self.documents: list[str] = []
        self.observed_state: dict = {}

    def embed_documents(self, texts):
        from apps.knowledge.models import KnowledgeDocument

        document = KnowledgeDocument.objects.get(pk=self.document_id)
        self.observed_state = {
            "status": document.status,
            "indexing_run_id": document.indexing_run_id,
            "processing_started_at": document.processing_started_at,
            "error_code": document.error_code,
            "error_message": document.error_message,
        }
        self.documents = list(texts)
        return super().embed_documents(texts)


class FailingEmbeddingProvider(DeterministicEmbeddingProvider):
    def embed_documents(self, texts):
        raise KnowledgeDocumentError(
            KnowledgeDocumentErrorCode.EMBEDDING_PROVIDER_ERROR
        )


class ExplodingEmbeddingProvider(DeterministicEmbeddingProvider):
    def embed_documents(self, texts):
        raise RuntimeError(
            "provider secret at C:\\private\\knowledge.md: confidential content"
        )


class WrongCountEmbeddingProvider(DeterministicEmbeddingProvider):
    def __init__(self, count: int):
        self.count = count

    def embed_documents(self, texts):
        return [[float(index + 1)] * 1024 for index in range(self.count)]


class ConflictingEmbeddingProvider(DeterministicEmbeddingProvider):
    def __init__(self, document_id: int):
        self.document_id = document_id
        self.replacement_run_id = uuid4()
        self.replacement_started_at = timezone.now()

    def embed_documents(self, texts):
        from apps.knowledge.models import KnowledgeDocument

        KnowledgeDocument.objects.filter(pk=self.document_id).update(
            status="processing",
            indexing_run_id=self.replacement_run_id,
            processing_started_at=self.replacement_started_at,
        )
        return super().embed_documents(texts)


class ConflictingFailingEmbeddingProvider(ConflictingEmbeddingProvider):
    def embed_documents(self, texts):
        super().embed_documents(texts)
        raise KnowledgeDocumentError(
            KnowledgeDocumentErrorCode.EMBEDDING_PROVIDER_ERROR
        )


def assert_initial_indexing_failed(document, *, code: str, message: str):
    document.refresh_from_db()
    assert document.status == "failed"
    assert document.chunk_count == 0
    assert document.chunks.count() == 0
    assert document.indexing_run_id is None
    assert document.processing_started_at is None
    assert document.last_indexed_at is None
    assert document.error_code == code
    assert document.error_message == message


def test_pending_document_is_indexed_into_ready_traceable_chunks(make_document):
    from apps.knowledge.models import KnowledgeChunk
    from apps.knowledge.services.indexing import index_document

    document = make_document(
        error_code="previous_error",
        error_message="Previous safe message.",
    )
    provider = ObservingEmbeddingProvider(document.pk)

    result = index_document(document.pk, provider=provider)

    document.refresh_from_db()
    chunks = list(KnowledgeChunk.objects.filter(document=document).order_by("chunk_index"))

    assert result.pk == document.pk
    assert provider.observed_state["status"] == "processing"
    assert provider.observed_state["indexing_run_id"] is not None
    assert provider.observed_state["processing_started_at"] is not None
    assert provider.observed_state["error_code"] == ""
    assert provider.observed_state["error_message"] == ""

    assert document.status == "ready"
    assert document.chunk_count == 2
    assert document.embedding_provider == "fake"
    assert document.embedding_model == "sha256-test"
    assert document.embedding_dimensions == 1024
    assert document.last_indexed_at is not None
    assert document.last_index_run_id == provider.observed_state["indexing_run_id"]
    assert document.indexing_run_id is None
    assert document.processing_started_at is None
    assert document.error_code == ""
    assert document.error_message == ""

    assert provider.documents == [
        "Shared deployment guide.",
        "PostgreSQL configuration details.",
    ]
    assert [chunk.chunk_index for chunk in chunks] == [0, 1]
    assert [chunk.content for chunk in chunks] == provider.documents
    assert [chunk.section_title for chunk in chunks] == [
        "Deployment",
        "Deployment > PostgreSQL",
    ]
    assert [chunk.source_reference for chunk in chunks] == [
        "《guide.md》 > Deployment",
        "《guide.md》 > Deployment > PostgreSQL",
    ]
    assert [chunk.metadata for chunk in chunks] == [
        {"file_type": "markdown", "section_path": ["Deployment"]},
        {
            "file_type": "markdown",
            "section_path": ["Deployment", "PostgreSQL"],
        },
    ]
    assert [chunk.char_count for chunk in chunks] == [24, 33]
    assert list(chunks[0].embedding) == pytest.approx(
        provider.embed_query("Shared deployment guide.")
    )
    assert list(chunks[1].embedding) == pytest.approx(
        provider.embed_query("PostgreSQL configuration details.")
    )


@pytest.mark.parametrize(
    ("status", "state_fields"),
    [
        ("ready", {"last_indexed_at": timezone.now()}),
        ("failed", {}),
        (
            "processing",
            {
                "indexing_run_id": uuid4(),
                "processing_started_at": timezone.now(),
            },
        ),
    ],
)
def test_initial_indexing_rejects_non_pending_state(
    make_document,
    status,
    state_fields,
):
    from apps.knowledge.services.indexing import index_document

    document = make_document(status=status, **state_fields)

    with pytest.raises(KnowledgeDocumentError) as exc_info:
        index_document(
            document.pk,
            provider=DeterministicEmbeddingProvider(),
        )

    document.refresh_from_db()
    assert exc_info.value.code == "invalid_indexing_state"
    assert document.status == status
    assert document.chunks.count() == 0


def test_second_initial_indexing_does_not_duplicate_chunks(make_document):
    from apps.knowledge.services.indexing import index_document

    document = make_document()
    provider = DeterministicEmbeddingProvider()
    index_document(document.pk, provider=provider)

    with pytest.raises(KnowledgeDocumentError) as exc_info:
        index_document(document.pk, provider=provider)

    document.refresh_from_db()
    assert exc_info.value.code == "invalid_indexing_state"
    assert document.status == "ready"
    assert document.chunk_count == 2
    assert document.chunks.count() == 2


def test_parser_failure_marks_document_failed_without_chunks(make_document):
    from apps.knowledge.services.indexing import index_document

    document = make_document(content=b"not a pdf", filename="broken.pdf")

    with pytest.raises(KnowledgeDocumentError) as exc_info:
        index_document(
            document.pk,
            provider=DeterministicEmbeddingProvider(),
        )

    assert exc_info.value.code == "invalid_file"
    assert_initial_indexing_failed(
        document,
        code="invalid_file",
        message="The file is invalid or corrupted.",
    )


def test_chunker_failure_preserves_safe_domain_error(monkeypatch, make_document):
    from apps.knowledge.services import indexing

    document = make_document()

    def fail_chunking(segments):
        raise KnowledgeDocumentError(
            KnowledgeDocumentErrorCode.CHUNK_LIMIT_EXCEEDED
        )

    monkeypatch.setattr(indexing, "chunk_segments", fail_chunking)

    with pytest.raises(KnowledgeDocumentError) as exc_info:
        indexing.index_document(
            document.pk,
            provider=DeterministicEmbeddingProvider(),
        )

    assert exc_info.value.code == "chunk_limit_exceeded"
    assert_initial_indexing_failed(
        document,
        code="chunk_limit_exceeded",
        message="The document exceeds the allowed chunk count.",
    )


def test_embedding_failure_marks_document_failed_without_chunks(make_document):
    from apps.knowledge.services.indexing import index_document

    document = make_document()

    with pytest.raises(KnowledgeDocumentError) as exc_info:
        index_document(document.pk, provider=FailingEmbeddingProvider())

    assert exc_info.value.code == "embedding_provider_error"
    assert_initial_indexing_failed(
        document,
        code="embedding_provider_error",
        message="The embedding provider request failed.",
    )


def test_missing_source_file_is_stored_as_safe_failure(make_document):
    from apps.knowledge.services.indexing import index_document

    document = make_document()
    document.source_file.storage.delete(document.source_file.name)

    with pytest.raises(KnowledgeDocumentError) as exc_info:
        index_document(
            document.pk,
            provider=DeterministicEmbeddingProvider(),
        )

    assert exc_info.value.code == "invalid_file"
    assert_initial_indexing_failed(
        document,
        code="invalid_file",
        message="The file is invalid or corrupted.",
    )


def test_unknown_failure_is_sanitized_before_storage(make_document):
    from apps.knowledge.services.indexing import index_document

    document = make_document()

    with pytest.raises(KnowledgeDocumentError) as exc_info:
        index_document(document.pk, provider=ExplodingEmbeddingProvider())

    assert exc_info.value.code == "indexing_failed"
    assert "secret" not in str(exc_info.value)
    assert "confidential content" not in str(exc_info.value)
    assert "C:\\private" not in str(exc_info.value)
    assert_initial_indexing_failed(
        document,
        code="indexing_failed",
        message="The document could not be indexed.",
    )


def test_unknown_parser_exception_is_not_misclassified_as_invalid_file(
    monkeypatch,
    make_document,
):
    from apps.knowledge.services import indexing

    document = make_document()

    def fail_parser(source, original_filename):
        raise TypeError("internal parser detail at C:\\private\\source.md")

    monkeypatch.setattr(indexing, "parse_document", fail_parser)

    with pytest.raises(KnowledgeDocumentError) as exc_info:
        indexing.index_document(
            document.pk,
            provider=DeterministicEmbeddingProvider(),
        )

    assert exc_info.value.code == "indexing_failed"
    assert "private" not in str(exc_info.value)
    assert_initial_indexing_failed(
        document,
        code="indexing_failed",
        message="The document could not be indexed.",
    )


def test_empty_chunk_result_fails_instead_of_creating_empty_ready_document(
    monkeypatch,
    make_document,
):
    from apps.knowledge.services import indexing

    document = make_document()
    monkeypatch.setattr(indexing, "chunk_segments", lambda segments: [])

    with pytest.raises(KnowledgeDocumentError) as exc_info:
        indexing.index_document(
            document.pk,
            provider=DeterministicEmbeddingProvider(),
        )

    assert exc_info.value.code == "no_indexable_content"
    assert_initial_indexing_failed(
        document,
        code="no_indexable_content",
        message="The document contains no indexable content.",
    )


@pytest.mark.parametrize("vector_count", [1, 3])
def test_embedding_count_must_match_chunk_count(make_document, vector_count):
    from apps.knowledge.services.indexing import index_document

    document = make_document()

    with pytest.raises(KnowledgeDocumentError) as exc_info:
        index_document(
            document.pk,
            provider=WrongCountEmbeddingProvider(vector_count),
        )

    assert exc_info.value.code == "embedding_invalid_response"
    assert_initial_indexing_failed(
        document,
        code="embedding_invalid_response",
        message="The embedding provider returned an invalid response.",
    )


def test_old_run_cannot_overwrite_replacement_run(make_document):
    from apps.knowledge.services.indexing import index_document

    document = make_document()
    provider = ConflictingEmbeddingProvider(document.pk)

    with pytest.raises(KnowledgeDocumentError) as exc_info:
        index_document(document.pk, provider=provider)

    document.refresh_from_db()
    assert exc_info.value.code == "indexing_run_conflict"
    assert document.status == "processing"
    assert document.indexing_run_id == provider.replacement_run_id
    assert document.processing_started_at == provider.replacement_started_at
    assert document.error_code == ""
    assert document.error_message == ""
    assert document.chunk_count == 0
    assert document.chunks.count() == 0


def test_old_failed_run_reports_conflict_without_overwriting_replacement_run(
    make_document,
):
    from apps.knowledge.services.indexing import index_document

    document = make_document()
    provider = ConflictingFailingEmbeddingProvider(document.pk)

    with pytest.raises(KnowledgeDocumentError) as exc_info:
        index_document(document.pk, provider=provider)

    document.refresh_from_db()
    assert exc_info.value.code == "indexing_run_conflict"
    assert document.status == "processing"
    assert document.indexing_run_id == provider.replacement_run_id
    assert document.processing_started_at == provider.replacement_started_at
    assert document.error_code == ""
    assert document.error_message == ""
    assert document.chunks.count() == 0


def test_partial_bulk_insert_is_rolled_back_before_failure_state(
    monkeypatch,
    make_document,
):
    from apps.knowledge.models import KnowledgeChunk
    from apps.knowledge.services.indexing import index_document

    document = make_document()
    original_bulk_create = QuerySet.bulk_create

    def insert_one_then_fail(queryset, objects, *args, **kwargs):
        if queryset.model is KnowledgeChunk:
            original_bulk_create(queryset, objects[:1], *args, **kwargs)
            raise IntegrityError("simulated bulk insert failure")
        return original_bulk_create(queryset, objects, *args, **kwargs)

    monkeypatch.setattr(QuerySet, "bulk_create", insert_one_then_fail)

    with pytest.raises(KnowledgeDocumentError) as exc_info:
        index_document(
            document.pk,
            provider=DeterministicEmbeddingProvider(),
        )

    assert exc_info.value.code == "indexing_failed"
    assert_initial_indexing_failed(
        document,
        code="indexing_failed",
        message="The document could not be indexed.",
    )


def test_ready_update_failure_rolls_back_all_chunks(monkeypatch, make_document):
    from apps.knowledge.models import KnowledgeDocument
    from apps.knowledge.services.indexing import index_document

    document = make_document()
    original_save = KnowledgeDocument.save

    def fail_ready_save(instance, *args, **kwargs):
        if instance.status == KnowledgeDocument.Status.READY:
            raise IntegrityError("simulated ready update failure")
        return original_save(instance, *args, **kwargs)

    monkeypatch.setattr(KnowledgeDocument, "save", fail_ready_save)

    with pytest.raises(KnowledgeDocumentError) as exc_info:
        index_document(
            document.pk,
            provider=DeterministicEmbeddingProvider(),
        )

    assert exc_info.value.code == "indexing_failed"
    assert_initial_indexing_failed(
        document,
        code="indexing_failed",
        message="The document could not be indexed.",
    )


def test_pdf_page_sources_are_preserved_in_persisted_chunks(make_document):
    from apps.knowledge.services.indexing import index_document

    document = make_document(
        content=build_pdf(["First page guidance", "Second page details"]),
        filename="manual.pdf",
        mime_type="application/pdf",
    )
    provider = DeterministicEmbeddingProvider()

    index_document(document.pk, provider=provider)

    chunks = list(document.chunks.order_by("chunk_index"))
    assert [chunk.content for chunk in chunks] == [
        "First page guidance",
        "Second page details",
    ]
    assert [chunk.page_number for chunk in chunks] == [1, 2]
    assert [chunk.section_title for chunk in chunks] == ["", ""]
    assert [chunk.source_reference for chunk in chunks] == [
        "《manual.pdf》第 1 页",
        "《manual.pdf》第 2 页",
    ]
    assert [chunk.metadata for chunk in chunks] == [
        {"file_type": "pdf", "page_number": 1},
        {"file_type": "pdf", "page_number": 2},
    ]


@pytest.mark.django_db(transaction=True)
def test_parse_chunk_and_embedding_run_outside_database_transaction(
    monkeypatch,
    make_document,
):
    from apps.knowledge.services import indexing

    document = make_document()
    observed_atomic_states = []
    original_parse_document = indexing.parse_document
    original_chunk_segments = indexing.chunk_segments

    def observe_parse(*args, **kwargs):
        observed_atomic_states.append(("parse", connection.in_atomic_block))
        return original_parse_document(*args, **kwargs)

    def observe_chunk(*args, **kwargs):
        observed_atomic_states.append(("chunk", connection.in_atomic_block))
        return original_chunk_segments(*args, **kwargs)

    class TransactionObservingProvider(DeterministicEmbeddingProvider):
        def embed_documents(self, texts):
            observed_atomic_states.append(("embedding", connection.in_atomic_block))
            return super().embed_documents(texts)

    monkeypatch.setattr(indexing, "parse_document", observe_parse)
    monkeypatch.setattr(indexing, "chunk_segments", observe_chunk)

    indexing.index_document(
        document.pk,
        provider=TransactionObservingProvider(),
    )

    assert observed_atomic_states == [
        ("parse", False),
        ("chunk", False),
        ("embedding", False),
    ]


def test_default_provider_is_resolved_by_factory_without_network(
    monkeypatch,
    make_document,
):
    from apps.knowledge.services import indexing

    document = make_document()
    provider = DeterministicEmbeddingProvider()
    monkeypatch.setattr(indexing, "get_embedding_provider", lambda: provider)

    indexing.index_document(document.pk)

    document.refresh_from_db()
    assert document.status == "ready"
    assert document.embedding_provider == provider.provider_name
    assert document.embedding_model == provider.model_name
    assert document.embedding_dimensions == provider.dimensions
