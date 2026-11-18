"""The audit view is a read-only, admin-only, paged projection of history."""

from datetime import timedelta
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
    SolutionReturnReason,
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


def _add_review(opportunity, analysis, sales, reviewer, *, version, status):
    draft = SolutionDraftRecord.objects.create(
        opportunity=opportunity,
        requirement_analysis=analysis,
        version=version,
        schema_version=2,
        title=f"Solution V{version}",
        draft_payload={"title": f"Solution V{version}", "claims": []},
        generation_metadata={},
        generation_idempotency_key=uuid4(),
        review_status=SolutionReviewStatus.PENDING_REVIEW,
        created_by=sales,
    )
    # The table enforces the decision triple (status, return_reason, decided_at),
    # so a returned row needs a reason and a comment to exist at all.
    returned = status == SolutionReviewDecisionStatus.RETURNED
    return SolutionReview.objects.create(
        solution_draft=draft,
        submitted_by=sales,
        reviewer=reviewer,
        status=status,
        return_reason=(
            SolutionReturnReason.CUSTOMER_INFO_REQUIRED if returned else ""
        ),
        comment="退回补充资料" if returned else "",
        decided_at=(
            None
            if status == SolutionReviewDecisionStatus.PENDING
            else timezone.now()
        ),
    )


def _add_job(opportunity, analysis, sales, *, status=SolutionGenerationJobStatus.SUCCEEDED):
    now = timezone.now()
    terminal = status in {
        SolutionGenerationJobStatus.SUCCEEDED,
        SolutionGenerationJobStatus.FAILED,
    }
    return SolutionGenerationJob.objects.create(
        workflow_id=uuid4(),
        opportunity=opportunity,
        requirement_analysis=analysis,
        requested_by=sales,
        status=status,
        attempts=1,
        started_at=now,
        # The table requires finished_at for any terminal status.
        finished_at=now if terminal else None,
        error_code="workflow_generation_error" if terminal and status == SolutionGenerationJobStatus.FAILED else "",
    )


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
    review = _add_review(
        opportunity, analysis, sales, reviewer,
        version=1, status=SolutionReviewDecisionStatus.PENDING,
    )
    job = _add_job(opportunity, analysis, sales)
    return sales, reviewer, opportunity, analysis, review, job


def test_admin_reads_review_and_generation_history(api_client, user_factory):
    sales, reviewer, _opportunity, _analysis, review, job = build_history()
    admin = user_factory(UserRole.ADMIN)
    api_client.force_authenticate(user=admin)

    response = api_client.get(AUDIT_URL)

    assert response.status_code == 200
    assert response.data["page"] == 1
    assert response.data["page_size"] == 20
    assert response.data["reviews"]["count"] == 1
    assert [item["id"] for item in response.data["reviews"]["results"]] == [review.pk]

    review_row = response.data["reviews"]["results"][0]
    assert review_row["project_name"] == "Audit project"
    assert review_row["submitted_by"] == "audit.sales"
    assert review_row["reviewer"] == "audit.presales"
    assert review_row["status"] == "PENDING"
    assert review_row["decided_at"] is None

    assert response.data["generations"]["count"] == 1
    assert [item["id"] for item in response.data["generations"]["results"]] == [job.pk]
    job_row = response.data["generations"]["results"][0]
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


def test_pages_are_sliced_while_the_total_stays_visible(api_client, user_factory):
    sales, reviewer, opportunity, analysis, _review, _job = build_history()
    for version in (2, 3):
        _add_review(
            opportunity, analysis, sales, reviewer,
            version=version, status=SolutionReviewDecisionStatus.PENDING,
        )
    api_client.force_authenticate(user=user_factory(UserRole.ADMIN))

    first = api_client.get(AUDIT_URL, {"page": 1, "page_size": 2})
    second = api_client.get(AUDIT_URL, {"page": 2, "page_size": 2})

    assert first.data["reviews"]["count"] == 3
    assert len(first.data["reviews"]["results"]) == 2
    assert second.data["reviews"]["count"] == 3
    assert len(second.data["reviews"]["results"]) == 1


