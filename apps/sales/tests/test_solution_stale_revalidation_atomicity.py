"""Approval-time staleness must be derived under a lock, never from straddled reads.

``evaluate_solution_draft_stale_reasons`` reads provenance, documents and chunks
with separate statements. Deriving the reasons outside a lock let a concurrent
reindex commit land between those reads, and the resulting false verdict was
written into the monotonic ``stale_reasons`` union, which is never cleared. The
refresh path now locks the draft and its provenance rows first.
"""

from types import SimpleNamespace

import pytest
from django.utils import timezone

from apps.accounts.models import UserRole
from apps.knowledge.models import EnterpriseGroundingFact
from apps.sales.models import SolutionDraftRecord, SolutionReviewStatus, SolutionStaleReason
from apps.sales.services.solution_export_guard import (
    SolutionExportError,
    load_export_snapshot,
)
from apps.sales.services.solution_persistence import (
    generate_and_persist_solution_draft,
    project_solution_draft_staleness,
)
from apps.sales.services.solution_review import (
    SolutionReviewError,
    SolutionReviewErrorCode,
    approve_solution_draft,
    submit_solution_draft_for_review,
    validate_solution_review_submission,
)
from apps.sales.tests.export_fixtures import make_export_case  # noqa: F401
from apps.sales.tests.test_solution_persistence_service import (  # noqa: F401
    generated_artifact,
    persistence_context,
)
from apps.sales.tests.test_solution_v2_provenance import _patch, _v2_result


pytestmark = pytest.mark.django_db(transaction=True)


def _pending_case(monkeypatch, make_user, persistence_context, generated_artifact):
    owner, _, opportunity, analysis, _ = persistence_context
    reviewer = make_user(UserRole.PRESALES)
    submitter = make_user(UserRole.ADMIN)
    result, fact, document = generated_artifact
    result = _v2_result(result, with_duplicate_text_proposal=True)
    _patch(monkeypatch, result)
    solution = generate_and_persist_solution_draft(
        opportunity, analysis, created_by=owner, schema_version=2,
    )
    submit_solution_draft_for_review(solution, actor=submitter, reviewer=reviewer)
    solution.refresh_from_db()
    return SimpleNamespace(
        owner=owner, reviewer=reviewer, submitter=submitter, opportunity=opportunity,
        analysis=analysis, solution=solution, fact=fact, document=document,
    )


def test_reasons_are_derived_only_after_the_source_rows_are_locked(
    monkeypatch, make_user, persistence_context, generated_artifact,
):
    case = _pending_case(monkeypatch, make_user, persistence_context, generated_artifact)
    from apps.sales.services import solution_persistence

    events = []
    real_lock = solution_persistence._lock_staleness_source_rows
    real_evaluate = solution_persistence.evaluate_solution_draft_stale_reasons

    def lock(record):
        events.append("lock")
        real_lock(record)

    def evaluate(record):
        events.append("evaluate")
        return real_evaluate(record)

    monkeypatch.setattr(solution_persistence, "_lock_staleness_source_rows", lock)
    monkeypatch.setattr(solution_persistence, "evaluate_solution_draft_stale_reasons", evaluate)

    approve_solution_draft(case.solution, actor=case.reviewer)

    assert events == ["lock", "evaluate"]


def test_real_reindex_invalidation_is_persisted_and_blocks_approval(
    monkeypatch, make_user, persistence_context, generated_artifact,
):
    case = _pending_case(monkeypatch, make_user, persistence_context, generated_artifact)
    EnterpriseGroundingFact.objects.filter(pk=case.fact.pk).update(
        is_stale=True, stale_at=timezone.now(),
    )

    with pytest.raises(SolutionReviewError) as caught:
        approve_solution_draft(case.solution, actor=case.reviewer)

    assert caught.value.code == SolutionReviewErrorCode.STALE.value
    case.solution.refresh_from_db()
    assert case.solution.is_stale is True
    assert SolutionStaleReason.GROUNDING_FACT_INVALID.value in case.solution.stale_reasons
    assert case.solution.review_status == SolutionReviewStatus.PENDING_REVIEW.value


def test_read_only_eligibility_check_never_writes_stale_metadata(
    monkeypatch, make_user, persistence_context, generated_artifact,
):
    case = _pending_case(monkeypatch, make_user, persistence_context, generated_artifact)
    EnterpriseGroundingFact.objects.filter(pk=case.fact.pk).update(
        is_stale=True, stale_at=timezone.now(),
    )

    with pytest.raises(SolutionReviewError) as caught:
        validate_solution_review_submission(
            case.solution, actor=case.submitter, reviewer=case.reviewer,
        )

    assert caught.value.code == SolutionReviewErrorCode.STALE.value
    fresh = SolutionDraftRecord.objects.get(pk=case.solution.pk)
    assert fresh.is_stale is False
    assert fresh.stale_reasons == []
    assert fresh.stale_at is None


def test_projection_helper_never_writes_stale_metadata(make_export_case):
    case = make_export_case()
    EnterpriseGroundingFact.objects.filter(pk=case.fact.pk).update(
        is_stale=True, stale_at=timezone.now(),
    )

    projected = project_solution_draft_staleness(
        SolutionDraftRecord.objects.get(pk=case.solution.pk)
    )

    assert projected.is_stale is True
    fresh = SolutionDraftRecord.objects.get(pk=case.solution.pk)
    assert fresh.is_stale is False
    assert fresh.stale_reasons == []
    assert fresh.stale_at is None


def test_export_still_rejects_a_version_invalidated_by_reindex(make_export_case):
    case = make_export_case()
    EnterpriseGroundingFact.objects.filter(pk=case.fact.pk).update(
        is_stale=True, stale_at=timezone.now(),
    )

    with pytest.raises(SolutionExportError) as caught:
        load_export_snapshot(
            actor_id=case.owner.pk, solution_id=case.solution.pk,
            exported_at=timezone.now(),
        )

    assert caught.value.code == "solution_export_stale"
