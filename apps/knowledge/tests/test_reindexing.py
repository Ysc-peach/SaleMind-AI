"""Zero-downtime knowledge document reindexing contracts."""

from datetime import timedelta
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
from apps.knowledge.tests.embedding_fakes import DeterministicEmbeddingProvider


pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def knowledge_media_root(settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path


@pytest.fixture
def creator(django_user_model):
    return django_user_model.objects.create_user(
        username="reindex-admin",
        email="reindex-admin@example.com",
        role="admin",
        password="StrongPassword123!",
    )


@pytest.fixture
def make_ready_document(creator):
    from apps.knowledge.models import KnowledgeChunk, KnowledgeDocument

    sequence = 0

    def factory(*, content: bytes | None = None, filename: str = "guide.md", **overrides):
        nonlocal sequence
        sequence += 1
        file_content = content or (
            b"# Deployment\n\nUpdated deployment guidance.\n\n"
            b"## PostgreSQL\n\nUpdated database configuration.\n"
        )
        indexed_at = timezone.now() - timedelta(days=1)
        values = {
            "title": f"Ready knowledge document {sequence}",
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
            "status": "ready",
            "embedding_provider": "old-provider",
            "embedding_model": "old-model",
            "embedding_dimensions": 1024,
            "chunk_count": 2,
            "last_indexed_at": indexed_at,
            "created_by": creator,
        }
        values.update(overrides)
        document = KnowledgeDocument.objects.create(**values)
        KnowledgeChunk.objects.bulk_create(
            [
                KnowledgeChunk(
                    document=document,
                    chunk_index=index,
                    content=f"Old indexed content {index}",
                    embedding=[float(index + 1)] * 1024,
                    section_title="Old section",
                    source_reference="Old source",
                    metadata={"generation": "old", "position": index},
                    char_count=len(f"Old indexed content {index}"),
                )
                for index in range(2)
            ]
        )
        return document

    return factory


class ReindexEmbeddingProvider(DeterministicEmbeddingProvider):
    provider_name = "replacement-provider"
    model_name = "replacement-model"

    def __init__(self, document_id: int):
        self.document_id = document_id
        self.documents: list[str] = []
        self.observed_document: dict = {}
        self.observed_chunks: list[dict] = []

    def embed_documents(self, texts):
        from apps.knowledge.models import KnowledgeDocument

        document = KnowledgeDocument.objects.get(pk=self.document_id)
        self.observed_document = {
            "status": document.status,
            "chunk_count": document.chunk_count,
            "embedding_provider": document.embedding_provider,
            "embedding_model": document.embedding_model,
            "embedding_dimensions": document.embedding_dimensions,
            "last_indexed_at": document.last_indexed_at,
            "indexing_run_id": document.indexing_run_id,
            "processing_started_at": document.processing_started_at,
            "error_code": document.error_code,
            "error_message": document.error_message,
        }
        self.observed_chunks = list(
            document.chunks.order_by("chunk_index").values(
                "id", "chunk_index", "content", "metadata"
            )
        )
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
            "secret at C:\\private\\knowledge.md: confidential enterprise content"
        )


