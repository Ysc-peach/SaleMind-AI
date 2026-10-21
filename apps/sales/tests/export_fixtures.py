"""Export test data lives exclusively in the pytest database."""
from types import SimpleNamespace

import pytest

from apps.accounts.models import UserRole
from apps.sales.models import SolutionReview, SolutionDraftRecord, SolutionDraftProvenance
from apps.sales.services.solution_persistence import generate_and_persist_solution_draft
from apps.sales.services.solution_review import submit_solution_draft_for_review, approve_solution_draft
from apps.sales.tests.test_solution_persistence_service import persistence_context, generated_artifact
from apps.sales.tests.test_solution_v2_provenance import _v2_result, _patch


@pytest.fixture
def make_export_case(monkeypatch, make_user, persistence_context, generated_artifact):
    def make(schema_version=2):
        owner, _, opportunity, analysis, _ = persistence_context
        reviewer = make_user(UserRole.PRESALES)
        result, fact, document = generated_artifact
        if schema_version == 2:
            result = _v2_result(result, with_duplicate_text_proposal=True)
        _patch(monkeypatch, result)
        solution = generate_and_persist_solution_draft(
            opportunity, analysis, created_by=owner, schema_version=schema_version,
        )
        submitter = make_user(UserRole.ADMIN)
        review = submit_solution_draft_for_review(solution, actor=submitter, reviewer=reviewer)
        review = approve_solution_draft(solution, actor=reviewer, comment='PRIVATE_REVIEW_COMMENT')
        solution.refresh_from_db()
        return SimpleNamespace(owner=owner, reviewer=reviewer, opportunity=opportunity,
            analysis=analysis, solution=solution, approved_review=review, fact=fact, document=document,
            provenance=solution.provenance_entries.first())
    return make


def business_state():
    return (
        tuple(SolutionDraftRecord.objects.values_list('pk', 'review_status', 'is_stale', 'draft_payload')),
        tuple(SolutionReview.objects.values_list('pk', 'status', 'decided_at')),
        SolutionDraftProvenance.objects.count(),
    )
