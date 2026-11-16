"""Shared fixtures for sales domain tests.

`persistence_context` and `generated_artifact` live here rather than in one test
module because eight other modules use them; importing a fixture across test
modules works but hides who owns it and leaves every importer looking like it has
an unused import.
"""

import hashlib
from uuid import uuid4

import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone

from apps.accounts.models import UserRole
from apps.knowledge.models import (
    EnterpriseGroundingFact,
    KnowledgeChunk,
    KnowledgeDocument,
)
from apps.sales.models import (
    Customer,
    Opportunity,
    OpportunityRequirementAnalysis,
)
from apps.sales.services.requirement_analysis_history import (
    analysis_record_to_domain,
)
from apps.sales.services.solution_admission import build_solution_admission
from apps.sales.services.solution_draft import (
    GroundedSolutionDraftResult,
    SolutionGenerationStatus,
)
from apps.sales.services.solution_readiness import (
    SolutionReadiness,
    SolutionReadinessStatus,
)
from apps.sales.services.solution_retrieval import SolutionSource
from apps.sales.services.solution_schema import (
    assemble_solution_draft,
    build_solution_unresolved_items,
)
from apps.sales.tests.solution_fakes import analysis_payload


@pytest.fixture
def make_user():
    """Create a user with a unique username and email."""

    sequence = 0

    def factory(role=UserRole.SALES):
        nonlocal sequence
        sequence += 1
        return get_user_model().objects.create_user(
            username=f"user-{sequence}",
            email=f"user-{sequence}@example.com",
            role=role,
            password="StrongPassword123!",
        )

    return factory


@pytest.fixture
def persistence_context(make_user):
    owner = make_user()
    customer = Customer.objects.create(name="Persistence customer", created_by=owner)
    opportunity = Opportunity.objects.create(
        project_name="Persistence opportunity",
        customer=customer,
        sales_owner=owner,
        created_by=owner,
        raw_requirement="客户需要私有化部署。",
    )

    def create_analysis(*, for_opportunity=opportunity, summary="客户需要私有化部署。"):
        payload = analysis_payload()
        return OpportunityRequirementAnalysis.objects.create(
            opportunity=for_opportunity,
            created_by=owner,
            summary=summary,
            requirements=payload["requirements"],
            conflicts=payload["conflicts"],
            clarifying_questions=payload["clarifying_questions"],
            source_raw_requirement=for_opportunity.raw_requirement,
            source_context={"opportunity": {"project_name": for_opportunity.project_name}},
            analysis_version="v1",
            llm_provider="fake",
            llm_model="fake-model",
        )

    analysis = create_analysis()
    return owner, customer, opportunity, analysis, create_analysis



@pytest.fixture
def generated_artifact(persistence_context):
    owner, _, _, analysis, _ = persistence_context
    run_id = uuid4()
    source_content = "SalesMind 当前版本支持企业私有化部署。"
    document = KnowledgeDocument.objects.create(
        title="Private deployment",
        document_type="technical",
        source_file="knowledge/documents/private-deployment.md",
        original_filename="private-deployment.md",
        mime_type="text/markdown",
        file_size=len(source_content.encode()),
        checksum_sha256="a" * 64,
        status="ready",
        chunk_count=1,
        embedding_provider="fake",
        embedding_model="fake-model",
        embedding_dimensions=1024,
        last_indexed_at=timezone.now(),
        last_index_run_id=run_id,
        created_by=owner,
    )
    source = SolutionSource(
        chunk_id=811,
        document_id=document.pk,
        document_title=document.title,
        document_type=document.document_type,
        original_filename=document.original_filename,
        content=source_content,
        page_number=None,
        section_title="部署能力",
        source_reference="Private deployment / 部署能力",
        similarity=0.99,
        label="S1",
    )
    fact = EnterpriseGroundingFact.objects.create(
        subject_key="private_deployment",
        statement=source_content,
        status="confirmed_supported",
        source_document=document,
        source_chunk_id=source.chunk_id,
        source_excerpt=source_content,
        source_index_run_id=run_id,
        source_content_hash=hashlib.sha256(source_content.encode()).hexdigest(),
        approval_status="approved",
        approved_by=owner,
        approved_at=timezone.now(),
    )
    KnowledgeChunk.objects.create(
        pk=source.chunk_id,
        document=document,
        chunk_index=0,
        content=source_content,
        embedding=[0.0] * 1024,
        section_title=source.section_title,
        source_reference=source.source_reference,
        char_count=len(source_content),
    )
    typed = analysis_record_to_domain(analysis)
    admission = build_solution_admission(typed, (source,))
    draft = assemble_solution_draft(admission.claims, typed)
    result = GroundedSolutionDraftResult(
        analysis_id=analysis.pk,
        readiness=SolutionReadiness(SolutionReadinessStatus.READY, (), (), ()),
        generation_status=SolutionGenerationStatus.GENERATED,
        draft=draft,
        sources=(source,),
        unresolved_items=build_solution_unresolved_items(typed),
        admission=admission,
    )
    return result, fact, document
