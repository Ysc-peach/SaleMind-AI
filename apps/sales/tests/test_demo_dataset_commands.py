"""Production-quality, offline, and safely removable demo dataset."""

from __future__ import annotations

from uuid import UUID, uuid5

import pytest
from django.contrib.auth import authenticate, get_user_model
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import connection
from django.db.models import Count
from psycopg.conninfo import make_conninfo
from rest_framework.test import APIClient

from apps.accounts.models import UserRole
from apps.knowledge.models import (
    EnterpriseGroundingFact,
    EnterpriseGroundingFactApprovalStatus,
    KnowledgeDocument,
    KnowledgeDocumentStatus,
)
from apps.sales.api.opportunity_access import visible_opportunities_for
from apps.sales.models import (
    Customer,
    Opportunity,
    OpportunityRequirementAnalysis,
    SolutionDraftProvenance,
    SolutionDraftRecord,
    SolutionReturnReason,
    SolutionReview,
    SolutionReviewDecisionStatus,
    SolutionReviewStatus,
)
from apps.sales.services.solution_payloads import solution_draft_v2_from_payload


pytestmark = pytest.mark.django_db(transaction=True)


DEMO_NAMESPACE = UUID("23dc62a1-8f7c-4eca-8d6c-6ed354b7942a")
DEMO_USERS = {
    "salesmind_demo_sales_a": ("sales-a@demo.salesmind.invalid", UserRole.SALES, False),
    "salesmind_demo_sales_b": ("sales-b@demo.salesmind.invalid", UserRole.SALES, False),
    "salesmind_demo_presales_a": (
        "presales-a@demo.salesmind.invalid",
        UserRole.PRESALES,
        False,
    ),
    "salesmind_demo_presales_b": (
        "presales-b@demo.salesmind.invalid",
        UserRole.PRESALES,
        False,
    ),
    "salesmind_demo_admin": ("admin@demo.salesmind.invalid", UserRole.ADMIN, True),
}
DEMO_PROJECTS = {
    "manufacturing_knowledge": "华辰精工企业知识平台（演示）",
    "retail_collaboration": "新零售业务协同平台（演示）",
    "enterprise_service_approved": "企业服务知识助手（演示）",
    "manufacturing_identity": "制造业统一身份集成（演示）",
    "ecommerce_ha_revision": "电商平台高可用改造（演示）",
}


def _checkpoint_conninfo() -> str:
    connection.ensure_connection()
    params = connection.get_connection_params()
    return make_conninfo(
        **{
            key: params[key]
            for key in ("dbname", "user", "password", "host", "port")
            if params.get(key) not in (None, "")
        }
    )


@pytest.fixture
def demo_settings(settings, tmp_path):
    settings.LANGGRAPH_CHECKPOINT_DATABASE_URL = _checkpoint_conninfo()
    settings.MEDIA_ROOT = tmp_path
    return settings


@pytest.fixture(autouse=True)
def isolated_demo_checkpoints(demo_settings):
    """Official checkpoint tables are outside Django's managed test flush."""

    from apps.sales.services.solution_workflow_checkpoint import (
        open_solution_workflow_checkpointer,
        setup_solution_workflow_checkpoint_schema,
    )

    setup_solution_workflow_checkpoint_schema()
    workflow_ids = [str(_workflow_id(key)) for key in DEMO_PROJECTS]
    with open_solution_workflow_checkpointer() as saver:
        for workflow_id in workflow_ids:
            saver.delete_thread(workflow_id)
    yield
    with open_solution_workflow_checkpointer() as saver:
        for workflow_id in workflow_ids:
            saver.delete_thread(workflow_id)


def _seed(monkeypatch, demo_settings, password="Demo-only-Strong-Password-41!"):
    monkeypatch.setenv("SALESMIND_DEMO_PASSWORD", password)
    call_command("seed_demo", verbosity=0)


