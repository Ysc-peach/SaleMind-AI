"""Admin-only Knowledge Document management API contracts."""

from datetime import timedelta
from hashlib import sha256
from uuid import uuid4

import pytest
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.models import UserRole
from apps.knowledge.exceptions import (
    KnowledgeDocumentError,
    KnowledgeDocumentErrorCode,
)
from apps.knowledge.tests.embedding_fakes import DeterministicEmbeddingProvider
from apps.knowledge.tests.parser_fixtures import build_pdf


pytestmark = pytest.mark.django_db

DOCUMENTS_URL = "/api/knowledge/documents/"
DOCUMENT_READ_FIELDS = {
    "id",
    "title",
    "document_type",
    "original_filename",
    "mime_type",
    "file_size",
    "status",
    "error_code",
    "error_message",
    "embedding_provider",
    "embedding_model",
    "embedding_dimensions",
    "chunk_count",
    "is_indexing",
    "processing_started_at",
    "last_indexed_at",
    "created_at",
    "updated_at",
}


@pytest.fixture(autouse=True)
def knowledge_api_environment(settings, tmp_path, monkeypatch):
    from apps.knowledge.services import indexing

    settings.MEDIA_ROOT = tmp_path
    monkeypatch.setattr(
        indexing,
        "get_embedding_provider",
        lambda: DeterministicEmbeddingProvider(),
    )


@pytest.fixture
def api_client():
    return APIClient()


@pytest.fixture
def user_factory():
    sequence = 0

    def factory(
        role=UserRole.ADMIN,
        *,
        is_staff=False,
        is_superuser=False,
    ):
        nonlocal sequence
        sequence += 1
        return get_user_model().objects.create_user(
            username=f"knowledge-user-{sequence}",
            email=f"knowledge-user-{sequence}@example.com",
            role=role,
            password="StrongPassword123!",
            is_staff=is_staff,
            is_superuser=is_superuser,
        )

    return factory


@pytest.fixture
def document_factory(user_factory):
    from apps.knowledge.models import KnowledgeDocument

    sequence = 0

    def factory(
        *,
        created_by=None,
        status="ready",
        title=None,
        **overrides,
    ):
        nonlocal sequence
        sequence += 1
        created_by = created_by or user_factory(UserRole.ADMIN)
        values = {
            "title": title or f"Knowledge document {sequence}",
            "document_type": "technical",
            "source_file": f"knowledge/documents/test/document-{sequence}.txt",
            "original_filename": f"document-{sequence}.txt",
            "mime_type": "text/plain",
            "file_size": 128,
            "checksum_sha256": f"{sequence:064x}",
            "status": status,
            "embedding_provider": "fake" if status == "ready" else "",
            "embedding_model": "sha256-test" if status == "ready" else "",
            "embedding_dimensions": 1024 if status == "ready" else None,
            "last_indexed_at": timezone.now() if status == "ready" else None,
            "created_by": created_by,
        }
        values.update(overrides)
        return KnowledgeDocument.objects.create(**values)

    return factory


@pytest.mark.parametrize(
    ("filename", "content", "client_mime_type", "expected_mime_type", "chunk_count"),
    [
        (
            "guide.txt",
            b"PostgreSQL deployment guidance for enterprise knowledge systems.",
            "application/octet-stream",
            "text/plain",
            1,
        ),
        (
            "guide.md",
            b"# Deployment\n\nPostgreSQL deployment guidance.",
            "application/octet-stream",
            "text/markdown",
            1,
        ),
        (
            "guide.pdf",
            build_pdf(["First page guidance", "Second page details"]),
            "application/octet-stream",
            "application/pdf",
            2,
        ),
    ],
)
def test_admin_uploads_supported_document_and_receives_ready_resource(
    api_client,
    user_factory,
    filename,
    content,
    client_mime_type,
    expected_mime_type,
    chunk_count,
):
    from apps.knowledge.models import KnowledgeDocument

    actor = user_factory(UserRole.ADMIN)
    api_client.force_authenticate(user=actor)

    response = api_client.post(
        DOCUMENTS_URL,
        {
            "title": "Deployment guide",
            "document_type": "technical",
            "source_file": SimpleUploadedFile(
                filename,
                content,
                content_type=client_mime_type,
            ),
        },
        format="multipart",
    )

    assert response.status_code == 201
    assert set(response.data) == DOCUMENT_READ_FIELDS
    document = KnowledgeDocument.objects.get(pk=response.data["id"])
    assert document.created_by_id == actor.id
    assert document.original_filename == filename
    assert document.mime_type == expected_mime_type
    assert document.file_size == len(content)
    assert document.checksum_sha256 == sha256(content).hexdigest()
    assert document.status == "ready"
    assert document.chunk_count == chunk_count
    assert document.chunks.count() == chunk_count
    assert document.embedding_provider == "fake"
    assert document.embedding_model == "sha256-test"
    assert document.embedding_dimensions == 1024
    assert document.last_indexed_at is not None
    with document.source_file.open("rb") as saved_file:
        assert saved_file.read() == content
    assert response.data["status"] == "ready"
    assert response.data["chunk_count"] == chunk_count
    assert response.data["is_indexing"] is False
    assert "source_file" not in response.data
    assert "checksum_sha256" not in response.data
    assert "indexing_run_id" not in response.data
    assert "chunks" not in response.data


