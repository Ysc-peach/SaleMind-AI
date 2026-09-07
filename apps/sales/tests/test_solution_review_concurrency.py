"""PostgreSQL locking regressions for concurrent Solution review actions."""

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from django.contrib.auth import get_user_model
from django.db import close_old_connections

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
    SolutionReviewError,
    approve_solution_draft,
    request_solution_draft_revision,
    submit_solution_draft_for_review,
)
from apps.sales.tests.solution_fakes import analysis_payload


pytestmark = pytest.mark.django_db(transaction=True)


@pytest.fixture
def concurrent_review_context():
    user_model = get_user_model()
    sales = user_model.objects.create_user(
        username="concurrent-sales",
        email="concurrent-sales@example.com",
        password="StrongPassword123!",
        role=UserRole.SALES,
    )
    presales = user_model.objects.create_user(
        username="concurrent-presales",
        email="concurrent-presales@example.com",
        password="StrongPassword123!",
        role=UserRole.PRESALES,
    )
    customer = Customer.objects.create(name="Concurrent customer", created_by=sales)
    opportunity = Opportunity.objects.create(
        project_name="Concurrent review opportunity",
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
        title="Concurrent solution",
        draft_payload={
            "title": "Concurrent solution",
            "executive_summary": [],
            "solution_sections": [],
            "assumptions": [],
        },
        generation_metadata={"generation_status": "generated"},
        created_by=sales,
    )
    return {"sales": sales, "presales": presales, "solution": solution}


def _run_after_barrier(barrier, function, *args, **kwargs):
    close_old_connections()
    barrier.wait()
    try:
        return function(*args, **kwargs)
    except SolutionReviewError as exc:
        return exc
    finally:
        close_old_connections()


def test_concurrent_submit_creates_only_one_pending_review(concurrent_review_context):
    context = concurrent_review_context
    barrier = Barrier(2)
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [
            pool.submit(
                _run_after_barrier,
                barrier,
                submit_solution_draft_for_review,
                context["solution"],
                actor=context["sales"],
            )
            for _ in range(2)
        ]
        results = [future.result(timeout=10) for future in futures]

    context["solution"].refresh_from_db()
    assert sum(isinstance(result, SolutionReview) for result in results) == 1
    assert sum(isinstance(result, SolutionReviewError) for result in results) == 1
    assert SolutionReview.objects.filter(
        solution_draft=context["solution"],
        status=SolutionReviewDecisionStatus.PENDING,
    ).count() == 1
    assert context["solution"].review_status == SolutionReviewStatus.PENDING_REVIEW


def test_concurrent_approve_and_return_leave_one_valid_final_decision(
    concurrent_review_context,
):
    context = concurrent_review_context
    submit_solution_draft_for_review(context["solution"], actor=context["sales"])
    barrier = Barrier(2)
    with ThreadPoolExecutor(max_workers=2) as pool:
        approve = pool.submit(
            _run_after_barrier,
            barrier,
            approve_solution_draft,
            context["solution"],
            actor=context["presales"],
        )
        returned = pool.submit(
            _run_after_barrier,
            barrier,
            request_solution_draft_revision,
            context["solution"],
            actor=context["presales"],
            return_reason=SolutionReturnReason.TECHNICAL_REVISION_REQUIRED,
            comment="Revise the deployment design.",
        )
        results = [approve.result(timeout=10), returned.result(timeout=10)]

    context["solution"].refresh_from_db()
    review = SolutionReview.objects.get(solution_draft=context["solution"])
    assert sum(isinstance(result, SolutionReview) for result in results) == 1
    assert sum(isinstance(result, SolutionReviewError) for result in results) == 1
    assert review.status in {
        SolutionReviewDecisionStatus.APPROVED,
        SolutionReviewDecisionStatus.RETURNED,
    }
    expected_projection = (
        SolutionReviewStatus.APPROVED
        if review.status == SolutionReviewDecisionStatus.APPROVED
        else SolutionReviewStatus.NEEDS_REVISION
    )
    assert context["solution"].review_status == expected_projection
