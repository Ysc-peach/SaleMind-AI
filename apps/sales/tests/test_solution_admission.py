"""Deterministic admission from approved, current provenance facts."""

import hashlib
from uuid import uuid4

import pytest
from django.utils import timezone

from apps.knowledge.models import (
    EnterpriseGroundingFact,
    EnterpriseGroundingFactApprovalStatus as Approval,
    EnterpriseGroundingFactStatus as FactStatus,
    KnowledgeDocument,
)
from apps.sales.services.solution_retrieval import SolutionSource
from apps.sales.services.solution_schema import SolutionStatementType
from apps.sales.tests.solution_fakes import typed_analysis


pytestmark = pytest.mark.django_db


@pytest.fixture
def provenance(django_user_model):
    actor = django_user_model.objects.create_user(
        username="admission-admin",
        email="admission-admin@example.com",
        role="admin",
        password="StrongPassword123!",
    )
    run_id = uuid4()
    content = "SalesMind 当前版本支持企业私有化部署。"
    document = KnowledgeDocument.objects.create(
        title="Deployment",
        document_type="technical",
        source_file="knowledge/documents/deployment.md",
        original_filename="deployment.md",
        mime_type="text/markdown",
        file_size=64,
        checksum_sha256="e" * 64,
        status="ready",
        chunk_count=1,
        embedding_provider="fake",
        embedding_model="fake",
        embedding_dimensions=1024,
        last_indexed_at=timezone.now(),
        last_index_run_id=run_id,
        created_by=actor,
    )
    source = SolutionSource(
        chunk_id=41,
        document_id=document.pk,
        document_title=document.title,
        document_type=document.document_type,
        original_filename=document.original_filename,
        content=content,
        page_number=None,
        section_title="能力边界",
        source_reference="Deployment / 能力边界",
        similarity=0.99,
        label="S1",
    )
    return actor, document, source


def make_fact(
    provenance,
    *,
    subject_key="private_deployment",
    statement="SalesMind 当前版本支持企业私有化部署。",
    status=FactStatus.CONFIRMED_SUPPORTED,
    approval_status=Approval.APPROVED,
    is_stale=False,
    run_id=None,
    content_hash=None,
):
    actor, document, source = provenance
    approved = approval_status == Approval.APPROVED
    return EnterpriseGroundingFact.objects.create(
        subject_key=subject_key,
        statement=statement,
        status=status,
        source_document=document,
        source_chunk_id=source.chunk_id,
        source_excerpt=source.content,
        source_index_run_id=run_id or document.last_index_run_id,
        source_content_hash=content_hash or hashlib.sha256(source.content.encode()).hexdigest(),
        approval_status=approval_status,
        approved_by=actor if approved else None,
        approved_at=timezone.now() if approved else None,
        is_stale=is_stale,
        stale_at=timezone.now() if is_stale else None,
    )


def enterprise_claims(admission):
    return tuple(
        claim
        for claim in admission.claims.claims
        if claim.statement_type is SolutionStatementType.ENTERPRISE_FACT
    )


@pytest.mark.parametrize(
    ("status", "statement"),
    [
        (FactStatus.CONFIRMED_SUPPORTED, "SalesMind 当前版本支持企业私有化部署。"),
        (FactStatus.CONFIRMED_UNSUPPORTED, "SalesMind 当前版本不支持 CSV 批量导出。"),
    ],
)
def test_current_approved_confirmed_fact_creates_enterprise_claim(
    provenance,
    status,
    statement,
):
    from apps.sales.services.solution_admission import build_solution_admission

    fact = make_fact(provenance, status=status, statement=statement)

    admission = build_solution_admission(typed_analysis(), (provenance[2],))

    claims = enterprise_claims(admission)
    assert [(item.text, item.citations) for item in claims] == [(statement, ("S1",))]
    assert admission.enterprise_provenance[0].fact_id == fact.pk
    assert admission.enterprise_provenance[0].claim == claims[0]