class ConflictingEmbeddingProvider(DeterministicEmbeddingProvider):
    def __init__(self, document_id: int):
        self.document_id = document_id
        self.replacement_run_id = uuid4()
        self.replacement_started_at = timezone.now()

    def embed_documents(self, texts):
        from apps.knowledge.models import KnowledgeDocument

        KnowledgeDocument.objects.filter(pk=self.document_id).update(
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


class ReplacementEmbeddingProvider(DeterministicEmbeddingProvider):
    provider_name = "takeover-provider"
    model_name = "takeover-model"


class StaleTakeoverEmbeddingProvider(DeterministicEmbeddingProvider):
    provider_name = "stale-provider"
    model_name = "stale-model"

    def __init__(self, document_id: int):
        self.document_id = document_id
        self.replacement_provider = ReplacementEmbeddingProvider()

    def embed_documents(self, texts):
        from django.conf import settings

        from apps.knowledge.models import KnowledgeDocument
        from apps.knowledge.services.indexing import reindex_document

        KnowledgeDocument.objects.filter(pk=self.document_id).update(
            processing_started_at=(
                timezone.now()
                - timedelta(
                    seconds=settings.KNOWLEDGE_INDEXING_STALE_TIMEOUT_SECONDS
                )
            )
        )
        reindex_document(
            self.document_id,
            provider=self.replacement_provider,
        )
        return super().embed_documents(texts)


def live_index_snapshot(document):
    document.refresh_from_db()
    return {
        "status": document.status,
        "chunk_count": document.chunk_count,
        "embedding_provider": document.embedding_provider,
        "embedding_model": document.embedding_model,
        "embedding_dimensions": document.embedding_dimensions,
        "last_indexed_at": document.last_indexed_at,
        "chunks": list(
            document.chunks.order_by("chunk_index").values(
                "id",
                "chunk_index",
                "content",
                "embedding",
                "page_number",
                "section_title",
                "source_reference",
                "metadata",
                "char_count",
            )
        ),
    }


def assert_reindex_failure_preserves_live_index(
    document,
    original_index,
    *,
    code: str,
    message: str,
):
    document.refresh_from_db()
    assert live_index_snapshot(document) == original_index
    assert document.status == "ready"
    assert document.indexing_run_id is None
    assert document.processing_started_at is None
    assert document.error_code == code
    assert document.error_message == message


def test_ready_document_reindexes_without_interrupting_old_index(make_ready_document):
    from apps.knowledge.services.indexing import reindex_document

    document = make_ready_document(
        error_code="previous_reindex_error",
        error_message="Previous safe error.",
    )
    old_indexed_at = document.last_indexed_at
    old_chunks = list(
        document.chunks.order_by("chunk_index").values("id", "content")
    )
    provider = ReindexEmbeddingProvider(document.pk)

    result = reindex_document(document.pk, provider=provider)

    document.refresh_from_db()
    new_chunks = list(document.chunks.order_by("chunk_index"))
    assert result.pk == document.pk
    assert provider.observed_document == {
        "status": "ready",
        "chunk_count": 2,
        "embedding_provider": "old-provider",
        "embedding_model": "old-model",
        "embedding_dimensions": 1024,
        "last_indexed_at": old_indexed_at,
        "indexing_run_id": provider.observed_document["indexing_run_id"],
        "processing_started_at": provider.observed_document[
            "processing_started_at"
        ],
        "error_code": "",
        "error_message": "",
    }
    assert provider.observed_document["indexing_run_id"] is not None
    assert provider.observed_document["processing_started_at"] is not None
    assert provider.observed_chunks == [
        {
            "id": old_chunks[index]["id"],
            "chunk_index": index,
            "content": f"Old indexed content {index}",
            "metadata": {"generation": "old", "position": index},
        }
        for index in range(2)
    ]

    assert document.status == "ready"
    assert document.chunk_count == 2
    assert document.embedding_provider == provider.provider_name
    assert document.embedding_model == provider.model_name
    assert document.embedding_dimensions == provider.dimensions
    assert document.last_indexed_at > old_indexed_at
    assert document.indexing_run_id is None
    assert document.processing_started_at is None
    assert document.error_code == ""
    assert document.error_message == ""

    assert provider.documents == [
        "Updated deployment guidance.",
        "Updated database configuration.",
    ]
    assert [chunk.pk for chunk in new_chunks] != [
        chunk["id"] for chunk in old_chunks
    ]
    assert [chunk.chunk_index for chunk in new_chunks] == [0, 1]
    assert [chunk.content for chunk in new_chunks] == provider.documents
    assert [chunk.section_title for chunk in new_chunks] == [
        "Deployment",
        "Deployment > PostgreSQL",
    ]
    assert [chunk.source_reference for chunk in new_chunks] == [
        "《guide.md》 > Deployment",
        "《guide.md》 > Deployment > PostgreSQL",
    ]
    assert [chunk.metadata for chunk in new_chunks] == [
        {"file_type": "markdown", "section_path": ["Deployment"]},
        {
            "file_type": "markdown",
            "section_path": ["Deployment", "PostgreSQL"],
        },
    ]
    assert [chunk.char_count for chunk in new_chunks] == [
        len("Updated deployment guidance."),
        len("Updated database configuration."),
    ]
    assert list(new_chunks[0].embedding) == pytest.approx(
        provider.embed_query(provider.documents[0])
    )
    assert list(new_chunks[1].embedding) == pytest.approx(
        provider.embed_query(provider.documents[1])
    )


@pytest.mark.parametrize(
    ("status", "state_fields"),
    [
        ("pending", {"last_indexed_at": None}),
        (
            "processing",
            {
                "last_indexed_at": None,
                "indexing_run_id": uuid4(),
                "processing_started_at": timezone.now(),
            },
        ),
        ("failed", {"last_indexed_at": None}),
    ],
)
def test_reindex_rejects_documents_without_a_ready_index(
    make_ready_document,
    status,
    state_fields,
):
    from apps.knowledge.services.indexing import reindex_document

    document = make_ready_document(status=status, **state_fields)
    old_chunk_ids = list(
        document.chunks.order_by("chunk_index").values_list("id", flat=True)
    )

    with pytest.raises(KnowledgeDocumentError) as exc_info:
        reindex_document(
            document.pk,
            provider=DeterministicEmbeddingProvider(),
        )

    document.refresh_from_db()
    assert exc_info.value.code == "invalid_reindex_state"
    assert document.status == status
    assert list(
        document.chunks.order_by("chunk_index").values_list("id", flat=True)
    ) == old_chunk_ids


def test_parser_failure_preserves_the_live_index(make_ready_document):
    from apps.knowledge.services.indexing import reindex_document

    document = make_ready_document(content=b"not a pdf", filename="broken.pdf")
    original_index = live_index_snapshot(document)

    with pytest.raises(KnowledgeDocumentError) as exc_info:
        reindex_document(
            document.pk,
            provider=DeterministicEmbeddingProvider(),
        )

    assert exc_info.value.code == "invalid_file"
    assert_reindex_failure_preserves_live_index(
        document,
        original_index,
        code="invalid_file",
        message="The file is invalid or corrupted.",
    )


def test_chunker_failure_preserves_the_live_index(monkeypatch, make_ready_document):
    from apps.knowledge.services import indexing

    document = make_ready_document()
    original_index = live_index_snapshot(document)

    def fail_chunking(segments):
        raise KnowledgeDocumentError(
            KnowledgeDocumentErrorCode.CHUNK_LIMIT_EXCEEDED
        )

    monkeypatch.setattr(indexing, "chunk_segments", fail_chunking)

    with pytest.raises(KnowledgeDocumentError) as exc_info:
        indexing.reindex_document(
            document.pk,
            provider=DeterministicEmbeddingProvider(),
        )

    assert exc_info.value.code == "chunk_limit_exceeded"
    assert_reindex_failure_preserves_live_index(
        document,
        original_index,
        code="chunk_limit_exceeded",
        message="The document exceeds the allowed chunk count.",
    )


def test_embedding_failure_preserves_the_live_index(make_ready_document):
    from apps.knowledge.services.indexing import reindex_document

    document = make_ready_document()
    original_index = live_index_snapshot(document)

    with pytest.raises(KnowledgeDocumentError) as exc_info:
        reindex_document(document.pk, provider=FailingEmbeddingProvider())

    assert exc_info.value.code == "embedding_provider_error"
    assert_reindex_failure_preserves_live_index(
        document,
        original_index,
        code="embedding_provider_error",
        message="The embedding provider request failed.",
    )


def test_missing_source_file_preserves_the_live_index(make_ready_document):
    from apps.knowledge.services.indexing import reindex_document

    document = make_ready_document()
    original_index = live_index_snapshot(document)
    document.source_file.storage.delete(document.source_file.name)

    with pytest.raises(KnowledgeDocumentError) as exc_info:
        reindex_document(
            document.pk,
            provider=DeterministicEmbeddingProvider(),
        )

    assert exc_info.value.code == "invalid_file"
    assert_reindex_failure_preserves_live_index(
        document,
        original_index,
        code="invalid_file",
        message="The file is invalid or corrupted.",
    )


def test_empty_new_index_preserves_the_live_index(monkeypatch, make_ready_document):
    from apps.knowledge.services import indexing

    document = make_ready_document()
    original_index = live_index_snapshot(document)
    monkeypatch.setattr(indexing, "chunk_segments", lambda segments: [])

    with pytest.raises(KnowledgeDocumentError) as exc_info:
        indexing.reindex_document(
            document.pk,
            provider=DeterministicEmbeddingProvider(),
        )

    assert exc_info.value.code == "no_indexable_content"
    assert_reindex_failure_preserves_live_index(
        document,
        original_index,
        code="no_indexable_content",
        message="The document contains no indexable content.",
    )


def test_unknown_reindex_failure_is_sanitized_and_preserves_live_index(
    make_ready_document,
):
    from apps.knowledge.services.indexing import reindex_document

    document = make_ready_document()
    original_index = live_index_snapshot(document)

    with pytest.raises(KnowledgeDocumentError) as exc_info:
        reindex_document(document.pk, provider=ExplodingEmbeddingProvider())

    assert exc_info.value.code == "reindex_failed"
    assert "secret" not in str(exc_info.value)
    assert "confidential" not in str(exc_info.value)
    assert "C:\\private" not in str(exc_info.value)
    assert_reindex_failure_preserves_live_index(
        document,
        original_index,
        code="reindex_failed",
        message="The document index could not be rebuilt.",
    )


def test_active_reindex_is_rejected_before_stale_timeout(
    monkeypatch,
    settings,
    make_ready_document,
):
    from apps.knowledge.services import indexing

    now = timezone.now()
    current_run_id = uuid4()
    started_at = now - timedelta(
        seconds=settings.KNOWLEDGE_INDEXING_STALE_TIMEOUT_SECONDS,
        microseconds=-1,
    )
    document = make_ready_document(
        indexing_run_id=current_run_id,
        processing_started_at=started_at,
    )
    original_index = live_index_snapshot(document)
    monkeypatch.setattr(indexing.timezone, "now", lambda: now)

    with pytest.raises(KnowledgeDocumentError) as exc_info:
        indexing.reindex_document(
            document.pk,
            provider=DeterministicEmbeddingProvider(),
        )

    document.refresh_from_db()
    assert exc_info.value.code == "indexing_already_in_progress"
    assert document.indexing_run_id == current_run_id
    assert document.processing_started_at == started_at
    assert live_index_snapshot(document) == original_index


@pytest.mark.parametrize("elapsed_seconds", [3600, 3601])
def test_stale_reindex_is_taken_over_at_or_after_timeout(
    monkeypatch,
    settings,
    make_ready_document,
    elapsed_seconds,
):
    from apps.knowledge.services import indexing

    settings.KNOWLEDGE_INDEXING_STALE_TIMEOUT_SECONDS = 3600
    now = timezone.now()
    stale_run_id = uuid4()
    document = make_ready_document(
        indexing_run_id=stale_run_id,
        processing_started_at=now - timedelta(seconds=elapsed_seconds),
    )
    provider = ReindexEmbeddingProvider(document.pk)
    monkeypatch.setattr(indexing.timezone, "now", lambda: now)

    indexing.reindex_document(document.pk, provider=provider)

    assert provider.observed_document["status"] == "ready"
    assert provider.observed_document["indexing_run_id"] != stale_run_id
    assert provider.observed_document["processing_started_at"] == now
    document.refresh_from_db()
    assert document.status == "ready"
    assert document.indexing_run_id is None
    assert document.processing_started_at is None


@pytest.mark.parametrize(
    "provider_class",
    [ConflictingEmbeddingProvider, ConflictingFailingEmbeddingProvider],
)
def test_old_run_conflict_cannot_delete_chunks_or_overwrite_new_run(
    make_ready_document,
    provider_class,
):
    from apps.knowledge.services.indexing import reindex_document

    document = make_ready_document(
        error_code="previous_error",
        error_message="Previous safe message.",
    )
    original_index = live_index_snapshot(document)
    provider = provider_class(document.pk)

    with pytest.raises(KnowledgeDocumentError) as exc_info:
        reindex_document(document.pk, provider=provider)

    document.refresh_from_db()
    assert exc_info.value.code == "indexing_run_conflict"
    assert live_index_snapshot(document) == original_index
    assert document.status == "ready"
    assert document.indexing_run_id == provider.replacement_run_id
    assert document.processing_started_at == provider.replacement_started_at
    assert document.error_code == ""
    assert document.error_message == ""


def test_stale_old_run_cannot_overwrite_a_successful_takeover(make_ready_document):
    from apps.knowledge.services.indexing import reindex_document

    document = make_ready_document()
    stale_provider = StaleTakeoverEmbeddingProvider(document.pk)

    with pytest.raises(KnowledgeDocumentError) as exc_info:
        reindex_document(document.pk, provider=stale_provider)

    document.refresh_from_db()
    assert exc_info.value.code == "indexing_run_conflict"
    assert document.status == "ready"
    assert document.embedding_provider == "takeover-provider"
    assert document.embedding_model == "takeover-model"
    assert document.embedding_dimensions == 1024
    assert document.indexing_run_id is None
    assert document.processing_started_at is None
    assert document.error_code == ""
    assert document.error_message == ""
    assert [
        chunk.content for chunk in document.chunks.order_by("chunk_index")
    ] == [
        "Updated deployment guidance.",
        "Updated database configuration.",
    ]


@pytest.mark.django_db(transaction=True)
def test_atomic_swap_bulk_create_failure_restores_all_old_chunks(
    monkeypatch,
    make_ready_document,
):
    from apps.knowledge.models import KnowledgeChunk
    from apps.knowledge.services.indexing import reindex_document

    document = make_ready_document()
    original_index = live_index_snapshot(document)
    original_bulk_create = QuerySet.bulk_create

    def insert_one_then_fail(queryset, objects, *args, **kwargs):
        if queryset.model is KnowledgeChunk:
            original_bulk_create(queryset, objects[:1], *args, **kwargs)
            raise IntegrityError("simulated replacement bulk insert failure")
        return original_bulk_create(queryset, objects, *args, **kwargs)

    monkeypatch.setattr(QuerySet, "bulk_create", insert_one_then_fail)

    with pytest.raises(KnowledgeDocumentError) as exc_info:
        reindex_document(
            document.pk,
            provider=DeterministicEmbeddingProvider(),
        )

    assert exc_info.value.code == "reindex_failed"
    assert_reindex_failure_preserves_live_index(
        document,
        original_index,
        code="reindex_failed",
        message="The document index could not be rebuilt.",
    )


@pytest.mark.django_db(transaction=True)
def test_atomic_swap_document_update_failure_restores_all_old_chunks(
    monkeypatch,
    make_ready_document,
):
    from apps.knowledge.models import KnowledgeDocument
    from apps.knowledge.services.indexing import reindex_document

    document = make_ready_document()
    original_index = live_index_snapshot(document)
    provider = ReindexEmbeddingProvider(document.pk)
    original_save = KnowledgeDocument.save

    def fail_replacement_snapshot_save(instance, *args, **kwargs):
        if instance.embedding_provider == provider.provider_name:
            raise IntegrityError("simulated replacement document update failure")
        return original_save(instance, *args, **kwargs)

    monkeypatch.setattr(KnowledgeDocument, "save", fail_replacement_snapshot_save)

    with pytest.raises(KnowledgeDocumentError) as exc_info:
        reindex_document(document.pk, provider=provider)

    assert exc_info.value.code == "reindex_failed"
    assert_reindex_failure_preserves_live_index(
        document,
        original_index,
        code="reindex_failed",
        message="The document index could not be rebuilt.",
    )


@pytest.mark.django_db(transaction=True)
def test_reindex_parse_chunk_and_embedding_run_outside_database_transaction(
    monkeypatch,
    make_ready_document,
):
    from apps.knowledge.services import indexing

    document = make_ready_document()
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
            observed_atomic_states.append(
                ("embedding", connection.in_atomic_block)
            )
            return super().embed_documents(texts)

    monkeypatch.setattr(indexing, "parse_document", observe_parse)
    monkeypatch.setattr(indexing, "chunk_segments", observe_chunk)

    indexing.reindex_document(
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
    make_ready_document,
):
    from apps.knowledge.services import indexing

    document = make_ready_document()
    provider = ReplacementEmbeddingProvider()
    monkeypatch.setattr(indexing, "get_embedding_provider", lambda: provider)

    indexing.reindex_document(document.pk)

    document.refresh_from_db()
    assert document.status == "ready"
    assert document.embedding_provider == provider.provider_name
    assert document.embedding_model == provider.model_name
    assert document.embedding_dimensions == provider.dimensions
