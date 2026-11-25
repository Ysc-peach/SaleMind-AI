"""Archiving a document takes it out of retrieval without deleting anything."""

import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.models import UserRole
from apps.knowledge.models import KnowledgeChunk, KnowledgeDocument
from apps.knowledge.services.search import search_knowledge

pytestmark = pytest.mark.django_db

DOCUMENTS_URL = "/api/knowledge/documents/"


def vector(*values):
    return [*values, *([0.0] * (1024 - len(values)))]


class ControlledQueryProvider:
    provider_name = "search-fake"
    model_name = "unit-space"
    dimensions = 1024

    def __init__(self, query_vector):
        self.query_vector = query_vector

    def embed_query(self, text):
        return self.query_vector

    def embed_documents(self, texts):
        raise AssertionError("Search must call embed_query().")


def make_user(role=UserRole.ADMIN, suffix="owner"):
    return get_user_model().objects.create_user(
        username=f"archive-{suffix}",
        email=f"archive-{suffix}@example.com",
        role=role,
        password="StrongPassword123!",
    )


def make_document(owner, *, title="Searchable document", is_active=True):
    return KnowledgeDocument.objects.create(
        title=title,
        document_type=KnowledgeDocument.DocumentType.TECHNICAL,
        source_file="knowledge/documents/test/archive.txt",
        original_filename="archive.txt",
        mime_type="text/plain",
        file_size=100,
        checksum_sha256="b" * 64,
        status=KnowledgeDocument.Status.READY,
        embedding_provider="search-fake",
        embedding_model="unit-space",
        embedding_dimensions=1024,
        last_indexed_at=timezone.now(),
        is_active=is_active,
        created_by=owner,
    )


def make_chunk(document, *, index=0, content="Private deployment is supported."):
    return KnowledgeChunk.objects.create(
        document=document,
        chunk_index=index,
        content=content,
        embedding=vector(1.0, 0.0),
        source_reference="《白皮书》第 1 页",
        metadata={},
        char_count=len(content),
    )


def client_for(user):
    client = APIClient()
    client.force_authenticate(user=user)
    return client


def test_an_archived_document_leaves_retrieval():
    owner = make_user()
    document = make_document(owner)
    make_chunk(document)
    provider = ControlledQueryProvider(vector(1.0, 0.0))
    assert search_knowledge(query="私有化", provider=provider)

    document.is_active = False
    document.save(update_fields=["is_active"])

    # One filter covers the search API, RAG answers and solution generation,
    # because all three read through this function.
    assert search_knowledge(query="私有化", provider=provider) == []


def test_archiving_through_the_api_hides_it_from_the_list():
    admin = make_user()
    document = make_document(admin)
    client = client_for(admin)

    archived = client.post(f"{DOCUMENTS_URL}{document.pk}/archive/")
    default_list = client.get(DOCUMENTS_URL).data
    with_archived = client.get(DOCUMENTS_URL, {"include_inactive": "1"}).data

    assert archived.status_code == 200
    assert archived.data["is_active"] is False
    assert document.pk not in [row["id"] for row in default_list["results"]]
    assert document.pk in [row["id"] for row in with_archived["results"]]


def test_an_archived_document_stays_readable_by_id():
    admin = make_user()
    document = make_document(admin)
    client = client_for(admin)
    client.post(f"{DOCUMENTS_URL}{document.pk}/archive/")

    detail = client.get(f"{DOCUMENTS_URL}{document.pk}/")

    # History has to keep reading: drafts and facts point at this document.
    assert detail.status_code == 200
    assert detail.data["title"] == "Searchable document"
    assert detail.data["is_active"] is False


def test_only_an_administrator_may_archive():
    owner = make_user()
    document = make_document(owner)
    presales = make_user(UserRole.PRESALES, suffix="presales")

    response = client_for(presales).post(f"{DOCUMENTS_URL}{document.pk}/archive/")

    assert response.status_code == 403
    document.refresh_from_db()
    assert document.is_active is True


def test_restoring_brings_the_document_back_into_retrieval():
    admin = make_user()
    document = make_document(admin, is_active=False)
    make_chunk(document)
    client = client_for(admin)
    provider = ControlledQueryProvider(vector(1.0, 0.0))
    assert search_knowledge(query="私有化", provider=provider) == []

    restored = client.post(f"{DOCUMENTS_URL}{document.pk}/restore/")

    assert restored.status_code == 200
    assert restored.data["is_active"] is True
    assert len(search_knowledge(query="私有化", provider=provider)) == 1


def test_archiving_keeps_the_file_and_its_chunks():
    admin = make_user()
    document = make_document(admin)
    chunk = make_chunk(document)

    client_for(admin).post(f"{DOCUMENTS_URL}{document.pk}/archive/")

    # Out of retrieval, not out of the database: the provenance chain that ends
    # at this document must not develop a hole.
    assert KnowledgeChunk.objects.filter(pk=chunk.pk).exists()
    document.refresh_from_db()
    assert document.source_file.name.endswith("archive.txt")


def test_archiving_twice_is_harmless():
    admin = make_user()
    document = make_document(admin)
    client = client_for(admin)

    first = client.post(f"{DOCUMENTS_URL}{document.pk}/archive/")
    second = client.post(f"{DOCUMENTS_URL}{document.pk}/archive/")

    assert first.status_code == 200
    assert second.status_code == 200
    document.refresh_from_db()
    assert document.is_active is False