def test_upload_calls_the_initial_indexing_service(
    monkeypatch,
    api_client,
    user_factory,
):
    from apps.knowledge.services import indexing

    actor = user_factory(UserRole.ADMIN)
    api_client.force_authenticate(user=actor)
    original_index_document = indexing.index_document
    indexed_document_ids = []

    def observe_indexing(document_id, **kwargs):
        indexed_document_ids.append(document_id)
        return original_index_document(document_id, **kwargs)

    monkeypatch.setattr(indexing, "index_document", observe_indexing)

    response = api_client.post(
        DOCUMENTS_URL,
        {
            "title": "Operations guide",
            "document_type": "technical",
            "source_file": SimpleUploadedFile(
                "operations.txt",
                b"Operational instructions for the knowledge platform.",
                content_type="text/plain",
            ),
        },
        format="multipart",
    )

    assert response.status_code == 201
    assert indexed_document_ids == [response.data["id"]]


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("original_filename", "forged.txt"),
        ("mime_type", "application/pdf"),
        ("file_size", 1),
        ("checksum_sha256", "0" * 64),
        ("status", "ready"),
        ("error_code", "forged"),
        ("error_message", "forged"),
        ("embedding_provider", "forged"),
        ("embedding_model", "forged"),
        ("embedding_dimensions", 3),
        ("chunk_count", 999),
        ("indexing_run_id", str(uuid4())),
        ("processing_started_at", timezone.now().isoformat()),
        ("last_indexed_at", timezone.now().isoformat()),
        ("created_by", 999),
        ("created_at", timezone.now().isoformat()),
        ("updated_at", timezone.now().isoformat()),
    ],
)
def test_upload_rejects_each_server_controlled_field(
    api_client,
    user_factory,
    field,
    value,
):
    from apps.knowledge.models import KnowledgeDocument

    actor = user_factory(UserRole.ADMIN)
    api_client.force_authenticate(user=actor)

    response = api_client.post(
        DOCUMENTS_URL,
        {
            "title": "Controlled fields test",
            "document_type": "technical",
            "source_file": SimpleUploadedFile(
                "guide.txt",
                b"Valid knowledge document content for server control tests.",
                content_type="text/plain",
            ),
            field: value,
        },
        format="multipart",
    )

    assert response.status_code == 400
    assert field in response.data
    assert KnowledgeDocument.objects.count() == 0


@pytest.mark.parametrize(
    ("filename", "content", "expected_code"),
    [
        ("manual.pdf", b"not a PDF", "invalid_file"),
        ("manual.txt", b"valid prefix\x00binary payload", "invalid_file"),
        ("manual.md", b"\xff\xfe\xfa", "invalid_text_encoding"),
        ("manual.docx", b"plain text but unsupported suffix", "unsupported_file_type"),
    ],
)
def test_invalid_upload_is_rejected_before_document_creation(
    api_client,
    user_factory,
    filename,
    content,
    expected_code,
):
    from apps.knowledge.models import KnowledgeChunk, KnowledgeDocument

    actor = user_factory(UserRole.ADMIN)
    api_client.force_authenticate(user=actor)

    response = api_client.post(
        DOCUMENTS_URL,
        {
            "title": "Invalid upload",
            "document_type": "technical",
            "source_file": SimpleUploadedFile(
                filename,
                content,
                content_type="application/octet-stream",
            ),
        },
        format="multipart",
    )

    assert response.status_code == 400
    assert response.data == {
        "code": expected_code,
        "message": response.data["message"],
    }
    assert response.data["message"]
    assert KnowledgeDocument.objects.count() == 0
    assert KnowledgeChunk.objects.count() == 0


