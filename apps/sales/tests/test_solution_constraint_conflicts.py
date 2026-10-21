"""A unique-constraint race must surface as a business conflict, never a 500."""

from types import SimpleNamespace

import pytest
from django.db import IntegrityError
from rest_framework.test import APIClient

from apps.accounts.models import UserRole
from apps.sales.models import SolutionReview, SolutionReviewStatus
from apps.sales.services.solution_persistence import generate_and_persist_solution_draft
from apps.sales.tests.test_solution_persistence_service import (  # noqa: F401
    generated_artifact,
    persistence_context,
)
from apps.sales.tests.test_solution_v2_provenance import _patch, _v2_result


pytestmark = pytest.mark.django_db(transaction=True)

CONSTRAINT = "sales_solution_one_pending_review"


def _draft_case(monkeypatch, make_user, persistence_context, generated_artifact):
    owner, _, opportunity, analysis, _ = persistence_context
    reviewer = make_user(UserRole.PRESALES)
    opportunity.presales_owner = reviewer
    opportunity.save(update_fields=["presales_owner"])
    result, _, _ = generated_artifact
    _patch(monkeypatch, _v2_result(result, with_duplicate_text_proposal=True))
    solution = generate_and_persist_solution_draft(
        opportunity, analysis, created_by=owner, schema_version=2,
    )
    return SimpleNamespace(owner=owner, reviewer=reviewer, solution=solution)


def test_submit_constraint_conflict_returns_409_without_the_constraint_name(
    monkeypatch, make_user, persistence_context, generated_artifact,
):
    case = _draft_case(monkeypatch, make_user, persistence_context, generated_artifact)

    def conflict(self, *args, **kwargs):
        raise IntegrityError(
            f'duplicate key value violates unique constraint "{CONSTRAINT}"'
        )

    monkeypatch.setattr(SolutionReview, "save", conflict)

    client = APIClient()
    client.force_authenticate(case.owner)
    response = client.post(
        f"/api/solution-drafts/{case.solution.pk}/submit/", {}, format="json",
    )

    assert response.status_code == 409
    assert response.json()["code"] == "solution_review_invalid_state"
    assert CONSTRAINT not in response.content.decode()
    case.solution.refresh_from_db()
    assert case.solution.review_status == SolutionReviewStatus.DRAFT.value


def test_serialized_submit_still_creates_exactly_one_review(
    monkeypatch, make_user, persistence_context, generated_artifact,
):
    case = _draft_case(monkeypatch, make_user, persistence_context, generated_artifact)
    client = APIClient()
    client.force_authenticate(case.owner)

    first = client.post(
        f"/api/solution-drafts/{case.solution.pk}/submit/", {}, format="json",
    )
    second = client.post(
        f"/api/solution-drafts/{case.solution.pk}/submit/", {}, format="json",
    )

    assert first.status_code in (200, 201)
    assert second.status_code == 409
    assert SolutionReview.objects.filter(solution_draft=case.solution).count() == 1
