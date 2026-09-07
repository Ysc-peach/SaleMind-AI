"""Transactional business rules for Solution review transitions."""

from itertools import count

import pytest

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
from apps.sales.services.solution_review import (
    SolutionReviewPermissionError,
    SolutionReviewStateError,
    approve_solution_draft,
    request_solution_draft_revision,
    submit_solution_draft_for_review,
)
from apps.sales.services.solution_persistence import refresh_solution_draft_staleness
from apps.sales.tests.solution_fakes import analysis_payload


pytestmark = pytest.mark.django_db


@pytest.fixture
def review_service_context(make_user):
    sales = make_user(UserRole.SALES)
    presales = make_user(UserRole.PRESALES)
    other_presales = make_user(UserRole.PRESALES)
    admin = make_user(UserRole.ADMIN)
    unrelated_sales = make_user(UserRole.SALES)
    unrelated_presales = make_user(UserRole.PRESALES)
    technical_admin = make_user(UserRole.SALES)
    technical_admin.is_staff = True
    technical_admin.is_superuser = True
    technical_admin.save(update_fields=["is_staff", "is_superuser"])
    customer = Customer.objects.create(name="Review service customer", created_by=sales)
    opportunity = Opportunity.objects.create(
        project_name="Review service opportunity",
        customer=customer,
        sales_owner=sales,
        presales_owner=presales,
        created_by=sales,
    )
    missing_owner_opportunity = Opportunity.objects.create(
        project_name="Missing Presales opportunity",
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

    def make_solution(*, created_by=sales, for_opportunity=opportunity, stale=False):
        version = next(versions)
        return SolutionDraftRecord.objects.create(
            opportunity=for_opportunity,
            requirement_analysis=make_analysis(for_opportunity),
            version=version,
            title=f"Review service solution {version}",
            draft_payload={
                "title": f"Review service solution {version}",
                "executive_summary": [],
                "solution_sections": [],
                "assumptions": [],
            },
            generation_metadata={"generation_status": "generated"},
            review_status=SolutionReviewStatus.DRAFT,
            is_stale=stale,
            stale_at=None,
            stale_reasons=[],
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


def test_sales_owner_submit_creates_one_pending_review_for_assigned_presales(
    review_service_context,
):
    context = review_service_context
    solution = context["make_solution"]()

    review = submit_solution_draft_for_review(solution, actor=context["sales"])

    solution.refresh_from_db()
    assert review.solution_draft_id == solution.pk
    assert review.submitted_by_id == context["sales"].pk
    assert review.reviewer_id == context["presales"].pk
    assert review.status == SolutionReviewDecisionStatus.PENDING
    assert solution.review_status == SolutionReviewStatus.PENDING_REVIEW
    assert SolutionReview.objects.filter(solution_draft=solution).count() == 1


def test_stale_draft_cannot_be_submitted(review_service_context):
    context = review_service_context
    solution = context["make_solution"]()
    context["make_analysis"]()

    with pytest.raises(SolutionReviewStateError):
        submit_solution_draft_for_review(solution, actor=context["sales"])

    solution.refresh_from_db()
    assert solution.review_status == SolutionReviewStatus.DRAFT
    assert not SolutionReview.objects.filter(solution_draft=solution).exists()


def test_submit_fails_safely_without_assigned_presales_owner(review_service_context):
    context = review_service_context
    solution = context["make_solution"](
        for_opportunity=context["missing_owner_opportunity"]
    )

    with pytest.raises(SolutionReviewStateError):
        submit_solution_draft_for_review(solution, actor=context["sales"])

    assert not SolutionReview.objects.filter(solution_draft=solution).exists()


@pytest.mark.parametrize("actor_key", ["unrelated_sales", "technical_admin"])
def test_unrelated_sales_cannot_submit_even_with_technical_flags(
    review_service_context,
    actor_key,
):
    context = review_service_context
    solution = context["make_solution"]()

    with pytest.raises(SolutionReviewPermissionError):
        submit_solution_draft_for_review(solution, actor=context[actor_key])


def test_presales_authored_version_requires_another_presales_reviewer(
    review_service_context,
):
    context = review_service_context
    solution = context["make_solution"](created_by=context["presales"])

    with pytest.raises(SolutionReviewStateError):
        submit_solution_draft_for_review(solution, actor=context["presales"])
    with pytest.raises(SolutionReviewStateError):
        submit_solution_draft_for_review(
            solution,
            actor=context["presales"],
            reviewer=context["presales"],
        )

    review = submit_solution_draft_for_review(
        solution,
        actor=context["presales"],
        reviewer=context["other_presales"],
    )
    assert review.reviewer_id == context["other_presales"].pk


def test_presales_owner_can_submit_sales_authored_version_for_own_review(
    review_service_context,
):
    context = review_service_context
    solution = context["make_solution"]()

    review = submit_solution_draft_for_review(solution, actor=context["presales"])

    assert review.reviewer_id == context["presales"].pk


def test_admin_can_submit_as_business_fallback(review_service_context):
    context = review_service_context
    solution = context["make_solution"]()

    review = submit_solution_draft_for_review(solution, actor=context["admin"])

    assert review.reviewer_id == context["presales"].pk


def test_admin_fallback_can_submit_and_approve_without_presales_owner(
    review_service_context,
):
    context = review_service_context
    solution = context["make_solution"](
        for_opportunity=context["missing_owner_opportunity"]
    )

    review = submit_solution_draft_for_review(solution, actor=context["admin"])
    approved = approve_solution_draft(solution, actor=context["admin"])

    assert review.reviewer_id == context["admin"].pk
    assert approved.status == SolutionReviewDecisionStatus.APPROVED


def test_business_admin_cannot_assign_own_authored_version_to_self(
    review_service_context,
):
    context = review_service_context
    solution = context["make_solution"](
        created_by=context["admin"],
        for_opportunity=context["missing_owner_opportunity"],
    )

    with pytest.raises(SolutionReviewStateError):
        submit_solution_draft_for_review(solution, actor=context["admin"])


def test_assigned_presales_approve_atomically_updates_review_and_projection(
    review_service_context,
):
    context = review_service_context
    solution = context["make_solution"]()
    review = submit_solution_draft_for_review(solution, actor=context["sales"])

    decided = approve_solution_draft(
        solution,
        actor=context["presales"],
        comment="Technical review passed.",
    )

    solution.refresh_from_db()
    review.refresh_from_db()
    assert decided.pk == review.pk
    assert review.status == SolutionReviewDecisionStatus.APPROVED
    assert review.return_reason == ""
    assert review.comment == "Technical review passed."
    assert review.decided_at is not None
    assert solution.review_status == SolutionReviewStatus.APPROVED


@pytest.mark.parametrize("actor_key", ["sales", "unrelated_presales"])
def test_sales_and_unrelated_presales_cannot_approve(
    review_service_context,
    actor_key,
):
    context = review_service_context
    solution = context["make_solution"]()
    submit_solution_draft_for_review(solution, actor=context["sales"])

    with pytest.raises(SolutionReviewPermissionError):
        approve_solution_draft(solution, actor=context[actor_key])

    solution.refresh_from_db()
    assert solution.review_status == SolutionReviewStatus.PENDING_REVIEW


def test_business_admin_can_approve_as_fallback(review_service_context):
    context = review_service_context
    solution = context["make_solution"]()
    submit_solution_draft_for_review(solution, actor=context["sales"])

    review = approve_solution_draft(solution, actor=context["admin"])

    assert review.status == SolutionReviewDecisionStatus.APPROVED


def test_business_admin_cannot_approve_own_authored_version(review_service_context):
    context = review_service_context
    solution = context["make_solution"](created_by=context["admin"])
    SolutionReview.objects.create(
        solution_draft=solution,
        submitted_by=context["admin"],
        reviewer=context["admin"],
    )
    solution.review_status = SolutionReviewStatus.PENDING_REVIEW
    solution.save(update_fields=["review_status"])

    with pytest.raises(SolutionReviewPermissionError):
        approve_solution_draft(solution, actor=context["admin"])


def test_presales_reviewer_cannot_approve_own_authored_version(
    review_service_context,
):
    context = review_service_context
    solution = context["make_solution"](created_by=context["presales"])
    SolutionReview.objects.create(
        solution_draft=solution,
        submitted_by=context["presales"],
        reviewer=context["presales"],
    )
    solution.review_status = SolutionReviewStatus.PENDING_REVIEW
    solution.save(update_fields=["review_status"])

    with pytest.raises(SolutionReviewPermissionError):
        approve_solution_draft(solution, actor=context["presales"])


def test_stale_pending_solution_cannot_be_approved(review_service_context):
    context = review_service_context
    solution = context["make_solution"]()
    review = submit_solution_draft_for_review(solution, actor=context["sales"])
    context["make_analysis"]()

    with pytest.raises(SolutionReviewStateError):
        approve_solution_draft(solution, actor=context["presales"])

    solution.refresh_from_db()
    review.refresh_from_db()
    assert solution.review_status == SolutionReviewStatus.PENDING_REVIEW
    assert review.status == SolutionReviewDecisionStatus.PENDING


def test_stale_pending_solution_can_be_returned_for_revision(review_service_context):
    context = review_service_context
    solution = context["make_solution"]()
    submit_solution_draft_for_review(solution, actor=context["sales"])
    context["make_analysis"]()

    review = request_solution_draft_revision(
        solution,
        actor=context["presales"],
        return_reason=SolutionReturnReason.CUSTOMER_INFO_REQUIRED,
        comment="Use the newer customer requirement snapshot.",
    )

    solution.refresh_from_db()
    assert review.status == SolutionReviewDecisionStatus.RETURNED
    assert solution.review_status == SolutionReviewStatus.NEEDS_REVISION


def test_duplicate_approve_cannot_create_or_overwrite_a_decision(review_service_context):
    context = review_service_context
    solution = context["make_solution"]()
    submit_solution_draft_for_review(solution, actor=context["sales"])
    approved = approve_solution_draft(solution, actor=context["presales"])

    with pytest.raises(SolutionReviewStateError):
        approve_solution_draft(solution, actor=context["presales"])

    approved.refresh_from_db()
    assert approved.status == SolutionReviewDecisionStatus.APPROVED
    assert SolutionReview.objects.filter(solution_draft=solution).count() == 1

    with pytest.raises(SolutionReviewStateError):
        submit_solution_draft_for_review(solution, actor=context["sales"])


@pytest.mark.parametrize(
    "return_reason",
    [
        SolutionReturnReason.CUSTOMER_INFO_REQUIRED,
        SolutionReturnReason.TECHNICAL_REVISION_REQUIRED,
    ],
)
def test_request_revision_persists_exact_reason_and_changes_projection(
    review_service_context,
    return_reason,
):
    context = review_service_context
    solution = context["make_solution"]()
    submit_solution_draft_for_review(solution, actor=context["sales"])
    original_payload = solution.draft_payload

    review = request_solution_draft_revision(
        solution,
        actor=context["presales"],
        return_reason=return_reason,
        comment="Please address this review finding.",
    )

    solution.refresh_from_db()
    assert review.status == SolutionReviewDecisionStatus.RETURNED
    assert review.return_reason == return_reason
    assert review.comment == "Please address this review finding."
    assert review.decided_at is not None
    assert solution.review_status == SolutionReviewStatus.NEEDS_REVISION
    assert solution.draft_payload == original_payload


@pytest.mark.parametrize(
    ("return_reason", "comment"),
    [
        ("", "Missing reason."),
        ("not-a-return-reason", "Invalid reason."),
        (SolutionReturnReason.CUSTOMER_INFO_REQUIRED, ""),
        (SolutionReturnReason.TECHNICAL_REVISION_REQUIRED, "   "),
    ],
)
def test_request_revision_requires_valid_reason_and_nonblank_comment(
    review_service_context,
    return_reason,
    comment,
):
    context = review_service_context
    solution = context["make_solution"]()
    review = submit_solution_draft_for_review(solution, actor=context["sales"])

    with pytest.raises(SolutionReviewStateError):
        request_solution_draft_revision(
            solution,
            actor=context["presales"],
            return_reason=return_reason,
            comment=comment,
        )

    solution.refresh_from_db()
    review.refresh_from_db()
    assert solution.review_status == SolutionReviewStatus.PENDING_REVIEW
    assert review.status == SolutionReviewDecisionStatus.PENDING


def test_approved_solution_can_become_stale_without_losing_approval_history(
    review_service_context,
):
    context = review_service_context
    solution = context["make_solution"]()
    submit_solution_draft_for_review(solution, actor=context["sales"])
    review = approve_solution_draft(solution, actor=context["presales"])
    context["make_analysis"]()

    refresh_solution_draft_staleness(solution)

    solution.refresh_from_db()
    review.refresh_from_db()
    assert solution.is_stale is True
    assert solution.review_status == SolutionReviewStatus.APPROVED
    assert review.status == SolutionReviewDecisionStatus.APPROVED