def test_oversized_upload_is_rejected_before_document_creation(
    api_client,
    user_factory,
    settings,
):
    from apps.knowledge.models import KnowledgeDocument

    actor = user_factory(UserRole.ADMIN)
    api_client.force_authenticate(user=actor)
    oversized_content = b"x" * (settings.KNOWLEDGE_MAX_FILE_SIZE_BYTES + 1)

    response = api_client.post(
        DOCUMENTS_URL,
        {
            "title": "Oversized upload",
            "document_type": "technical",
            "source_file": SimpleUploadedFile(
                "oversized.txt",
                oversized_content,
                content_type="text/plain",
            ),
        },
        format="multipart",
    )

    assert response.status_code == 400
    assert response.data["code"] == "file_too_large"
    assert KnowledgeDocument.objects.count() == 0


def test_upload_filename_is_reduced_to_a_safe_display_basename(
    api_client,
    user_factory,
):
    from apps.knowledge.models import KnowledgeDocument

    actor = user_factory(UserRole.ADMIN)
    api_client.force_authenticate(user=actor)

    response = api_client.post(
        DOCUMENTS_URL,
        {
            "title": "Safe filename",
            "document_type": "technical",
            "source_file": SimpleUploadedFile(
                "../../private/guide.txt",
                b"Safe enterprise knowledge document content.",
                content_type="text/plain",
            ),
        },
        format="multipart",
    )

    assert response.status_code == 201
    document = KnowledgeDocument.objects.get(pk=response.data["id"])
    assert document.original_filename == "guide.txt"
    assert ".." not in document.source_file.name
    assert document.source_file.name.startswith("knowledge/documents/")


class FailingIndexEmbeddingProvider(DeterministicEmbeddingProvider):
    def embed_documents(self, texts):
        raise KnowledgeDocumentError(
            KnowledgeDocumentErrorCode.EMBEDDING_PROVIDER_ERROR
        )


class ReplacementAPIEmbeddingProvider(DeterministicEmbeddingProvider):
    provider_name = "replacement-api-provider"
    model_name = "replacement-api-model"


class ConflictingAPIEmbeddingProvider(DeterministicEmbeddingProvider):
    def __init__(self, document_id):
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


def test_created_document_is_returned_as_failed_when_initial_indexing_fails(
    monkeypatch,
    api_client,
    user_factory,
):
    from apps.knowledge.models import KnowledgeDocument
    from apps.knowledge.services import indexing

    actor = user_factory(UserRole.ADMIN)
    api_client.force_authenticate(user=actor)
    monkeypatch.setattr(
        indexing,
        "get_embedding_provider",
        lambda: FailingIndexEmbeddingProvider(),
    )

    response = api_client.post(
        DOCUMENTS_URL,
        {
            "title": "Provider failure",
            "document_type": "technical",
            "source_file": SimpleUploadedFile(
                "failure.txt",
                b"Content that passes upload validation before provider failure.",
                content_type="text/plain",
            ),
        },
        format="multipart",
    )

    assert response.status_code == 201
    document = KnowledgeDocument.objects.get(pk=response.data["id"])
    assert document.status == "failed"
    assert document.chunk_count == 0
    assert document.chunks.count() == 0
    assert document.error_code == "embedding_provider_error"
    assert document.error_message == "The embedding provider request failed."
    assert response.data["status"] == "failed"
    assert response.data["error_code"] == "embedding_provider_error"
    assert response.data["error_message"] == (
        "The embedding provider request failed."
    )


