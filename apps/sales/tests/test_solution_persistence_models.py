"""Persistence invariants for immutable Solution Draft versions."""

from datetime import datetime, timezone as datetime_timezone
from uuid import uuid4

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db.models import ForeignKey
from django.db.models.deletion import ProtectedError

from apps.sales.models import Customer, Opportunity, OpportunityRequirementAnalysis


pytestmark = pytest.mark.django_db


@pytest.fixture
def persisted_context(make_user):
    owner = make_user()
    customer = Customer.objects.create(name="Solution customer", created_by=owner)
    opportunity = Opportunity.objects.create(
        project_name="Solution opportunity",
        customer=customer,
        sales_owner=owner,
        created_by=owner,
    )
    analysis = OpportunityRequirementAnalysis.objects.create(
        opportunity=opportunity,
        created_by=owner,
        summary="客户需要企业知识方案。",
        requirements={},
        conflicts=[],
        clarifying_questions=[],
        source_raw_requirement="企业知识方案",
        source_context={},
        analysis_version="v1",
        llm_provider="fake",
        llm_model="fake-model",
    )
    return owner, opportunity, analysis


def record_values(owner, opportunity, analysis, **overrides):
    values = {
        "opportunity": opportunity,
        "requirement_analysis": analysis,
        "version": 1,
        "title": "商机需求解决方案内部草稿",
        "draft_payload": {"title": "商机需求解决方案内部草稿"},
        "generation_metadata": {"generation_status": "generated"},
        "created_by": owner,
    }
    values.update(overrides)
    return values


def test_solution_record_enums_and_defaults_are_fixed(persisted_context):
    from apps.sales.models import SolutionDraftRecord, SolutionReviewStatus, SolutionStaleReason

    owner, opportunity, analysis = persisted_context
    record = SolutionDraftRecord.objects.create(**record_values(owner, opportunity, analysis))

    assert set(SolutionReviewStatus.values) == {
        "draft", "pending_review", "approved", "needs_revision",
    }
    assert set(SolutionStaleReason.values) == {
        "newer_requirement_analysis",
        "grounding_fact_invalid",
        "grounding_provenance_invalid",
    }
    assert record.review_status == SolutionReviewStatus.DRAFT
    assert record.is_stale is False
    assert record.stale_at is None
    assert record.stale_reasons == []


def test_historical_solution_record_defaults_to_schema_version_one(persisted_context):
    """Dropping the model default would misclassify every historical V1 row."""
    from apps.sales.models import SolutionDraftRecord

    owner, opportunity, analysis = persisted_context
    record = SolutionDraftRecord.objects.create(
        **record_values(owner, opportunity, analysis)
    )

    assert record.schema_version == 1


def test_solution_versions_are_unique_per_opportunity(persisted_context):
    from apps.sales.models import SolutionDraftRecord

    owner, opportunity, analysis = persisted_context
    SolutionDraftRecord.objects.create(**record_values(owner, opportunity, analysis))

    with pytest.raises(IntegrityError), transaction.atomic():
        SolutionDraftRecord.objects.create(**record_values(owner, opportunity, analysis))


def test_non_null_generation_idempotency_keys_are_unique(persisted_context):
    from apps.sales.models import SolutionDraftRecord

    owner, opportunity, analysis = persisted_context
    key = uuid4()
    SolutionDraftRecord.objects.create(
        **record_values(owner, opportunity, analysis, generation_idempotency_key=key)
    )

    with pytest.raises(IntegrityError), transaction.atomic():
        SolutionDraftRecord.objects.create(
            **record_values(
                owner,
                opportunity,
                analysis,
                version=2,
                generation_idempotency_key=key,
            )
        )


def test_solution_record_rejects_nonpositive_version(persisted_context):
    from apps.sales.models import SolutionDraftRecord

    owner, opportunity, analysis = persisted_context
    with pytest.raises(IntegrityError), transaction.atomic():
        SolutionDraftRecord.objects.create(
            **record_values(owner, opportunity, analysis, version=0)
        )


