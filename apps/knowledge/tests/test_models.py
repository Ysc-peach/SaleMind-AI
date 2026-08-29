"""Persistence tests for enterprise knowledge documents and chunks."""

from uuid import uuid4

import pytest
from django.apps import apps
from django.db import DataError, IntegrityError, transaction
from django.db.models.deletion import ProtectedError
from django.utils import timezone


pytestmark = pytest.mark.django_db


@pytest.fixture
def creator(django_user_model):
    return django_user_model.objects.create_user(
        username="knowledge-admin",
        email="knowledge-admin@example.com",
        role="admin",
        password="StrongPassword123!",
    )


@pytest.fixture
def make_document(creator):
    document_model = apps.get_model("knowledge", "KnowledgeDocument")
    sequence = 0

    def factory(**overrides):
        nonlocal sequence
        sequence += 1
        values = {
            "title": f"Knowledge document {sequence}",
            "document_type": "technical",
            "source_file": f"knowledge/documents/document-{sequence}.md",
            "original_filename": f"document-{sequence}.md",
            "mime_type": "text/markdown",
            "file_size": 128,
            "checksum_sha256": f"{sequence:064x}",
            "status": "pending",
            "created_by": creator,
        }
        values.update(overrides)
        return document_model.objects.create(**values)

    return factory


@pytest.fixture
def make_chunk(make_document):
    chunk_model = apps.get_model("knowledge", "KnowledgeChunk")
    document = make_document()
    sequence = 0

    def factory(**overrides):
        nonlocal sequence
        values = {
            "document": document,
            "chunk_index": sequence,
            "content": f"Chunk content {sequence}",
            "embedding": [0.0] * 1024,
            "page_number": None,
            "section_title": "Overview",
            "source_reference": "Overview",
            "metadata": {"source": "test"},
            "char_count": 15,
        }
        sequence += 1
        values.update(overrides)
        return chunk_model.objects.create(**values)

    return factory


def test_document_type_exposes_only_supported_values():
    document_model = apps.get_model("knowledge", "KnowledgeDocument")

    assert set(document_model.DocumentType.values) == {
        "product",
        "technical",
        "case",
        "faq",
        "sales",
    }


def test_document_status_exposes_only_indexing_lifecycle_values():
    document_model = apps.get_model("knowledge", "KnowledgeDocument")

    assert set(document_model.Status.values) == {
        "pending",
        "processing",
        "ready",
        "failed",
    }


def test_database_rejects_unknown_document_type(make_document):
    with pytest.raises(IntegrityError), transaction.atomic():
        make_document(document_type="unknown")


def test_database_rejects_unknown_document_status(make_document):
    with pytest.raises(IntegrityError), transaction.atomic():
        make_document(status="unknown")


def test_database_rejects_negative_chunk_count(make_document):
    with pytest.raises(IntegrityError), transaction.atomic():
        make_document(chunk_count=-1)


def test_document_creator_is_protected_from_deletion(make_document, creator):
    make_document()

    with pytest.raises(ProtectedError):
        creator.delete()


def test_deleting_document_cascades_to_its_chunks(make_chunk):
    chunk = make_chunk()
    chunk_model = type(chunk)

    chunk.document.delete()

    assert not chunk_model.objects.filter(pk=chunk.pk).exists()


def test_document_chunk_index_is_unique_per_document(make_chunk):
    first_chunk = make_chunk(chunk_index=0)

    with pytest.raises(IntegrityError), transaction.atomic():
        make_chunk(document=first_chunk.document, chunk_index=0)


def test_database_rejects_negative_chunk_index(make_chunk):
    with pytest.raises(IntegrityError), transaction.atomic():
        make_chunk(chunk_index=-1)


def test_database_rejects_page_number_zero(make_chunk):
    with pytest.raises(IntegrityError), transaction.atomic():
        make_chunk(page_number=0)


def test_page_number_can_be_null(make_chunk):
    chunk = make_chunk(page_number=None)

    assert chunk.page_number is None


@pytest.mark.parametrize(
    ("indexing_run_id", "processing_started_at"),
    [
        (uuid4(), None),
        (None, timezone.now()),
    ],
)
def test_indexing_run_fields_must_be_set_or_cleared_together(
    make_document,
    indexing_run_id,
    processing_started_at,
):
    with pytest.raises(IntegrityError), transaction.atomic():
        make_document(
            indexing_run_id=indexing_run_id,
            processing_started_at=processing_started_at,
        )


def test_indexing_run_fields_can_be_set_together(make_document):
    run_id = uuid4()
    started_at = timezone.now()

    document = make_document(
        indexing_run_id=run_id,
        processing_started_at=started_at,
    )

    assert document.indexing_run_id == run_id
    assert document.processing_started_at == started_at


def test_ready_document_requires_last_indexed_timestamp(make_document):
    with pytest.raises(IntegrityError), transaction.atomic():
        make_document(status="ready", last_indexed_at=None)


def test_ready_document_accepts_last_indexed_timestamp(make_document):
    indexed_at = timezone.now()

    document = make_document(status="ready", last_indexed_at=indexed_at)

    assert document.last_indexed_at == indexed_at


def test_embedding_accepts_and_returns_exactly_1024_dimensions(make_chunk):
    embedding = [0.25] * 1024

    chunk = make_chunk(embedding=embedding)
    chunk.refresh_from_db()

    assert list(chunk.embedding) == pytest.approx(embedding)


def test_embedding_rejects_wrong_dimension(make_chunk):
    with pytest.raises(DataError), transaction.atomic():
        make_chunk(embedding=[0.25] * 3)