def test_initial_index_claim_conflict_is_not_misreported_as_created_failure(
    monkeypatch,
    api_client,
    user_factory,
):
    from apps.knowledge.models import KnowledgeDocument
    from apps.knowledge.services import indexing

    actor = user_factory(UserRole.ADMIN)
    api_client.force_authenticate(user=actor)

    def reject_claim(document_id):
        raise KnowledgeDocumentError(
            KnowledgeDocumentErrorCode.INVALID_INDEXING_STATE
        )

    monkeypatch.setattr(indexing, "index_document", reject_claim)

    response = api_client.post(
        DOCUMENTS_URL,
        {
            "title": "Claim conflict",
            "document_type": "technical",
            "source_file": SimpleUploadedFile(
                "claim.txt",
                b"Valid upload whose indexing claim is simulated to conflict.",
                content_type="text/plain",
            ),
        },
        format="multipart",
    )

    assert response.status_code == 409
    assert response.data == {
        "code": "invalid_indexing_state",
        "message": "The document is not pending initial indexing.",
    }
    document = KnowledgeDocument.objects.get()
    assert document.status == "pending"
    assert document.chunks.count() == 0


def test_admin_lists_documents_with_safe_fields(
    api_client,
    user_factory,
    document_factory,
):
    actor = user_factory(UserRole.ADMIN)
    document_factory(created_by=actor, title="First guide")
    latest = document_factory(created_by=actor, title="Latest guide")
    api_client.force_authenticate(user=actor)

    response = api_client.get(DOCUMENTS_URL)

    assert response.status_code == 200
    assert set(response.data) == {"count", "next", "previous", "results"}
    assert response.data["count"] == 2
    assert response.data["results"][0]["id"] == latest.id
    assert all(
        set(document_data) == DOCUMENT_READ_FIELDS
        for document_data in response.data["results"]
    )


def test_document_list_uses_twenty_item_pages(
    api_client,
    user_factory,
    document_factory,
):
    actor = user_factory(UserRole.ADMIN)
    for index in range(21):
        document_factory(created_by=actor, title=f"Guide {index:02d}")
    api_client.force_authenticate(user=actor)

    response = api_client.get(DOCUMENTS_URL)

    assert response.status_code == 200
    assert response.data["count"] == 21
    assert len(response.data["results"]) == 20
    assert response.data["next"] is not None


def test_document_list_has_stable_updated_at_then_id_descending_order(
    api_client,
    user_factory,
    document_factory,
):
    from apps.knowledge.models import KnowledgeDocument

    actor = user_factory(UserRole.ADMIN)
    lower_id = document_factory(created_by=actor, title="Lower ID")
    higher_id = document_factory(created_by=actor, title="Higher ID")
    older = document_factory(created_by=actor, title="Older")
    same_updated_at = timezone.now()
    KnowledgeDocument.objects.filter(pk__in=[lower_id.pk, higher_id.pk]).update(
        updated_at=same_updated_at
    )
    KnowledgeDocument.objects.filter(pk=older.pk).update(
        updated_at=same_updated_at - timedelta(seconds=1)
    )
    api_client.force_authenticate(user=actor)

    response = api_client.get(DOCUMENTS_URL)

    assert response.status_code == 200
    assert [item["id"] for item in response.data["results"]] == [
        higher_id.id,
        lower_id.id,
        older.id,
    ]


def test_admin_retrieves_safe_document_metadata(
    api_client,
    user_factory,
    document_factory,
):
    actor = user_factory(UserRole.ADMIN)
    document = document_factory(
        created_by=actor,
        title="Retrievable guide",
        error_code="previous_safe_error",
        error_message="Previous safe message.",
    )
    api_client.force_authenticate(user=actor)

    response = api_client.get(f"{DOCUMENTS_URL}{document.pk}/")

    assert response.status_code == 200
    assert set(response.data) == DOCUMENT_READ_FIELDS
    assert response.data["id"] == document.id
    assert response.data["title"] == "Retrievable guide"
    assert response.data["error_code"] == "previous_safe_error"
    assert response.data["error_message"] == "Previous safe message."
    assert "source_file" not in response.data
    assert "indexing_run_id" not in response.data
    assert "checksum_sha256" not in response.data
    assert "chunks" not in response.data
    assert "embedding" not in response.data