def test_the_actor_filter_matches_either_side_of_a_review(
    api_client, user_factory
):
    sales, reviewer, opportunity, analysis, _review, _job = build_history()
    _add_review(
        opportunity, analysis, sales, reviewer,
        version=2, status=SolutionReviewDecisionStatus.PENDING,
    )
    api_client.force_authenticate(user=user_factory(UserRole.ADMIN))

    by_reviewer = api_client.get(AUDIT_URL, {"actor": "audit.presales"})
    by_submitter = api_client.get(AUDIT_URL, {"actor": "audit.sales"})
    missing = api_client.get(AUDIT_URL, {"actor": "nobody"})

    assert by_reviewer.data["reviews"]["count"] == 2
    assert by_submitter.data["reviews"]["count"] == 2
    assert by_submitter.data["generations"]["count"] == 1
    assert missing.data["reviews"]["count"] == 0
    assert missing.data["generations"]["count"] == 0


def test_the_status_filter_applies_to_each_history(api_client, user_factory):
    sales, reviewer, opportunity, analysis, _review, _job = build_history()
    _add_review(
        opportunity, analysis, sales, reviewer,
        version=2, status=SolutionReviewDecisionStatus.RETURNED,
    )
    _add_job(opportunity, analysis, sales, status=SolutionGenerationJobStatus.FAILED)
    api_client.force_authenticate(user=user_factory(UserRole.ADMIN))

    returned = api_client.get(AUDIT_URL, {"status": "returned"})
    succeeded = api_client.get(AUDIT_URL, {"status": "succeeded"})

    assert returned.data["reviews"]["count"] == 1
    assert returned.data["generations"]["count"] == 0
    assert succeeded.data["reviews"]["count"] == 0
    assert succeeded.data["generations"]["count"] == 1


def test_the_date_range_excludes_older_rows(api_client, user_factory):
    _sales, _reviewer, _opportunity, _analysis, review, _job = build_history()
    SolutionReview.objects.filter(pk=review.pk).update(
        submitted_at=timezone.now() - timedelta(days=400)
    )
    api_client.force_authenticate(user=user_factory(UserRole.ADMIN))
    today = timezone.localdate().isoformat()

    recent = api_client.get(AUDIT_URL, {"date_from": today})

    assert recent.data["reviews"]["count"] == 0


def test_invalid_query_parameters_are_rejected(api_client, user_factory):
    api_client.force_authenticate(user=user_factory(UserRole.ADMIN))

    assert api_client.get(AUDIT_URL, {"page": 0}).status_code == 400
    assert api_client.get(AUDIT_URL, {"page_size": 101}).status_code == 400
    assert api_client.get(AUDIT_URL, {"page": "abc"}).status_code == 400
    assert api_client.get(AUDIT_URL, {"status": "nonsense"}).status_code == 400
    assert api_client.get(AUDIT_URL, {"date_from": "16-11-2026"}).status_code == 400
    assert (
        api_client.get(
            AUDIT_URL, {"date_from": "2026-11-16", "date_to": "2026-11-01"}
        ).status_code
        == 400
    )


def test_the_actor_filter_does_not_match_a_prefix(api_client, user_factory):
    sales, reviewer, _opportunity, _analysis, _review, _job = build_history()
    api_client.force_authenticate(user=user_factory(UserRole.ADMIN))

    # `audit.sale` is a prefix of `audit.sales` and of nothing else; before this
    # rule it returned that person's history, which makes an audit answer a
    # guess about who did what.
    partial = api_client.get(AUDIT_URL, {"actor": "audit.sale"})

    assert partial.data["reviews"]["count"] == 0
    assert partial.data["generations"]["count"] == 0


def test_the_actor_filter_matches_the_name_the_table_shows(api_client, user_factory):
    sales, _reviewer, _opportunity, _analysis, _review, _job = build_history()
    sales.first_name = "张三"
    sales.save(update_fields=["first_name"])
    api_client.force_authenticate(user=user_factory(UserRole.ADMIN))

    by_name = api_client.get(AUDIT_URL, {"actor": "张三"})

    assert by_name.data["generations"]["count"] == 1