def _workflow_id(scenario_key: str):
    return uuid5(DEMO_NAMESPACE, f"{scenario_key}:solution:v1")


def _solution(scenario_key: str) -> SolutionDraftRecord:
    return SolutionDraftRecord.objects.get(
        generation_idempotency_key=_workflow_id(scenario_key)
    )


def _demo_checkpoint_row_count() -> int:
    workflow_ids = [str(_workflow_id(key)) for key in DEMO_PROJECTS]
    placeholders = ", ".join(["%s"] * len(workflow_ids))
    with connection.cursor() as cursor:
        cursor.execute(
            f"SELECT COUNT(*) FROM checkpoints WHERE thread_id IN ({placeholders})",
            workflow_ids,
        )
        return cursor.fetchone()[0]


def _demo_checkpoint_thread_count() -> int:
    workflow_ids = [str(_workflow_id(key)) for key in DEMO_PROJECTS]
    placeholders = ", ".join(["%s"] * len(workflow_ids))
    with connection.cursor() as cursor:
        cursor.execute(
            f"SELECT COUNT(DISTINCT thread_id) FROM checkpoints "
            f"WHERE thread_id IN ({placeholders})",
            workflow_ids,
        )
        return cursor.fetchone()[0]


def test_seed_demo_requires_password_and_never_prints_it(
    monkeypatch,
    demo_settings,
    capsys,
):
    monkeypatch.delenv("SALESMIND_DEMO_PASSWORD", raising=False)

    with pytest.raises(CommandError, match="SALESMIND_DEMO_PASSWORD"):
        call_command("seed_demo", verbosity=0)

    password = "Do-Not-Print-This-Demo-Password-51!"
    _seed(monkeypatch, demo_settings, password)
    captured = capsys.readouterr()
    assert password not in captured.out
    assert password not in captured.err


def test_first_seed_creates_exact_identities_scenarios_and_real_business_states(
    monkeypatch,
    demo_settings,
):
    _seed(monkeypatch, demo_settings)

    users = get_user_model().objects.filter(username__in=DEMO_USERS)
    assert users.count() == 5
    for username, (email, role, is_staff) in DEMO_USERS.items():
        user = users.get(username=username)
        assert (user.email, user.role, user.is_staff, user.is_superuser) == (
            email,
            role,
            is_staff,
            False,
        )
    assert set(
        Opportunity.objects.filter(project_name__in=DEMO_PROJECTS.values()).values_list(
            "project_name", flat=True
        )
    ) == set(DEMO_PROJECTS.values())

    waiting_sales = _solution("manufacturing_knowledge")
    waiting_presales = _solution("retail_collaboration")
    approved = _solution("enterprise_service_approved")
    customer_return = _solution("manufacturing_identity")
    technical_return = _solution("ecommerce_ha_revision")
    assert waiting_sales.review_status == SolutionReviewStatus.DRAFT
    assert not waiting_sales.reviews.exists()
    assert waiting_presales.review_status == SolutionReviewStatus.PENDING_REVIEW
    assert waiting_presales.reviews.get().status == SolutionReviewDecisionStatus.PENDING
    assert approved.review_status == SolutionReviewStatus.APPROVED
    assert approved.reviews.get().status == SolutionReviewDecisionStatus.APPROVED
    assert customer_return.review_status == SolutionReviewStatus.NEEDS_REVISION
    assert customer_return.reviews.get().return_reason == (
        SolutionReturnReason.CUSTOMER_INFO_REQUIRED
    )
    assert technical_return.review_status == SolutionReviewStatus.NEEDS_REVISION
    assert technical_return.reviews.get().return_reason == (
        SolutionReturnReason.TECHNICAL_REVISION_REQUIRED
    )