@pytest.mark.parametrize(
    ("status", "last_indexed_at"),
    [("processing", None), ("ready", timezone.now())],
)
def test_is_indexing_is_true_for_initial_and_reindex_runs(
    api_client,
    user_factory,
    document_factory,
    status,
    last_indexed_at,
):
    actor = user_factory(UserRole.ADMIN)
    document = document_factory(
        created_by=actor,
        status=status,
        last_indexed_at=last_indexed_at,
        indexing_run_id=uuid4(),
        processing_started_at=timezone.now(),
    )
    api_client.force_authenticate(user=actor)

    response = api_client.get(f"{DOCUMENTS_URL}{document.pk}/")

    assert response.status_code == 200
    assert response.data["status"] == status
    assert response.data["is_indexing"] is True
    assert "indexing_run_id" not in response.data


def test_is_indexing_is_false_when_run_markers_are_clear(
    api_client,
    user_factory,
    document_factory,
):
    actor = user_factory(UserRole.ADMIN)
    document = document_factory(created_by=actor)
    api_client.force_authenticate(user=actor)

    response = api_client.get(f"{DOCUMENTS_URL}{document.pk}/")

    assert response.status_code == 200
    assert response.data["is_indexing"] is False


def test_admin_reindexes_a_ready_document_through_the_service(
    monkeypatch,
    api_client,
    user_factory,
):
    from apps.knowledge.models import KnowledgeDocument
    from apps.knowledge.services import indexing

    actor = user_factory(UserRole.ADMIN)
    api_client.force_authenticate(user=actor)
    create_response = api_client.post(
        DOCUMENTS_URL,
        {
            "title": "Reindex guide",
            "document_type": "technical",
            "source_file": SimpleUploadedFile(
                "reindex.txt",
                b"Content that remains available while the index is rebuilt.",
                content_type="text/plain",
            ),
        },
        format="multipart",
    )
    document = KnowledgeDocument.objects.get(pk=create_response.data["id"])
    old_chunk_ids = list(document.chunks.values_list("id", flat=True))
    old_indexed_at = document.last_indexed_at
    replacement_provider = ReplacementAPIEmbeddingProvider()
    monkeypatch.setattr(
        indexing,
        "get_embedding_provider",
        lambda: replacement_provider,
    )

    response = api_client.post(f"{DOCUMENTS_URL}{document.pk}/reindex/")

    assert response.status_code == 200
    assert set(response.data) == DOCUMENT_READ_FIELDS
    document.refresh_from_db()
    assert document.status == "ready"
    assert document.embedding_provider == replacement_provider.provider_name
    assert document.embedding_model == replacement_provider.model_name
    assert document.embedding_dimensions == 1024
    assert document.last_indexed_at > old_indexed_at
    assert document.indexing_run_id is None
    assert document.processing_started_at is None
    assert set(document.chunks.values_list("id", flat=True)).isdisjoint(
        old_chunk_ids
    )
    assert response.data["embedding_provider"] == "replacement-api-provider"
    assert response.data["embedding_model"] == "replacement-api-model"
    assert response.data["is_indexing"] is False


def test_active_reindex_request_returns_stable_conflict(
    api_client,
    user_factory,
    document_factory,
):
    actor = user_factory(UserRole.ADMIN)
    current_run_id = uuid4()
    started_at = timezone.now()
    document = document_factory(
        created_by=actor,
        indexing_run_id=current_run_id,
        processing_started_at=started_at,
    )
    api_client.force_authenticate(user=actor)

    response = api_client.post(f"{DOCUMENTS_URL}{document.pk}/reindex/")

    assert response.status_code == 409
    assert response.data == {
        "code": "indexing_already_in_progress",
        "message": "The document is already being indexed.",
    }
    document.refresh_from_db()
    assert document.status == "ready"
    assert document.indexing_run_id == current_run_id
    assert document.processing_started_at == started_at


@pytest.mark.parametrize(
    ("status", "state_fields"),
    [
        ("pending", {}),
        (
            "processing",
            {
                "indexing_run_id": uuid4(),
                "processing_started_at": timezone.now(),
            },
        ),
        ("failed", {}),
    ],
)
def test_invalid_reindex_state_returns_stable_conflict(
    api_client,
    user_factory,
    document_factory,
    status,
    state_fields,
):
    actor = user_factory(UserRole.ADMIN)
    document = document_factory(
        created_by=actor,
        status=status,
        **state_fields,
    )
    api_client.force_authenticate(user=actor)

    response = api_client.post(f"{DOCUMENTS_URL}{document.pk}/reindex/")

    assert response.status_code == 409
    assert response.data == {
        "code": "invalid_reindex_state",
        "message": "The document does not have a ready index to rebuild.",
    }