@pytest.mark.parametrize(
    "field,new_value",
    [
        ("schema_version", 2),
        ("version", 2),
        ("title", "changed"),
        ("draft_payload", {"changed": True}),
        ("generation_metadata", {"changed": True}),
        ("generation_idempotency_key", uuid4()),
    ],
)
def test_solution_content_identity_cannot_be_edited_in_place(
    persisted_context,
    field,
    new_value,
):
    from apps.sales.models import SolutionDraftRecord

    owner, opportunity, analysis = persisted_context
    record = SolutionDraftRecord.objects.create(**record_values(owner, opportunity, analysis))
    setattr(record, field, new_value)

    with pytest.raises(ValidationError):
        record.save()


def test_solution_lifecycle_metadata_is_independent_from_content(persisted_context):
    from apps.sales.models import SolutionDraftRecord, SolutionStaleReason

    owner, opportunity, analysis = persisted_context
    record = SolutionDraftRecord.objects.create(**record_values(owner, opportunity, analysis))
    record.is_stale = True
    record.stale_at = datetime.now(datetime_timezone.utc)
    record.stale_reasons = [SolutionStaleReason.NEWER_REQUIREMENT_ANALYSIS]
    record.save(update_fields=["is_stale", "stale_at", "stale_reasons"])
    record.refresh_from_db()

    assert record.review_status == "draft"
    assert record.is_stale is True


def test_provenance_has_snapshot_not_replaceable_chunk_foreign_key(persisted_context):
    from apps.sales.models import SolutionDraftProvenance

    field_names = {field.name for field in SolutionDraftProvenance._meta.fields}
    foreign_targets = {
        field.remote_field.model._meta.label
        for field in SolutionDraftProvenance._meta.fields
        if isinstance(field, ForeignKey)
    }

    assert {
        "solution_draft",
        "statement_path",
        "citation_label",
        "enterprise_grounding_fact",
        "source_document",
        "source_chunk_id",
        "source_index_run_id",
        "source_content_hash",
        "source_excerpt",
        "claim_id",
    } <= field_names
    assert "knowledge.KnowledgeChunk" not in foreign_targets
    assert SolutionDraftProvenance._meta.get_field("enterprise_grounding_fact").null is False
    assert SolutionDraftProvenance._meta.get_field("claim_id").null is True


def test_v1_provenance_allows_null_claim_id(persisted_context):
    """Historical V1 provenance has no stable claim identity and remains valid."""
    from apps.knowledge.models import EnterpriseGroundingFact, KnowledgeDocument
    from apps.sales.models import SolutionDraftProvenance, SolutionDraftRecord

    owner, opportunity, analysis = persisted_context
    document = KnowledgeDocument.objects.create(
        title="V1 source",
        document_type="technical",
        source_file="knowledge/documents/v1-source.md",
        original_filename="v1-source.md",
        mime_type="text/markdown",
        file_size=10,
        checksum_sha256="c" * 64,
        status="ready",
        chunk_count=1,
        embedding_provider="fake",
        embedding_model="fake-model",
        embedding_dimensions=1024,
        last_indexed_at=datetime.now(datetime_timezone.utc),
        last_index_run_id=uuid4(),
        created_by=owner,
    )
    fact = EnterpriseGroundingFact.objects.create(
        subject_key="v1-private-deployment",
        statement="V1 evidence.",
        status="confirmed_supported",
        source_document=document,
        source_chunk_id=8,
        source_excerpt="V1 evidence.",
        source_index_run_id=document.last_index_run_id,
        source_content_hash="d" * 64,
        approval_status="approved",
        approved_by=owner,
        approved_at=datetime.now(datetime_timezone.utc),
    )
    record = SolutionDraftRecord.objects.create(
        **record_values(owner, opportunity, analysis)
    )

    provenance = SolutionDraftProvenance.objects.create(
        solution_draft=record,
        claim_id=None,
        statement_path="solution_sections.deployment.statements[0]",
        citation_label="S1",
        enterprise_grounding_fact=fact,
        source_document=document,
        source_chunk_id=fact.source_chunk_id,
        source_index_run_id=fact.source_index_run_id,
        source_content_hash=fact.source_content_hash,
        source_excerpt=fact.source_excerpt,
    )

    assert provenance.claim_id is None


