"""Persistence invariants for approved enterprise grounding facts."""

from uuid import uuid4

import pytest
from django.db import IntegrityError, transaction
from django.db.models.deletion import ProtectedError
from django.utils import timezone


pytestmark = pytest.mark.django_db


@pytest.fixture
def actor(django_user_model):
    return django_user_model.objects.create_user(
        username="fact-admin",
        email="fact-admin@example.com",
        role="admin",
        password="StrongPassword123!",
    )


@pytest.fixture
def document(actor):
    from apps.knowledge.models import KnowledgeDocument

    return KnowledgeDocument.objects.create(
        title="Grounding source",
        document_type="technical",
        source_file="knowledge/documents/grounding.md",
        original_filename="grounding.md",
        mime_type="text/markdown",
        file_size=128,
        checksum_sha256="a" * 64,
        status="ready",
        chunk_count=1,
        embedding_provider="fake",
        embedding_model="fake-model",
        embedding_dimensions=1024,
        last_indexed_at=timezone.now(),
        last_index_run_id=uuid4(),
        created_by=actor,
    )


@pytest.fixture
def make_fact(document):
    from apps.knowledge.models import EnterpriseGroundingFact

    sequence = 0

    def factory(**overrides):
        nonlocal sequence
        sequence += 1
        values = {
            "subject_key": f"private_deployment_{sequence}",
            "statement": "SalesMind 支持企业私有化部署。",
            "status": "confirmed_supported",
            "source_document": document,
            "source_chunk_id": sequence,
            "source_excerpt": "支持企业私有化部署",
            "source_index_run_id": document.last_index_run_id,
            "source_content_hash": f"{sequence:064x}",
        }
        values.update(overrides)
        return EnterpriseGroundingFact.objects.create(**values)

    return factory


def test_fact_enums_expose_only_fixed_statuses():
    from apps.knowledge.models import (
        EnterpriseGroundingFactApprovalStatus,
        EnterpriseGroundingFactStatus,
    )

    assert set(EnterpriseGroundingFactStatus.values) == {
        "confirmed_supported",
        "confirmed_unsupported",
        "unconfirmed",
        "conflict",
    }
    assert set(EnterpriseGroundingFactApprovalStatus.values) == {
        "proposed",
        "approved",
        "rejected",
    }


def test_new_fact_defaults_to_proposed_and_current(make_fact):
    fact = make_fact()

    assert fact.approval_status == "proposed"
    assert fact.approved_by is None
    assert fact.approved_at is None
    assert fact.is_stale is False
    assert fact.stale_at is None


def test_chunk_snapshot_survives_chunk_deletion(make_fact, document):
    from apps.knowledge.models import KnowledgeChunk

    chunk = KnowledgeChunk.objects.create(
        document=document,
        chunk_index=0,
        content="支持企业私有化部署",
        embedding=[0.0] * 1024,
        char_count=10,
    )
    fact = make_fact(source_chunk_id=chunk.pk)

    chunk.delete()
    fact.refresh_from_db()

    assert fact.source_chunk_id > 0
    assert fact.source_excerpt == "支持企业私有化部署"


def test_source_document_is_protected_by_auditable_fact(make_fact, document):
    make_fact()

    with pytest.raises(ProtectedError):
        document.delete()


@pytest.mark.parametrize("status", ["invalid", "supported", ""])
def test_database_rejects_unknown_fact_status(make_fact, status):
    with pytest.raises(IntegrityError), transaction.atomic():
        make_fact(status=status)


@pytest.mark.parametrize("approval_status", ["invalid", "pending", ""])
def test_database_rejects_unknown_approval_status(make_fact, approval_status):
    with pytest.raises(IntegrityError), transaction.atomic():
        make_fact(approval_status=approval_status)


def test_approved_fact_requires_actor_and_timestamp(make_fact):
    with pytest.raises(IntegrityError), transaction.atomic():
        make_fact(approval_status="approved")


def test_nonapproved_fact_cannot_hold_approval_metadata(make_fact, actor):
    with pytest.raises(IntegrityError), transaction.atomic():
        make_fact(approved_by=actor, approved_at=timezone.now())


def test_stale_fact_requires_stale_timestamp(make_fact):
    with pytest.raises(IntegrityError), transaction.atomic():
        make_fact(is_stale=True)


def test_current_fact_cannot_hold_stale_timestamp(make_fact):
    with pytest.raises(IntegrityError), transaction.atomic():
        make_fact(stale_at=timezone.now())