def test_reindex_processing_failure_returns_422_and_preserves_live_index(
    monkeypatch,
    api_client,
    user_factory,
):
    from apps.knowledge.models import KnowledgeDocument
    from apps.knowledge.services import indexing

    actor = user_factory(UserRole.ADMIN)
    api_client.force_authenticate(user=actor)
    create_response = api_client.post(
        DOCUMENTS_URL,
        {
            "title": "Reindex failure guide",
            "document_type": "technical",
            "source_file": SimpleUploadedFile(
                "failure.txt",
                b"The existing index must survive a provider failure.",
                content_type="text/plain",
            ),
        },
        format="multipart",
    )
    document = KnowledgeDocument.objects.get(pk=create_response.data["id"])
    old_chunk_ids = list(document.chunks.values_list("id", flat=True))
    old_indexed_at = document.last_indexed_at
    old_provider = document.embedding_provider
    monkeypatch.setattr(
        indexing,
        "get_embedding_provider",
        lambda: FailingIndexEmbeddingProvider(),
    )

    response = api_client.post(f"{DOCUMENTS_URL}{document.pk}/reindex/")

    assert response.status_code == 422
    assert response.data == {
        "code": "embedding_provider_error",
        "message": "The embedding provider request failed.",
    }
    document.refresh_from_db()
    assert document.status == "ready"
    assert list(document.chunks.values_list("id", flat=True)) == old_chunk_ids
    assert document.last_indexed_at == old_indexed_at
    assert document.embedding_provider == old_provider
    assert document.indexing_run_id is None
    assert document.processing_started_at is None
    assert document.error_code == "embedding_provider_error"
    assert document.error_message == "The embedding provider request failed."


def test_reindex_run_conflict_returns_409_without_overwriting_new_run(
    monkeypatch,
    api_client,
    user_factory,
):
    from apps.knowledge.models import KnowledgeDocument
    from apps.knowledge.services import indexing

    actor = user_factory(UserRole.ADMIN)
    api_client.force_authenticate(user=actor)
    create_response = api_client.post(
        DOCUMENTS_URL,
        {
            "title": "Run conflict guide",
            "document_type": "technical",
            "source_file": SimpleUploadedFile(
                "conflict.txt",
                b"The current live chunks must survive a run conflict.",
                content_type="text/plain",
            ),
        },
        format="multipart",
    )
    document = KnowledgeDocument.objects.get(pk=create_response.data["id"])
    old_chunk_ids = list(document.chunks.values_list("id", flat=True))
    provider = ConflictingAPIEmbeddingProvider(document.pk)
    monkeypatch.setattr(
        indexing,
        "get_embedding_provider",
        lambda: provider,
    )

    response = api_client.post(f"{DOCUMENTS_URL}{document.pk}/reindex/")

    assert response.status_code == 409
    assert response.data == {
        "code": "indexing_run_conflict",
        "message": "The indexing run is no longer current.",
    }
    document.refresh_from_db()
    assert document.status == "ready"
    assert document.indexing_run_id == provider.replacement_run_id
    assert document.processing_started_at == provider.replacement_started_at
    assert list(document.chunks.values_list("id", flat=True)) == old_chunk_ids


def request_document_endpoint(api_client, method, url):
    if method == "post" and url == DOCUMENTS_URL:
        return api_client.post(
            url,
            {
                "title": "Permission upload",
                "document_type": "technical",
                "source_file": SimpleUploadedFile(
                    "permission.txt",
                    b"Valid content that must not bypass business permissions.",
                    content_type="text/plain",
                ),
            },
            format="multipart",
        )
    return getattr(api_client, method)(url)


@pytest.mark.parametrize("role", [UserRole.SALES, UserRole.PRESALES])
@pytest.mark.parametrize(
    ("method", "url_kind"),
    [
        ("get", "collection"),
        ("post", "collection"),
        ("get", "detail"),
        ("post", "reindex"),
    ],
)
def test_non_admin_business_roles_cannot_access_document_management(
    api_client,
    user_factory,
    document_factory,
    role,
    method,
    url_kind,
):
    owner = user_factory(UserRole.ADMIN)
    document = document_factory(created_by=owner)
    actor = user_factory(role)
    api_client.force_authenticate(user=actor)
    urls = {
        "collection": DOCUMENTS_URL,
        "detail": f"{DOCUMENTS_URL}{document.pk}/",
        "reindex": f"{DOCUMENTS_URL}{document.pk}/reindex/",
    }

    response = request_document_endpoint(api_client, method, urls[url_kind])

    assert response.status_code == 403