def test_seed_is_idempotent_resets_only_demo_password_and_uses_no_network_factories(
    monkeypatch,
    demo_settings,
):
    def unexpected_factory_call(*_args, **_kwargs):
        raise AssertionError("A configured external provider factory was called.")

    monkeypatch.setattr("apps.llm.factory.get_llm_provider", unexpected_factory_call)
    monkeypatch.setattr(
        "apps.llm.verifier_factory.get_verifier_provider",
        unexpected_factory_call,
    )
    monkeypatch.setattr(
        "apps.knowledge.embeddings.get_embedding_provider",
        unexpected_factory_call,
    )
    first_password = "First-Demo-Password-61!"
    second_password = "Second-Demo-Password-62!"
    _seed(monkeypatch, demo_settings, first_password)
    before = {
        "users": get_user_model().objects.count(),
        "customers": Customer.objects.count(),
        "opportunities": Opportunity.objects.count(),
        "analyses": OpportunityRequirementAnalysis.objects.count(),
        "solutions": SolutionDraftRecord.objects.count(),
        "reviews": SolutionReview.objects.count(),
        "provenance": SolutionDraftProvenance.objects.count(),
        "checkpoint_rows": _demo_checkpoint_row_count(),
    }
    assert _demo_checkpoint_thread_count() == 5

    _seed(monkeypatch, demo_settings, second_password)

    after = {
        "users": get_user_model().objects.count(),
        "customers": Customer.objects.count(),
        "opportunities": Opportunity.objects.count(),
        "analyses": OpportunityRequirementAnalysis.objects.count(),
        "solutions": SolutionDraftRecord.objects.count(),
        "reviews": SolutionReview.objects.count(),
        "provenance": SolutionDraftProvenance.objects.count(),
        "checkpoint_rows": _demo_checkpoint_row_count(),
    }
    assert after == before
    for username in DEMO_USERS:
        assert authenticate(username=username, password=second_password) is not None


def test_interrupted_seed_recovers_deterministic_solution_and_review_identities(
    monkeypatch,
    demo_settings,
):
    from apps.sales.services import demo_dataset

    original = demo_dataset.generate_and_persist_solution_draft
    calls = 0

    def persist_then_interrupt(*args, **kwargs):
        nonlocal calls
        record = original(*args, **kwargs)
        calls += 1
        if calls == 1:
            raise RuntimeError("simulated command interruption after persistence")
        return record

    monkeypatch.setattr(
        demo_dataset,
        "generate_and_persist_solution_draft",
        persist_then_interrupt,
    )
    monkeypatch.setenv("SALESMIND_DEMO_PASSWORD", "Interrupted-Demo-Password-71!")
    with pytest.raises(RuntimeError, match="simulated command interruption"):
        call_command("seed_demo", verbosity=0)
    assert SolutionDraftRecord.objects.count() == 1

    monkeypatch.setattr(
        demo_dataset,
        "generate_and_persist_solution_draft",
        original,
    )
    call_command("seed_demo", verbosity=0)
    call_command("seed_demo", verbosity=0)

    assert SolutionDraftRecord.objects.count() == 5
    assert SolutionReview.objects.count() == 4
    assert not (
        SolutionDraftRecord.objects.values("generation_idempotency_key")
        .annotate(total=Count("id"))
        .filter(total__gt=1)
        .exists()
    )


