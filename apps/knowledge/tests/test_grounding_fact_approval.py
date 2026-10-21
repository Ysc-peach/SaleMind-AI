"""Human approval boundary for proposed enterprise grounding facts."""

from uuid import uuid4

import pytest
from django.utils import timezone

from apps.accounts.models import UserRole
from apps.knowledge.models import (
    EnterpriseGroundingFact,
    EnterpriseGroundingFactApprovalStatus,
    EnterpriseGroundingFactStatus,
    KnowledgeDocument,
)


pytestmark = pytest.mark.django_db


@pytest.fixture
def fact_fixture(django_user_model):
    owner = django_user_model.objects.create_user(
        username="fact-owner",
        email="fact-owner@example.com",
        role=UserRole.ADMIN,
        password="StrongPassword123!",
    )
    document = KnowledgeDocument.objects.create(
        title="Capability",
        document_type="technical",
        source_file="knowledge/documents/capability.md",
        original_filename="capability.md",
        mime_type="text/markdown",
        file_size=10,
        checksum_sha256="c" * 64,
        status="ready",
        chunk_count=1,
        embedding_provider="fake",
        embedding_model="fake",
        embedding_dimensions=1024,
        last_indexed_at=timezone.now(),
        last_index_run_id=uuid4(),
        created_by=owner,
    )
    fact = EnterpriseGroundingFact.objects.create(
        subject_key="private_deployment",
        statement="SalesMind 支持私有化部署。",
        status=EnterpriseGroundingFactStatus.CONFIRMED_SUPPORTED,
        source_document=document,
        source_chunk_id=7,
        source_excerpt="支持私有化部署",
        source_index_run_id=document.last_index_run_id,
        source_content_hash="d" * 64,
    )
    return owner, document, fact


def create_actor(django_user_model, *, role=UserRole.ADMIN, **flags):
    suffix = uuid4().hex
    return django_user_model.objects.create_user(
        username=f"actor-{suffix}",
        email=f"actor-{suffix}@example.com",
        role=role,
        password="StrongPassword123!",
        **flags,
    )


def test_business_admin_can_approve_proposed_fact(fact_fixture, django_user_model):
    from apps.knowledge.services.grounding_fact_approval import approve_grounding_facts

    _, _, fact = fact_fixture
    actor = create_actor(django_user_model, is_staff=True)

    count = approve_grounding_facts([fact.pk], actor=actor)

    fact.refresh_from_db()
    assert count == 1
    assert fact.approval_status == EnterpriseGroundingFactApprovalStatus.APPROVED
    assert fact.approved_by == actor
    assert fact.approved_at is not None


def test_business_admin_can_reject_proposal(fact_fixture, django_user_model):
    from apps.knowledge.services.grounding_fact_approval import reject_grounding_facts

    _, _, fact = fact_fixture
    actor = create_actor(django_user_model, is_staff=True)

    count = reject_grounding_facts([fact.pk], actor=actor)

    fact.refresh_from_db()
    assert count == 1
    assert fact.approval_status == EnterpriseGroundingFactApprovalStatus.REJECTED
    assert fact.approved_by is None
    assert fact.approved_at is None


@pytest.mark.parametrize("action", ["approve_grounding_facts", "reject_grounding_facts"])
@pytest.mark.parametrize(
    "actor_kwargs",
    [
        {"role": UserRole.SALES, "is_staff": True, "is_superuser": False},
        {"role": UserRole.SALES, "is_staff": True, "is_superuser": True},
        {"role": UserRole.ADMIN, "is_staff": False, "is_superuser": False},
        {"role": UserRole.ADMIN, "is_staff": True, "is_active": False},
    ],
)
def test_technical_flags_do_not_bypass_business_approval_role(
    fact_fixture,
    django_user_model,
    action,
    actor_kwargs,
):
    from apps.knowledge.services import grounding_fact_approval

    _, _, fact = fact_fixture
    actor = create_actor(django_user_model, **actor_kwargs)

    with pytest.raises(PermissionError):
        getattr(grounding_fact_approval, action)([fact.pk], actor=actor)

    fact.refresh_from_db()
    assert fact.approval_status == EnterpriseGroundingFactApprovalStatus.PROPOSED


def test_stale_fact_cannot_be_approved(fact_fixture, django_user_model):
    from apps.knowledge.services.grounding_fact_approval import approve_grounding_facts

    _, _, fact = fact_fixture
    fact.is_stale = True
    fact.stale_at = timezone.now()
    fact.save(update_fields=["is_stale", "stale_at"])
    actor = create_actor(django_user_model, is_staff=True)

    with pytest.raises(ValueError):
        approve_grounding_facts([fact.pk], actor=actor)

    fact.refresh_from_db()
    assert fact.approval_status == EnterpriseGroundingFactApprovalStatus.PROPOSED


def test_admin_registers_fact_review_and_read_only_documents(fact_fixture, django_user_model):
    from django.contrib import admin

    from apps.knowledge.models import KnowledgeChunk

    assert admin.site.is_registered(EnterpriseGroundingFact)
    assert admin.site.is_registered(KnowledgeDocument)
    assert not admin.site.is_registered(KnowledgeChunk)

    model_admin = admin.site._registry[EnterpriseGroundingFact]
    admin_actor = create_actor(django_user_model, is_staff=True)
    sales_superuser = create_actor(
        django_user_model,
        role=UserRole.SALES,
        is_staff=True,
        is_superuser=True,
    )

    class Request:
        pass

    request = Request()
    request.user = admin_actor
    assert model_admin.has_view_permission(request) is True
    assert model_admin.has_change_permission(request) is True
    assert model_admin.has_add_permission(request) is False
    assert model_admin.has_delete_permission(request) is False

    request.user = sales_superuser
    assert model_admin.has_view_permission(request) is False
    assert model_admin.has_change_permission(request) is False