@pytest.mark.parametrize(
    ("method", "url_kind"),
    [
        ("get", "collection"),
        ("post", "collection"),
        ("get", "detail"),
        ("post", "reindex"),
    ],
)
def test_unauthenticated_requests_cannot_access_document_management(
    api_client,
    user_factory,
    document_factory,
    method,
    url_kind,
):
    owner = user_factory(UserRole.ADMIN)
    document = document_factory(created_by=owner)
    urls = {
        "collection": DOCUMENTS_URL,
        "detail": f"{DOCUMENTS_URL}{document.pk}/",
        "reindex": f"{DOCUMENTS_URL}{document.pk}/reindex/",
    }

    response = request_document_endpoint(api_client, method, urls[url_kind])

    assert response.status_code == 401


@pytest.mark.parametrize(
    "technical_flags",
    [
        {"is_staff": True, "is_superuser": False},
        {"is_staff": True, "is_superuser": True},
    ],
)
@pytest.mark.parametrize(
    ("method", "url_kind"),
    [
        ("get", "collection"),
        ("post", "collection"),
        ("get", "detail"),
        ("post", "reindex"),
    ],
)
def test_django_technical_flags_do_not_bypass_business_admin_role(
    api_client,
    user_factory,
    document_factory,
    technical_flags,
    method,
    url_kind,
):
    owner = user_factory(UserRole.ADMIN)
    document = document_factory(created_by=owner)
    actor = user_factory(UserRole.SALES, **technical_flags)
    api_client.force_authenticate(user=actor)
    urls = {
        "collection": DOCUMENTS_URL,
        "detail": f"{DOCUMENTS_URL}{document.pk}/",
        "reindex": f"{DOCUMENTS_URL}{document.pk}/reindex/",
    }

    response = request_document_endpoint(api_client, method, urls[url_kind])

    assert response.status_code == 403


@pytest.mark.parametrize("method", ["put", "patch", "delete"])
def test_document_mutation_methods_are_not_exposed(
    api_client,
    user_factory,
    document_factory,
    method,
):
    actor = user_factory(UserRole.ADMIN)
    document = document_factory(created_by=actor)
    api_client.force_authenticate(user=actor)

    response = getattr(api_client, method)(
        f"{DOCUMENTS_URL}{document.pk}/",
        {"title": "Forbidden mutation"},
        format="json",
    )

    assert response.status_code == 405


def test_oversized_request_is_rejected_before_parsing(
    api_client, user_factory, settings, monkeypatch,
):
    from apps.knowledge.api import views

    settings.KNOWLEDGE_MAX_FILE_SIZE_BYTES = 16
    monkeypatch.setattr(views, "_MAX_MULTIPART_OVERHEAD_BYTES", 0)
    api_client.force_authenticate(user=user_factory(UserRole.ADMIN))

    response = api_client.post(
        DOCUMENTS_URL,
        {
            "title": "Oversized document",
            "document_type": "technical",
            "file": SimpleUploadedFile(
                "big.txt", b"x" * 4096, content_type="text/plain",
            ),
        },
        format="multipart",
    )

    assert response.status_code == 413
    assert response.json()["code"] == "payload_too_large"


def test_body_limit_ignores_missing_or_invalid_content_length():
    from types import SimpleNamespace

    from apps.knowledge.api.views import enforce_body_limit

    enforce_body_limit(SimpleNamespace(META={}))
    enforce_body_limit(SimpleNamespace(META={"CONTENT_LENGTH": ""}))
    enforce_body_limit(SimpleNamespace(META={"CONTENT_LENGTH": "not-a-number"}))


def test_knowledge_admin_registers_documents_but_not_mutable_chunks():
    from django.contrib import admin

    from apps.knowledge.models import KnowledgeChunk, KnowledgeDocument

    assert admin.site.is_registered(KnowledgeDocument)
    assert not admin.site.is_registered(KnowledgeChunk)