def test_interrupted_seed_recovers_pending_document_and_proposed_facts(
    monkeypatch,
    demo_settings,
):
    from apps.sales.services import demo_dataset

    original_index = demo_dataset.index_document
    original_approve = demo_dataset.approve_grounding_facts
    index_calls = 0

    def interrupt_before_first_index(*args, **kwargs):
        nonlocal index_calls
        index_calls += 1
        if index_calls == 1:
            raise RuntimeError("simulated interruption before indexing")
        return original_index(*args, **kwargs)

    monkeypatch.setattr(demo_dataset, "index_document", interrupt_before_first_index)
    monkeypatch.setenv("SALESMIND_DEMO_PASSWORD", "Interrupted-Knowledge-Password-72!")
    with pytest.raises(RuntimeError, match="before indexing"):
        call_command("seed_demo", verbosity=0)
    pending = KnowledgeDocument.objects.get(
        title="SalesMind 演示资料：企业知识平台能力"
    )
    assert pending.status == KnowledgeDocumentStatus.PENDING
    assert not pending.grounding_facts.exists()

    monkeypatch.setattr(demo_dataset, "index_document", original_index)

    def interrupt_after_first_extraction(fact_ids, *, actor):
        del fact_ids, actor
        raise RuntimeError("simulated interruption before Fact approval")

    monkeypatch.setattr(
        demo_dataset,
        "approve_grounding_facts",
        interrupt_after_first_extraction,
    )
    with pytest.raises(RuntimeError, match="before Fact approval"):
        call_command("seed_demo", verbosity=0)
    assert EnterpriseGroundingFact.objects.filter(
        source_document=pending,
        approval_status=EnterpriseGroundingFactApprovalStatus.PROPOSED,
    ).count() == 3

    monkeypatch.setattr(demo_dataset, "approve_grounding_facts", original_approve)
    call_command("seed_demo", verbosity=0)
    call_command("seed_demo", verbosity=0)
    assert KnowledgeDocument.objects.count() == 3
    assert EnterpriseGroundingFact.objects.count() == 13
    assert SolutionDraftRecord.objects.count() == 5


def test_fixture_identity_mismatch_fails_closed_before_creating_business_data(
    monkeypatch,
    demo_settings,
):
    get_user_model().objects.create_user(
        username="salesmind_demo_sales_a",
        email="sales-a@demo.salesmind.invalid",
        role=UserRole.PRESALES,
        password="Unrelated-Password-81!",
    )

    monkeypatch.setenv("SALESMIND_DEMO_PASSWORD", "Demo-Password-82!")
    with pytest.raises(CommandError, match="conflict"):
        call_command("seed_demo", verbosity=0)

    assert not Customer.objects.exists()
    assert not Opportunity.objects.exists()


def test_seed_preserves_role_visibility_and_reviewer_inbox_assignment(
    monkeypatch,
    demo_settings,
):
    _seed(monkeypatch, demo_settings)
    users = get_user_model().objects
    sales_a = users.get(username="salesmind_demo_sales_a")
    sales_b = users.get(username="salesmind_demo_sales_b")
    presales_a = users.get(username="salesmind_demo_presales_a")
    sales_a_projects = set(
        visible_opportunities_for(sales_a).values_list("project_name", flat=True)
    )
    sales_b_projects = set(
        visible_opportunities_for(sales_b).values_list("project_name", flat=True)
    )
    assert sales_a_projects
    assert sales_b_projects
    assert sales_a_projects.isdisjoint(sales_b_projects)

    client = APIClient()
    client.force_authenticate(presales_a)
    response = client.get("/api/reviews/inbox/")
    assert response.status_code == 200
    pending = response.data["pending_reviews"]
    assert len(pending) == 1
    assert pending[0]["project_name"] == DEMO_PROJECTS["retail_collaboration"]
    assert pending[0]["sales_owner_name"] == "演示销售 A"

    client.force_authenticate(sales_a)
    response = client.get("/api/workspaces/sales/")
    assert response.status_code == 200
    tasks = response.data["tasks"]
    assert [item["project_name"] for item in tasks["waiting_for_sales_confirmation"]] == [
        DEMO_PROJECTS["manufacturing_knowledge"]
    ]
    assert [item["project_name"] for item in tasks["waiting_for_presales_review"]] == [
        DEMO_PROJECTS["retail_collaboration"]
    ]

    client.force_authenticate(sales_b)
    response = client.get("/api/workspaces/sales/")
    assert [item["project_name"] for item in response.data["tasks"]["customer_info_required"]] == [
        DEMO_PROJECTS["manufacturing_identity"]
    ]

    presales_b = users.get(username="salesmind_demo_presales_b")
    client.force_authenticate(presales_b)
    response = client.get("/api/reviews/inbox/")
    assert [item["project_name"] for item in response.data["technical_revisions"]] == [
        DEMO_PROJECTS["ecommerce_ha_revision"]
    ]


