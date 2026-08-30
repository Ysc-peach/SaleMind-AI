"""End-to-end acceptance test for the Phase 3 knowledge lifecycle."""

import pytest
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework.test import APIClient

from apps.accounts.models import UserRole
from apps.knowledge.models import KnowledgeDocument
from apps.knowledge.tests.embedding_fakes import DeterministicEmbeddingProvider


pytestmark = pytest.mark.django_db

DOCUMENTS_URL = "/api/knowledge/documents/"
SEARCH_URL = "/api/knowledge/search/"


def test_upload_search_reindex_and_search_new_index(
    settings,
    tmp_path,
    monkeypatch,
):
    from apps.knowledge.services import indexing, search

    settings.MEDIA_ROOT = tmp_path
    provider = DeterministicEmbeddingProvider()
    monkeypatch.setattr(indexing, "get_embedding_provider", lambda: provider)
    monkeypatch.setattr(search, "get_embedding_provider", lambda: provider)

    admin = get_user_model().objects.create_user(
        username="phase3-admin",
        email="phase3-admin@example.com",
        role=UserRole.ADMIN,
        password="StrongPassword123!",
    )
    sales = get_user_model().objects.create_user(
        username="phase3-sales",
        email="phase3-sales@example.com",
        role=UserRole.SALES,
        password="StrongPassword123!",
    )
    client = APIClient()
    old_content = "Legacy private deployment guidance for the enterprise platform."

    client.force_authenticate(user=admin)
    upload_response = client.post(
        DOCUMENTS_URL,
        {
            "title": "Phase 3 integration guide",
            "document_type": "technical",
            "source_file": SimpleUploadedFile(
                "phase3-guide.txt",
                old_content.encode("utf-8"),
                content_type="text/plain",
            ),
        },
        format="multipart",
    )

    assert upload_response.status_code == 201
    assert upload_response.data["status"] == "ready"
    document = KnowledgeDocument.objects.get(pk=upload_response.data["id"])
    old_chunks = list(document.chunks.order_by("chunk_index"))
    assert document.chunk_count == len(old_chunks) == 1
    assert len(old_chunks[0].embedding) == 1024
    assert old_chunks[0].content == old_content
    assert old_chunks[0].source_reference == "《phase3-guide.txt》"

    client.force_authenticate(user=sales)
    first_search = client.post(
        SEARCH_URL,
        {"query": old_content, "top_k": 1},
        format="json",
    )

    assert first_search.status_code == 200
    assert first_search.data["results"][0]["chunk_id"] == old_chunks[0].id
    assert first_search.data["results"][0]["content"] == old_content
    assert first_search.data["results"][0]["source_reference"] == (
        "《phase3-guide.txt》"
    )
    assert first_search.data["results"][0]["similarity"] == pytest.approx(1.0)

    new_content = "Updated sovereign deployment guidance with offline operations."
    with document.source_file.storage.open(document.source_file.name, "wb") as source:
        source.write(new_content.encode("utf-8"))

    client.force_authenticate(user=admin)
    reindex_response = client.post(f"{DOCUMENTS_URL}{document.pk}/reindex/")

    assert reindex_response.status_code == 200
    assert reindex_response.data["status"] == "ready"
    document.refresh_from_db()
    new_chunks = list(document.chunks.order_by("chunk_index"))
    assert document.chunk_count == len(new_chunks) == 1
    assert {chunk.id for chunk in old_chunks}.isdisjoint(
        chunk.id for chunk in new_chunks
    )
    assert new_chunks[0].content == new_content
    assert len(new_chunks[0].embedding) == 1024

    client.force_authenticate(user=sales)
    second_search = client.post(
        SEARCH_URL,
        {"query": new_content, "top_k": 1},
        format="json",
    )

    assert second_search.status_code == 200
    assert second_search.data["results"][0]["chunk_id"] == new_chunks[0].id
    assert second_search.data["results"][0]["content"] == new_content
    assert second_search.data["results"][0]["source_reference"] == (
        "《phase3-guide.txt》"
    )
    assert second_search.data["results"][0]["similarity"] == pytest.approx(1.0)
