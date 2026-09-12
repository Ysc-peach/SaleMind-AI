"""Role workspace projections for Sales and Presales users."""

from uuid import uuid4

import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.models import UserRole
from apps.sales.models import (
    Customer,
    Opportunity,
    OpportunityRequirementAnalysis,
    SolutionDraftRecord,
    SolutionReturnReason,
    SolutionReview,
    SolutionReviewDecisionStatus,
    SolutionReviewStatus,
)


pytestmark = pytest.mark.django_db

SALES_WORKSPACE_URL = "/api/workspaces/sales/"
REVIEW_INBOX_URL = "/api/reviews/inbox/"


@pytest.fixture
def api_client():
    return APIClient()


@pytest.fixture
def user_factory():
    sequence = 0

    def create(role, *, username=None, first_name="", last_name="", **flags):
        nonlocal sequence
        sequence += 1
        username = username or f"workspace-user-{sequence}"
        return get_user_model().objects.create_user(
            username=username,
            email=f"{username}@example.com",
            password="StrongPassword123!",
            role=role,
            first_name=first_name,
            last_name=last_name,
            **flags,
        )

    return create


def create_opportunity(*, sales, presales, name, customer_name):
    customer = Customer.objects.create(name=customer_name, created_by=sales)
    opportunity = Opportunity.objects.create(
        project_name=name,
        customer=customer,
        sales_owner=sales,
        presales_owner=presales,
        created_by=sales,
    )
    analysis = OpportunityRequirementAnalysis.objects.create(
        opportunity=opportunity,
        created_by=sales,
        summary="Verified requirement snapshot",
        requirements={},
        conflicts=[],
        clarifying_questions=[],
        source_raw_requirement="",
        source_context={},
        analysis_version="v1",
        llm_provider="controlled",
        llm_model="controlled",
    )
    return opportunity, analysis


def create_draft(*, opportunity, analysis, creator, version=1, status="draft"):
    return SolutionDraftRecord.objects.create(
        opportunity=opportunity,
        requirement_analysis=analysis,
        version=version,
        schema_version=2,
        title=f"Solution V{version}",
        draft_payload={"title": f"Solution V{version}", "claims": []},
        generation_metadata={},
        generation_idempotency_key=uuid4(),
        review_status=status,
        created_by=creator,
    )


def create_review(*, draft, submitter, reviewer, status, reason="", comment=""):
    decided_at = None if status == SolutionReviewDecisionStatus.PENDING else timezone.now()
    return SolutionReview.objects.create(
        solution_draft=draft,
        submitted_by=submitter,
        reviewer=reviewer,
        status=status,
        return_reason=reason,
        comment=comment,
        decided_at=decided_at,
    )


def test_sales_workspace_classifies_own_actionable_work_and_uses_display_names(
    api_client, user_factory
):
    sales = user_factory(
        UserRole.SALES,
        username="alice.sales",
        first_name="Alice",
        last_name="Chen",
    )
    presales = user_factory(UserRole.PRESALES, username="pat.presales")

    confirm_opp, confirm_analysis = create_opportunity(
        sales=sales,
        presales=presales,
        name="Knowledge platform",
        customer_name="Acme Group",
    )
    create_draft(
        opportunity=confirm_opp,
        analysis=confirm_analysis,
        creator=sales,
        status=SolutionReviewStatus.DRAFT,
    )

    pending_opp, pending_analysis = create_opportunity(
        sales=sales,
        presales=presales,
        name="Portal rollout",
        customer_name="Beacon Ltd",
    )
    pending = create_draft(
        opportunity=pending_opp,
        analysis=pending_analysis,
        creator=sales,
        status=SolutionReviewStatus.PENDING_REVIEW,
    )
    create_review(
        draft=pending,
        submitter=sales,
        reviewer=presales,
        status=SolutionReviewDecisionStatus.PENDING,
    )

    returned_opp, returned_analysis = create_opportunity(
        sales=sales,
        presales=presales,
        name="SSO discovery",
        customer_name="Cloud Nine",
    )
    returned = create_draft(
        opportunity=returned_opp,
        analysis=returned_analysis,
        creator=sales,
        status=SolutionReviewStatus.NEEDS_REVISION,
    )
    create_review(
        draft=returned,
        submitter=sales,
        reviewer=presales,
        status=SolutionReviewDecisionStatus.RETURNED,
        reason=SolutionReturnReason.CUSTOMER_INFO_REQUIRED,
        comment="Please confirm the SSO protocol.",
    )

    other_sales = user_factory(UserRole.SALES)
    other_opp, other_analysis = create_opportunity(
        sales=other_sales,
        presales=presales,
        name="Hidden opportunity",
        customer_name="Hidden customer",
    )
    create_draft(
        opportunity=other_opp,
        analysis=other_analysis,
        creator=other_sales,
    )

    api_client.force_authenticate(user=sales)
    response = api_client.get(SALES_WORKSPACE_URL)

    assert response.status_code == 200
    assert {item["project_name"] for item in response.data["my_opportunities"]} == {
        "Knowledge platform",
        "Portal rollout",
        "SSO discovery",
    }
    assert response.data["tasks"]["waiting_for_sales_confirmation"][0]["status"] == (
        "WAITING_FOR_SALES_CONFIRMATION"
    )
    assert response.data["tasks"]["waiting_for_sales_confirmation"][0][
        "customer_name"
    ] == "Acme Group"
    assert response.data["tasks"]["waiting_for_presales_review"][0]["status"] == (
        "WAITING_FOR_PRESALES_REVIEW"
    )
    assert response.data["tasks"]["customer_info_required"][0]["status"] == (
        "CUSTOMER_INFO_REQUIRED"
    )
    assert all(
        item["sales_owner_name"] == "Alice Chen"
        for item in response.data["my_opportunities"]
    )
    assert all(
        item["presales_owner_name"] == "pat.presales"
        for item in response.data["my_opportunities"]
    )
    assert "Hidden opportunity" not in str(response.data)