def test_provenance_rejects_blank_non_null_claim_id(persisted_context):
    """A present V2 claim identifier must identify an actual atomic claim."""
    from apps.knowledge.models import EnterpriseGroundingFact, KnowledgeDocument
    from apps.sales.models import SolutionDraftProvenance, SolutionDraftRecord

    owner, opportunity, analysis = persisted_context
    document = KnowledgeDocument.objects.create(
        title="V2 source",
        document_type="technical",
        source_file="knowledge/documents/v2-source.md",
        original_filename="v2-source.md",
        mime_type="text/markdown",
        file_size=10,
        checksum_sha256="e" * 64,
        status="ready",
        chunk_count=1,
        embedding_provider="fake",
        embedding_model="fake-model",
        embedding_dimensions=1024,
        last_indexed_at=datetime.now(datetime_timezone.utc),
        last_index_run_id=uuid4(),
        created_by=owner,
    )
    fact = EnterpriseGroundingFact.objects.create(
        subject_key="v2-private-deployment",
        statement="V2 evidence.",
        status="confirmed_supported",
        source_document=document,
        source_chunk_id=9,
        source_excerpt="V2 evidence.",
        source_index_run_id=document.last_index_run_id,
        source_content_hash="f" * 64,
        approval_status="approved",
        approved_by=owner,
        approved_at=datetime.now(datetime_timezone.utc),
    )
    record = SolutionDraftRecord.objects.create(
        **record_values(owner, opportunity, analysis)
    )

    with pytest.raises(IntegrityError), transaction.atomic():
        SolutionDraftProvenance.objects.create(
            solution_draft=record,
            claim_id="",
            statement_path="items.C0001",
            citation_label="S1",
            enterprise_grounding_fact=fact,
            source_document=document,
            source_chunk_id=fact.source_chunk_id,
            source_index_run_id=fact.source_index_run_id,
            source_content_hash=fact.source_content_hash,
            source_excerpt=fact.source_excerpt,
        )


def test_solution_and_provenance_audit_relations_are_protected(persisted_context):
    from apps.knowledge.models import EnterpriseGroundingFact, KnowledgeDocument
    from apps.sales.models import SolutionDraftProvenance, SolutionDraftRecord

    owner, opportunity, analysis = persisted_context
    document = KnowledgeDocument.objects.create(
        title="Source",
        document_type="technical",
        source_file="knowledge/documents/source.md",
        original_filename="source.md",
        mime_type="text/markdown",
        file_size=10,
        checksum_sha256="a" * 64,
        status="ready",
        chunk_count=1,
        embedding_provider="fake",
        embedding_model="fake-model",
        embedding_dimensions=1024,
        last_indexed_at=datetime.now(datetime_timezone.utc),
        last_index_run_id=uuid4(),
        created_by=owner,
    )
    fact = EnterpriseGroundingFact.objects.create(
        subject_key="private_deployment",
        statement="SalesMind 支持私有化部署。",
        status="confirmed_supported",
        source_document=document,
        source_chunk_id=7,
        source_excerpt="SalesMind 支持私有化部署。",
        source_index_run_id=document.last_index_run_id,
        source_content_hash="b" * 64,
        approval_status="approved",
        approved_by=owner,
        approved_at=datetime.now(datetime_timezone.utc),
    )
    record = SolutionDraftRecord.objects.create(**record_values(owner, opportunity, analysis))
    SolutionDraftProvenance.objects.create(
        solution_draft=record,
        statement_path="solution_sections.deployment.statements[0]",
        citation_label="S1",
        enterprise_grounding_fact=fact,
        source_document=document,
        source_chunk_id=fact.source_chunk_id,
        source_index_run_id=fact.source_index_run_id,
        source_content_hash=fact.source_content_hash,
        source_excerpt=fact.source_excerpt,
    )

    with pytest.raises(ProtectedError):
        fact.delete()
    with pytest.raises(ProtectedError):
        document.delete()