@pytest.mark.parametrize(
    "fact_kwargs",
    [
        {"approval_status": Approval.PROPOSED},
        {"approval_status": Approval.REJECTED},
        {"is_stale": True},
        {"status": FactStatus.UNCONFIRMED},
        {"status": FactStatus.CONFLICT},
        {"run_id": uuid4()},
        {"content_hash": "0" * 64},
    ],
)
def test_nonadmissible_fact_never_creates_enterprise_claim(provenance, fact_kwargs):
    from apps.sales.services.solution_admission import build_solution_admission

    make_fact(provenance, **fact_kwargs)

    admission = build_solution_admission(typed_analysis(), (provenance[2],))

    assert enterprise_claims(admission) == ()
    decision = next(item for item in admission.enterprise_decisions if item.subject_key == "private_deployment")
    assert decision.status in {FactStatus.UNCONFIRMED, FactStatus.CONFLICT}
    assert decision.enterprise_fact_ids == ()


def test_opposed_approved_facts_resolve_to_conflict(provenance):
    from apps.sales.services.solution_admission import build_solution_admission

    make_fact(provenance, status=FactStatus.CONFIRMED_SUPPORTED)
    make_fact(
        provenance,
        status=FactStatus.CONFIRMED_UNSUPPORTED,
        statement="SalesMind 当前版本不支持企业私有化部署。",
    )

    admission = build_solution_admission(typed_analysis(), (provenance[2],))

    assert enterprise_claims(admission) == ()
    decision = next(item for item in admission.enterprise_decisions if item.subject_key == "private_deployment")
    assert decision.status == FactStatus.CONFLICT
    assert decision.needs_attention is True


def test_missing_subject_defaults_to_unconfirmed():
    from apps.sales.services.solution_admission import resolve_enterprise_subject

    decision = resolve_enterprise_subject("oracle_compatibility", ())

    assert decision.status == FactStatus.UNCONFIRMED
    assert decision.enterprise_fact_ids == ()
    assert decision.needs_attention is False


@pytest.mark.parametrize(
    "subject_key",
    [
        "server_compatibility",
        "oa_integration",
        "sso_integration",
        "kubernetes_deployment",
        "oracle_compatibility",
    ],
)
def test_n4_subjects_cannot_be_admitted_without_current_approved_confirmed_fact(
    provenance,
    subject_key,
):
    from apps.sales.services.solution_admission import build_solution_admission

    make_fact(
        provenance,
        subject_key=subject_key,
        status=FactStatus.UNCONFIRMED,
    )

    admission = build_solution_admission(typed_analysis(), (provenance[2],))

    assert all(
        item.subject_key != subject_key for item in admission.enterprise_provenance
    )
    assert all(
        not (
            claim.statement_type is SolutionStatementType.ENTERPRISE_FACT
            and claim.text == "SalesMind 当前版本支持企业私有化部署。"
        )
        for claim in admission.claims.claims
    )


def test_known_customer_facts_and_gaps_are_program_owned(provenance):
    from apps.sales.services.solution_admission import build_solution_admission

    admission = build_solution_admission(
        typed_analysis(existing_environment="unclear", integration_requirement="unknown"),
        (provenance[2],),
    )

    customer = [
        claim for claim in admission.claims.claims
        if claim.statement_type is SolutionStatementType.CUSTOMER_FACT
    ]
    unresolved = [
        claim for claim in admission.claims.claims
        if claim.statement_type is SolutionStatementType.UNRESOLVED
    ]
    assert any("约300人" in claim.text for claim in customer)
    assert all(not claim.citations for claim in customer)
    assert any("现有环境" in claim.text for claim in unresolved)
    assert any("集成要求" in claim.text for claim in unresolved)


def test_only_supported_provenance_labels_are_available_to_proposals(provenance):
    from apps.sales.services.solution_admission import build_solution_admission

    make_fact(provenance, status=FactStatus.CONFIRMED_SUPPORTED)
    make_fact(
        provenance,
        subject_key="csv_bulk_export",
        status=FactStatus.CONFIRMED_UNSUPPORTED,
        statement="SalesMind 当前版本不支持 CSV 批量导出。",
    )

    admission = build_solution_admission(typed_analysis(), (provenance[2],))

    assert admission.allowed_proposal_source_labels == ("S1",)