def test_checkpoint_reconstructs_waiting_sales_confirmation_from_postgres(
    monkeypatch,
    demo_settings,
):
    from apps.sales.services.solution_review_workflow import build_solution_review_graph
    from apps.sales.services.solution_workflow_checkpoint import (
        open_solution_workflow_checkpointer,
    )

    _seed(monkeypatch, demo_settings)
    workflow_id = _workflow_id("manufacturing_knowledge")
    config = {"configurable": {"thread_id": str(workflow_id)}}

    with open_solution_workflow_checkpointer() as saver:
        first_graph = build_solution_review_graph(saver)
        first = first_graph.get_state(config)
        assert first.values["workflow_outcome"] == "waiting_for_sales_confirmation"
        assert first.next == ("wait_for_sales_confirmation",)
    with open_solution_workflow_checkpointer() as saver:
        rebuilt_graph = build_solution_review_graph(saver)
        rebuilt = rebuilt_graph.get_state(config)
        assert rebuilt.values["solution_draft_id"] == _solution(
            "manufacturing_knowledge"
        ).pk
        assert rebuilt.values["workflow_stage"] == "waiting_for_sales_confirmation"


def test_v2_claims_provenance_and_api_source_projection_are_consistent(
    monkeypatch,
    demo_settings,
):
    _seed(monkeypatch, demo_settings)
    solution = _solution("enterprise_service_approved")
    domain = solution_draft_v2_from_payload(solution.draft_payload)
    claim_ids = {claim.claim_id for claim in domain.claims}
    provenance = list(solution.provenance_entries.select_related("source_document"))
    assert solution.schema_version == 2
    assert len(claim_ids) == len(domain.claims)
    assert domain.executive_summary_claim_ids
    assert domain.customer_context.confirmed_claim_ids
    assert domain.proposed_solution.overview_claim_ids
    assert domain.architecture.components
    assert domain.deployment_and_integration
    assert len(domain.implementation_plan.phases) == 2
    assert len(domain.risks) == 2
    assert len(domain.acceptance_criteria) == 2
    assert len(domain.milestones) == 2
    assert domain.assumption_claim_ids
    assert len(domain.open_questions) == 2
    assert len(domain.out_of_scope) == 2
    assert provenance
    assert all(entry.claim_id in claim_ids for entry in provenance)

    client = APIClient()
    client.force_authenticate(solution.opportunity.sales_owner)
    response = client.get(f"/api/solution-drafts/{solution.pk}/")
    assert response.status_code == 200
    source_ids = {item["source_id"] for item in response.data["source_registry"]}
    assert source_ids
    assert set(response.data["claim_sources"]).issubset(claim_ids)
    assert {
        source_id
        for labels in response.data["claim_sources"].values()
        for source_id in labels
    }.issubset(source_ids)


def test_clear_demo_removes_complete_graph_but_preserves_unrelated_rows(
    monkeypatch,
    demo_settings,
):
    unrelated = get_user_model().objects.create_user(
        username="ordinary-user",
        email="ordinary-user@example.com",
        role=UserRole.SALES,
        password="Ordinary-Password-91!",
    )
    unrelated_customer = Customer.objects.create(
        name="Unrelated real-like customer",
        created_by=unrelated,
    )
    _seed(monkeypatch, demo_settings)

    call_command("clear_demo", verbosity=0)

    assert not get_user_model().objects.filter(username__in=DEMO_USERS).exists()
    assert not Opportunity.objects.filter(project_name__in=DEMO_PROJECTS.values()).exists()
    assert not SolutionDraftRecord.objects.filter(
        generation_idempotency_key__in=[
            _workflow_id(key) for key in DEMO_PROJECTS
        ]
    ).exists()
    assert _demo_checkpoint_row_count() == 0
    assert not KnowledgeDocument.objects.filter(
        created_by__username="salesmind_demo_admin"
    ).exists()
    assert get_user_model().objects.filter(pk=unrelated.pk).exists()
    assert Customer.objects.filter(pk=unrelated_customer.pk).exists()


