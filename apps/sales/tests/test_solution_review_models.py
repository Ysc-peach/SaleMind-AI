"""Persistence contract for version-scoped Solution review attempts."""

from datetime import datetime, timezone as datetime_timezone

import pytest
from django.db import IntegrityError, transaction
from django.db.models.deletion import ProtectedError
from django.core.exceptions import ValidationError

from apps.accounts.models import UserRole
from apps.sales.models import (
    Customer,
    Opportunity,
    OpportunityRequirementAnalysis,
    SolutionDraftRecord,
    SolutionReturnReason,
    SolutionReview,
    SolutionReviewDecisionStatus,
)
from apps.sales.tests.solution_fakes import analysis_payload


pytestmark = pytest.mark.django_db


@pytest.fixture
def review_context(make_user):
    sales = make_user(UserRole.SALES)
    presales = make_user(UserRole.PRESALES)
    other_presales = make_user(UserRole.PRESALES)
    customer = Customer.objects.create(name="Review model customer", created_by=sales)
    opportunity = Opportunity.objects.create(
        project_name="Review model opportunity",
        customer=customer,
        sales_owner=sales,
        presales_owner=presales,
        created_by=sales,
    )
    payload = analysis_payload()
    analysis = OpportunityRequirementAnalysis.objects.create(
        opportunity=opportunity,
        created_by=sales,
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
    solution = SolutionDraftRecord.objects.create(
        opportunity=opportunity,
        requirement_analysis=analysis,
        version=1,
        title="Review model solution",
        draft_payload={
            "title": "Review model solution",
            "executive_summary": [],
            "solution_sections": [],
            "assumptions": [],
        },
        generation_metadata={"generation_status": "generated"},
        created_by=sales,
    )
    return {
        "sales": sales,
        "presales": presales,
        "other_presales": other_presales,
        "solution": solution,
    }


def pending_review(context):
    return SolutionReview.objects.create(
        solution_draft=context["solution"],
        submitted_by=context["sales"],
        reviewer=context["presales"],
    )


def test_review_enums_and_pending_defaults_are_fixed(review_context):
    review = pending_review(review_context)

    assert set(SolutionReviewDecisionStatus.values) == {
        "pending",
        "approved",
        "returned",
    }
    assert set(SolutionReturnReason.values) == {
        "customer_info_required",
        "technical_revision_required",
    }
    assert review.status == SolutionReviewDecisionStatus.PENDING
    assert review.return_reason == ""
    assert review.comment == ""
    assert review.decided_at is None


def test_only_one_pending_review_can_exist_for_a_solution(review_context):
    pending_review(review_context)

    with pytest.raises(IntegrityError), transaction.atomic():
        SolutionReview.objects.create(
            solution_draft=review_context["solution"],
            submitted_by=review_context["sales"],
            reviewer=review_context["other_presales"],
        )


@pytest.mark.parametrize(
    "overrides",
    [
        {
            "status": "pending",
            "decided_at": datetime.now(datetime_timezone.utc),
        },
        {
            "status": "approved",
            "return_reason": "customer_info_required",
            "decided_at": datetime.now(datetime_timezone.utc),
        },
        {
            "status": "returned",
            "return_reason": "technical_revision_required",
            "comment": "",
            "decided_at": datetime.now(datetime_timezone.utc),
        },
    ],
)
def test_database_rejects_inconsistent_review_decision_state(review_context, overrides):
    values = {
        "solution_draft": review_context["solution"],
        "submitted_by": review_context["sales"],
        "reviewer": review_context["presales"],
    }
    values.update(overrides)

    with pytest.raises(IntegrityError), transaction.atomic():
        SolutionReview.objects.create(**values)


def test_reviewer_and_submitter_are_protected_audit_identities(review_context):
    pending_review(review_context)

    with pytest.raises(ProtectedError):
        review_context["sales"].delete()
    with pytest.raises(ProtectedError):
        review_context["presales"].delete()


def test_pending_review_identity_cannot_be_changed(review_context):
    review = pending_review(review_context)
    review.reviewer = review_context["other_presales"]

    with pytest.raises(ValidationError):
        review.save()


def test_completed_review_decision_cannot_be_overwritten(review_context):
    review = pending_review(review_context)
    review.status = SolutionReviewDecisionStatus.APPROVED
    review.comment = "Initial approval"
    review.decided_at = datetime.now(datetime_timezone.utc)
    review.save(update_fields=["status", "comment", "decided_at"])

    review.status = SolutionReviewDecisionStatus.RETURNED
    review.return_reason = SolutionReturnReason.TECHNICAL_REVISION_REQUIRED
    review.comment = "Changed after decision"

    with pytest.raises(ValidationError):
        review.save()


def test_review_history_cannot_be_deleted(review_context):
    review = pending_review(review_context)

    with pytest.raises(ValidationError):
        review.delete()
