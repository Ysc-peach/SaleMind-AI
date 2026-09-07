"""Phase 5.6b HTTP workflow, visibility, and safe action errors."""

from itertools import count

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse
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
from apps.sales.tests.solution_fakes import analysis_payload


pytestmark = pytest.mark.django_db


@pytest.fixture
def review_api_context():
    sequence = count(1)

    def user(role, **flags):
        value = next(sequence)
        return get_user_model().objects.create_user(
            username=f"review-api-{value}",
            email=f"review-api-{value}@example.com",
            password="StrongPassword123!",
            role=role,
            **flags,
        )

    sales = user(UserRole.SALES)
    presales = user(UserRole.PRESALES)
    other_presales = user(UserRole.PRESALES)
    admin = user(UserRole.ADMIN)
    unrelated_sales = user(UserRole.SALES)
    unrelated_presales = user(UserRole.PRESALES)
    technical_admin = user(UserRole.SALES, is_staff=True, is_superuser=True)
    customer = Customer.objects.create(name="Review API customer", created_by=sales)
    opportunity = Opportunity.objects.create(
        project_name="Review API opportunity",
        customer=customer,
        sales_owner=sales,
        presales_owner=presales,
        created_by=sales,
    )
    missing_owner_opportunity = Opportunity.objects.create(
        project_name="Review API missing owner",
        customer=customer,
        sales_owner=sales,
        presales_owner=None,
        created_by=sales,
    )
    versions = count(1)
    payload = analysis_payload()

    def make_analysis(for_opportunity=opportunity):
        return OpportunityRequirementAnalysis.objects.create(
            opportunity=for_opportunity,
            created_by=for_opportunity.sales_owner,
            summary=payload["summary"],
            requirements=payload["requirements"],
            conflicts=payload["conflicts"],
            clarifying_questions=payload["clarifying_questions"],
            source_raw_requirement="synthetic",
            source_context={},
            analysis_version="v1",
            llm_provider="fake",
            llm_model="fake-model",
        )

    def make_solution(*, created_by=sales, for_opportunity=opportunity):
        version = next(versions)
        return SolutionDraftRecord.objects.create(
            opportunity=for_opportunity,
            requirement_analysis=make_analysis(for_opportunity),
            version=version,
            title=f"Review API solution {version}",
            draft_payload={
                "title": f"Review API solution {version}",
                "executive_summary": [],
                "solution_sections": [],
                "assumptions": [],
            },
            generation_metadata={"generation_status": "generated"},
            created_by=created_by,
        )

    return {
        "sales": sales,
        "presales": presales,
        "other_presales": other_presales,
        "admin": admin,
        "unrelated_sales": unrelated_sales,
        "unrelated_presales": unrelated_presales,
        "technical_admin": technical_admin,
        "opportunity": opportunity,
        "missing_owner_opportunity": missing_owner_opportunity,
        "make_analysis": make_analysis,
        "make_solution": make_solution,
    }


def client_for(user):
    client = APIClient()
    client.force_authenticate(user)
    return client


def action_url(name, solution):
    return reverse(name, kwargs={"solution_id": solution.pk})


def test_sales_submit_and_assigned_presales_approve(review_api_context):
    context = review_api_context
    solution = context["make_solution"]()

    submitted = client_for(context["sales"]).post(
        action_url("solution-draft-submit", solution),
        {},
        format="json",
    )
    approved = client_for(context["presales"]).post(
        action_url("solution-draft-approve", solution),
        {"comment": "Technical review passed."},
        format="json",
    )

    solution.refresh_from_db()
    assert submitted.status_code == 201
    assert submitted.json()["status"] == "pending"
    assert submitted.json()["reviewer"] == context["presales"].pk
    assert approved.status_code == 200
    assert approved.json()["status"] == "approved"
    assert solution.review_status == SolutionReviewStatus.APPROVED


@pytest.mark.parametrize(
    "return_reason",
    [
        SolutionReturnReason.CUSTOMER_INFO_REQUIRED,
        SolutionReturnReason.TECHNICAL_REVISION_REQUIRED,
    ],
)
def test_request_revision_persists_exact_reason(review_api_context, return_reason):
    context = review_api_context
    solution = context["make_solution"]()
    client_for(context["sales"]).post(
        action_url("solution-draft-submit", solution), {}, format="json"
    )

    response = client_for(context["presales"]).post(
        action_url("solution-draft-request-revision", solution),
        {
            "return_reason": return_reason,
            "comment": "Please revise this version.",
        },
        format="json",
    )

    solution.refresh_from_db()
    assert response.status_code == 200
    assert response.json()["status"] == "returned"
    assert response.json()["return_reason"] == return_reason
    assert solution.review_status == SolutionReviewStatus.NEEDS_REVISION


@pytest.mark.parametrize("actor_key", ["unrelated_sales", "unrelated_presales", "technical_admin"])
def test_unrelated_users_and_technical_flags_cannot_submit(
    review_api_context,
    actor_key,
):
    context = review_api_context
    solution = context["make_solution"]()

    response = client_for(context[actor_key]).post(
        action_url("solution-draft-submit", solution), {}, format="json"
    )

    assert response.status_code == 404