def test_clear_demo_removes_orphaned_demo_checkpoint_without_business_rows(
    demo_settings,
):
    from apps.sales.services.solution_review_workflow import build_solution_review_graph
    from apps.sales.services.solution_workflow_checkpoint import (
        open_solution_workflow_checkpointer,
    )

    workflow_id = _workflow_id("manufacturing_knowledge")
    config = {"configurable": {"thread_id": str(workflow_id)}}
    with open_solution_workflow_checkpointer() as saver:
        graph = build_solution_review_graph(saver)
        graph.update_state(
            config,
            {
                "workflow_run_id": str(workflow_id),
                "opportunity_id": 991,
                "requirement_analysis_id": 992,
                "requested_by_id": 993,
                "solution_draft_id": 994,
                "solution_version": 1,
                "workflow_stage": "waiting_for_sales_confirmation",
                "workflow_outcome": "waiting_for_sales_confirmation",
                "error_code": "",
            },
            as_node="generate_solution",
        )
        graph.invoke(None, config)
    assert _demo_checkpoint_row_count() > 0

    call_command("clear_demo", verbosity=0)

    assert _demo_checkpoint_row_count() == 0


def test_clear_demo_refuses_shared_knowledge_reference_without_partial_deletion(
    monkeypatch,
    demo_settings,
    make_user,
):
    _seed(monkeypatch, demo_settings)
    demo_solution = _solution("enterprise_service_approved")
    demo_entry = demo_solution.provenance_entries.first()
    unrelated_sales = make_user(UserRole.SALES)
    unrelated_customer = Customer.objects.create(
        name="External customer",
        created_by=unrelated_sales,
    )
    unrelated_opportunity = Opportunity.objects.create(
        project_name="External opportunity",
        customer=unrelated_customer,
        sales_owner=unrelated_sales,
        created_by=unrelated_sales,
    )
    payload = demo_solution.requirement_analysis
    unrelated_analysis = OpportunityRequirementAnalysis.objects.create(
        opportunity=unrelated_opportunity,
        created_by=unrelated_sales,
        summary=payload.summary,
        requirements=payload.requirements,
        conflicts=payload.conflicts,
        clarifying_questions=payload.clarifying_questions,
        source_raw_requirement="External requirement",
        source_context={},
        analysis_version="v1",
        llm_provider="controlled-test",
        llm_model="controlled-test",
    )
    unrelated_solution = SolutionDraftRecord.objects.create(
        opportunity=unrelated_opportunity,
        requirement_analysis=unrelated_analysis,
        version=1,
        title=demo_solution.title,
        draft_payload=demo_solution.draft_payload,
        generation_metadata={"generation_status": "generated"},
        schema_version=2,
        created_by=unrelated_sales,
    )
    SolutionDraftProvenance.objects.create(
        solution_draft=unrelated_solution,
        statement_path="claims[0]",
        claim_id=demo_entry.claim_id,
        citation_label=demo_entry.citation_label,
        enterprise_grounding_fact=demo_entry.enterprise_grounding_fact,
        source_document=demo_entry.source_document,
        source_chunk_id=demo_entry.source_chunk_id,
        source_index_run_id=demo_entry.source_index_run_id,
        source_content_hash=demo_entry.source_content_hash,
        source_excerpt=demo_entry.source_excerpt,
    )
    before = SolutionDraftRecord.objects.count()

    with pytest.raises(CommandError, match="non-demo"):
        call_command("clear_demo", verbosity=0)

    assert SolutionDraftRecord.objects.count() == before
    assert get_user_model().objects.filter(username__in=DEMO_USERS).count() == 5
