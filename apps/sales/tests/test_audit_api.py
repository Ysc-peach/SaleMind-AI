"""The audit view is a read-only, admin-only projection of business history."""

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
    SolutionGenerationJob,
    SolutionGenerationJobStatus,
    SolutionReview,
    SolutionReviewDecisionStatus,
    SolutionReviewStatus,
)

pytestmark = pytest.mark.django_db

AUDIT_URL = "/api/audit/events/"


@pytest.fixture
def api_client():
    return APIClient()


@pytest.fixture
def user_factory():
    sequence = 0

    def create(role, *, username=None, first_name="", last_name=""):
        nonlocal sequence
        sequence += 1
        username = username or f"audit-user-{sequence}"
        return get_user_model().objects.create_user(
            username=username,
            email=f"{username}@example.com",
            password="StrongPassword123!",
            role=role,
            first_name=first_name,
            last_name=last_name,
        )

    return create


def build_history():
    sales = get_user_model().objects.create_user(
        "audit.sales", "audit.sales@example.com", "sales",
        password="StrongPassword123!",
    )
    reviewer = get_user_model().objects.create_user(
        "audit.presales", "audit.presales@example.com", "presales",
        password="StrongPassword123!",
    )
    customer = Customer.objects.create(name="Audit Corp", created_by=sales)
    opportunity = Opportunity.objects.create(
        project_name="Audit project",
        customer=customer,
        sales_owner=sales,
        presales_owner=reviewer,
        created_by=sales,
    )
    analysis = OpportunityRequirementAnalysis.objects.create(
        opportunity=opportunity,
        created_by=sales,
        summary="Snapshot",
        requirements={},
        conflicts=[],
        clarifying_questions=[],
        source_raw_requirement="",
        source_context={},
        analysis_version="v1",
        llm_provider="controlled",
        llm_model="controlled",
    )
    draft = SolutionDraftRecord.objects.create(
        opportunity=opportunity,
        requirement_analysis=analysis,
        version=1,
        schema_version=2,
        title="Solution V1",
        draft_payload={"title": "Solution V1", "claims": []},
        generation_metadata={},
        generation_idempotency_key=uuid4(),
        review_status=SolutionReviewStatus.PENDING_REVIEW,
        created_by=sales,
    )
    review = SolutionReview.objects.create(
        solution_draft=draft,
        submitted_by=sales,
        reviewer=reviewer,
        status=SolutionReviewDecisionStatus.PENDING,
    )
    job = SolutionGenerationJob.objects.create(
        workflow_id=uuid4(),
        opportunity=opportunity,
        requirement_analysis=analysis,
        requested_by=sales,
        status=SolutionGenerationJobStatus.SUCCEEDED,
        attempts=1,
        started_at=timezone.now(),
        finished_at=timezone.now(),
    )
    return sales, reviewer, review, job


def test_admin_reads_review_and_generation_history(api_client, user_factory):
    sales, reviewer, review, job = build_history()
    admin = user_factory(UserRole.ADMIN)
    api_client.force_authenticate(user=admin)

    response = api_client.get(AUDIT_URL)

    assert response.status_code == 200
    assert response.data["limit"] == 50
    assert [item["id"] for item in response.data["reviews"]] == [review.pk]
    review_row = response.data["reviews"][0]
    assert review_row["project_name"] == "Audit project"
    assert review_row["submitted_by"] == "audit.sales"
    assert review_row["reviewer"] == "audit.presales"
    assert review_row["status"] == "PENDING"
    assert review_row["decided_at"] is None

    assert [item["id"] for item in response.data["generations"]] == [job.pk]
    job_row = response.data["generations"][0]
    assert job_row["status"] == "SUCCEEDED"
    assert job_row["requested_by"] == "audit.sales"
    assert job_row["error_code"] == ""


def test_sales_and_presales_cannot_read_the_audit_trail(
    api_client, user_factory
):
    build_history()
    for role in (UserRole.SALES, UserRole.PRESALES):
        actor = user_factory(role)
        api_client.force_authenticate(user=actor)
        assert api_client.get(AUDIT_URL).status_code == 403


def test_anonymous_callers_cannot_read_the_audit_trail(api_client):
    assert api_client.get(AUDIT_URL).status_code == 401