def test_sales_owner_can_submit_but_cannot_approve(review_api_context):
    context = review_api_context
    solution = context["make_solution"]()
    sales_client = client_for(context["sales"])
    sales_client.post(action_url("solution-draft-submit", solution), {}, format="json")

    response = sales_client.post(
        action_url("solution-draft-approve", solution), {}, format="json"
    )

    assert response.status_code == 403
    assert response.json()["code"] == "solution_review_permission_denied"


def test_missing_presales_owner_fails_with_stable_business_error(review_api_context):
    context = review_api_context
    solution = context["make_solution"](
        for_opportunity=context["missing_owner_opportunity"]
    )

    response = client_for(context["sales"]).post(
        action_url("solution-draft-submit", solution), {}, format="json"
    )

    assert response.status_code == 409
    assert response.json() == {
        "code": "solution_review_missing_reviewer",
        "message": "An eligible Solution reviewer is required.",
    }


def test_presales_authored_version_requires_explicit_independent_reviewer(
    review_api_context,
):
    context = review_api_context
    solution = context["make_solution"](created_by=context["presales"])
    presales_client = client_for(context["presales"])

    missing = presales_client.post(
        action_url("solution-draft-submit", solution), {}, format="json"
    )
    submitted = presales_client.post(
        action_url("solution-draft-submit", solution),
        {"reviewer_id": context["other_presales"].pk},
        format="json",
    )
    approved = client_for(context["other_presales"]).post(
        action_url("solution-draft-approve", solution),
        {"comment": "Independent technical approval."},
        format="json",
    )

    assert missing.status_code == 409
    assert submitted.status_code == 201
    assert submitted.json()["reviewer"] == context["other_presales"].pk
    assert approved.status_code == 200
    assert approved.json()["status"] == SolutionReviewDecisionStatus.APPROVED


def test_independent_reviewer_access_is_limited_to_assigned_solution_version(
    review_api_context,
):
    context = review_api_context
    assigned = context["make_solution"](created_by=context["presales"])
    client_for(context["presales"]).post(
        action_url("solution-draft-submit", assigned),
        {"reviewer_id": context["other_presales"].pk},
        format="json",
    )
    other = context["make_solution"](created_by=context["presales"])
    reviewer_client = client_for(context["other_presales"])

    assigned_detail = reviewer_client.get(
        reverse("solution-draft-detail", kwargs={"solution_id": assigned.pk})
    )
    other_detail = reviewer_client.get(
        reverse("solution-draft-detail", kwargs={"solution_id": other.pk})
    )
    opportunity_list = reviewer_client.get(
        reverse(
            "solution-draft-list",
            kwargs={"opportunity_id": context["opportunity"].pk},
        )
    )

    assert assigned_detail.status_code == 200
    assert other_detail.status_code == 404
    assert opportunity_list.status_code == 404


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"return_reason": SolutionReturnReason.CUSTOMER_INFO_REQUIRED},
        {"comment": "Missing reason."},
        {"return_reason": "invalid", "comment": "Invalid reason."},
        {
            "return_reason": SolutionReturnReason.CUSTOMER_INFO_REQUIRED,
            "comment": "   ",
        },
    ],
)
def test_request_revision_requires_exact_reason_and_comment(review_api_context, payload):
    context = review_api_context
    solution = context["make_solution"]()
    client_for(context["sales"]).post(
        action_url("solution-draft-submit", solution), {}, format="json"
    )

    response = client_for(context["presales"]).post(
        action_url("solution-draft-request-revision", solution),
        payload,
        format="json",
    )

    assert response.status_code == 400


def test_review_history_is_readable_and_has_no_update_or_delete_endpoint(
    review_api_context,
):
    context = review_api_context
    solution = context["make_solution"]()
    client_for(context["sales"]).post(
        action_url("solution-draft-submit", solution), {}, format="json"
    )
    client_for(context["presales"]).post(
        action_url("solution-draft-request-revision", solution),
        {
            "return_reason": SolutionReturnReason.TECHNICAL_REVISION_REQUIRED,
            "comment": "Revise the architecture.",
        },
        format="json",
    )

    history_url = action_url("solution-draft-review-list", solution)
    history = client_for(context["sales"]).get(history_url)
    patched = client_for(context["presales"]).patch(
        history_url, {"status": "approved"}, format="json"
    )
    deleted = client_for(context["admin"]).delete(history_url)

    assert history.status_code == 200
    assert len(history.json()["results"]) == 1
    assert history.json()["results"][0]["status"] == SolutionReviewDecisionStatus.RETURNED
    assert patched.status_code == 405
    assert deleted.status_code == 405


def test_solution_review_status_cannot_be_patched_directly(review_api_context):
    context = review_api_context
    solution = context["make_solution"]()

    response = client_for(context["sales"]).patch(
        reverse("solution-draft-detail", kwargs={"solution_id": solution.pk}),
        {"review_status": "approved"},
        format="json",
    )

    assert response.status_code == 405
    solution.refresh_from_db()
    assert solution.review_status == SolutionReviewStatus.DRAFT


def test_stale_solution_cannot_be_submitted(review_api_context):
    context = review_api_context
    solution = context["make_solution"]()
    context["make_analysis"]()

    response = client_for(context["sales"]).post(
        action_url("solution-draft-submit", solution), {}, format="json"
    )

    assert response.status_code == 409
    assert response.json()["code"] == "solution_review_stale"
    assert not SolutionReview.objects.filter(solution_draft=solution).exists()
