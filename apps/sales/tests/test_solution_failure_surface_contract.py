"""Deterministic rejections and existence oracles must not leak through the Solution Draft API."""

import pytest
from django.urls import reverse

from apps.sales.models import SolutionDraftProvenance, SolutionDraftRecord
from apps.sales.services.solution_grounding import (
    SolutionDraftGroundingError,
    SolutionGroundingErrorCode,
)
from apps.sales.services.solution_review import SolutionReviewErrorCode
from apps.sales.tests.test_solution_draft_api import api_context, client_for  # noqa: F401
from apps.sales.tests.test_solution_review_api import (  # noqa: F401
    action_url,
    review_api_context,
)


pytestmark = pytest.mark.django_db


@pytest.mark.parametrize("error_code", list(SolutionGroundingErrorCode))
def test_grounding_rejection_returns_safe_422_and_persists_nothing(
    monkeypatch,
    api_context,
    error_code,
):
    from apps.sales.api import solution_draft_views

    error = SolutionDraftGroundingError(error_code)

    def reject(*args, **kwargs):
        raise error

    monkeypatch.setattr(solution_draft_views, "generate_and_persist_solution_draft", reject)
    record_count = SolutionDraftRecord.objects.count()
    provenance_count = SolutionDraftProvenance.objects.count()
    response = client_for(api_context["owner"]).post(
        reverse(
            "solution-draft-list",
            kwargs={"opportunity_id": api_context["opportunity"].pk},
        ),
        {"analysis_id": api_context["analysis"].pk},
        format="json",
    )

    assert response.status_code == 422
    assert response.json() == {"code": error.code, "message": error.safe_message}
    assert SolutionDraftRecord.objects.count() == record_count
    assert SolutionDraftProvenance.objects.count() == provenance_count


def test_unknown_reviewer_id_is_indistinguishable_from_ineligible_reviewer(
    review_api_context,
):
    context = review_api_context
    with_unknown_id = context["make_solution"](created_by=context["sales"])
    with_ineligible_id = context["make_solution"](created_by=context["sales"])
    client = client_for(context["sales"])

    unknown = client.post(
        action_url("solution-draft-submit", with_unknown_id),
        {"reviewer_id": 9_999_999},
        format="json",
    )
    ineligible = client.post(
        action_url("solution-draft-submit", with_ineligible_id),
        {"reviewer_id": context["unrelated_sales"].pk},
        format="json",
    )

    expected = {
        "code": SolutionReviewErrorCode.INVALID_REVIEWER.value,
        "message": "The selected Solution reviewer is not eligible.",
    }
    assert unknown.status_code == ineligible.status_code == 409
    assert unknown.json() == ineligible.json() == expected