def test_sales_workspace_rejects_other_roles_and_technical_flags_do_not_bypass(
    api_client, user_factory
):
    for actor in (
        user_factory(UserRole.PRESALES),
        user_factory(UserRole.ADMIN),
        user_factory(UserRole.PRESALES, is_staff=True, is_superuser=True),
    ):
        api_client.force_authenticate(user=actor)
        assert api_client.get(SALES_WORKSPACE_URL).status_code == 403


def test_reviewer_inbox_is_derived_from_request_user_and_cannot_be_spoofed(
    api_client, user_factory
):
    sales = user_factory(UserRole.SALES, username="sam.sales")
    reviewer = user_factory(UserRole.PRESALES, username="riley.reviewer")
    other = user_factory(UserRole.PRESALES, username="other.reviewer")

    pending_opp, pending_analysis = create_opportunity(
        sales=sales,
        presales=reviewer,
        name="Assigned review",
        customer_name="Delta Corp",
    )
    pending = create_draft(
        opportunity=pending_opp,
        analysis=pending_analysis,
        creator=sales,
        status=SolutionReviewStatus.PENDING_REVIEW,
    )
    create_review(
        draft=pending,
        submitter=sales,
        reviewer=reviewer,
        status=SolutionReviewDecisionStatus.PENDING,
    )

    hidden_opp, hidden_analysis = create_opportunity(
        sales=sales,
        presales=other,
        name="Other reviewer item",
        customer_name="Echo Corp",
    )
    hidden = create_draft(
        opportunity=hidden_opp,
        analysis=hidden_analysis,
        creator=sales,
        status=SolutionReviewStatus.PENDING_REVIEW,
    )
    create_review(
        draft=hidden,
        submitter=sales,
        reviewer=other,
        status=SolutionReviewDecisionStatus.PENDING,
    )

    revision_opp, revision_analysis = create_opportunity(
        sales=sales,
        presales=reviewer,
        name="Technical revision",
        customer_name="Foxtrot Corp",
    )
    revision = create_draft(
        opportunity=revision_opp,
        analysis=revision_analysis,
        creator=sales,
        status=SolutionReviewStatus.NEEDS_REVISION,
    )
    create_review(
        draft=revision,
        submitter=sales,
        reviewer=other,
        status=SolutionReviewDecisionStatus.RETURNED,
        reason=SolutionReturnReason.TECHNICAL_REVISION_REQUIRED,
        comment="Revise the HA design.",
    )

    approved_opp, approved_analysis = create_opportunity(
        sales=sales,
        presales=reviewer,
        name="Recently approved",
        customer_name="Gamma Corp",
    )
    approved = create_draft(
        opportunity=approved_opp,
        analysis=approved_analysis,
        creator=sales,
        status=SolutionReviewStatus.APPROVED,
    )
    create_review(
        draft=approved,
        submitter=sales,
        reviewer=reviewer,
        status=SolutionReviewDecisionStatus.APPROVED,
        comment="Approved.",
    )

    api_client.force_authenticate(user=reviewer)
    response = api_client.get(REVIEW_INBOX_URL, {"reviewer_id": other.pk})

    assert response.status_code == 200
    assert [item["project_name"] for item in response.data["pending_reviews"]] == [
        "Assigned review"
    ]
    pending_item = response.data["pending_reviews"][0]
    assert pending_item["customer_name"] == "Delta Corp"
    assert pending_item["sales_owner_name"] == "sam.sales"
    assert pending_item["solution_version"] == 1
    assert pending_item["status"] == "WAITING_FOR_PRESALES_REVIEW"
    assert [item["project_name"] for item in response.data["technical_revisions"]] == [
        "Technical revision"
    ]
    assert [item["project_name"] for item in response.data["recent_reviews"]] == [
        "Recently approved"
    ]
    assert "Other reviewer item" not in str(response.data["pending_reviews"])


def test_reviewer_inbox_rejects_sales_even_with_technical_admin_flags(
    api_client, user_factory
):
    actor = user_factory(UserRole.SALES, is_staff=True, is_superuser=True)
    api_client.force_authenticate(user=actor)

    assert api_client.get(REVIEW_INBOX_URL).status_code == 403


def test_opportunity_list_and_detail_include_safe_display_names(
    api_client, user_factory
):
    sales = user_factory(
        UserRole.SALES,
        username="fallback.sales",
        first_name="Sally",
        last_name="Owner",
    )
    presales = user_factory(UserRole.PRESALES, username="pre.owner")
    opportunity, _ = create_opportunity(
        sales=sales,
        presales=presales,
        name="Display projection",
        customer_name="Named Customer",
    )
    api_client.force_authenticate(user=sales)

    collection = api_client.get("/api/opportunities/")
    detail = api_client.get(f"/api/opportunities/{opportunity.pk}/")

    assert collection.status_code == 200
    assert detail.status_code == 200
    expected = {
        "customer_name": "Named Customer",
        "sales_owner_name": "Sally Owner",
        "presales_owner_name": "pre.owner",
    }
    assert {key: collection.data["results"][0][key] for key in expected} == expected
    assert {key: detail.data[key] for key in expected} == expected
