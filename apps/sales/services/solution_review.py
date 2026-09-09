"""Transactional, business-role-aware Solution review lifecycle."""

from enum import StrEnum

from django.contrib.auth import get_user_model
from django.db import transaction
from django.utils import timezone

from apps.accounts.models import UserRole
from apps.sales.models import (
    SolutionDraftRecord,
    SolutionReturnReason,
    SolutionReview,
    SolutionReviewDecisionStatus,
    SolutionReviewStatus,
)
from apps.sales.services.solution_persistence import (
    evaluate_solution_draft_stale_reasons,
)


class SolutionReviewErrorCode(StrEnum):
    PERMISSION_DENIED = "solution_review_permission_denied"
    INVALID_STATE = "solution_review_invalid_state"
    STALE = "solution_review_stale"
    MISSING_REVIEWER = "solution_review_missing_reviewer"
    INVALID_REVIEWER = "solution_review_invalid_reviewer"
    SELF_REVIEW = "solution_review_self_review"
    NO_PENDING_REVIEW = "solution_review_no_pending_review"


_SAFE_MESSAGES = {
    SolutionReviewErrorCode.PERMISSION_DENIED: "You do not have permission to perform this review action.",
    SolutionReviewErrorCode.INVALID_STATE: "The Solution Draft is not in the required review state.",
    SolutionReviewErrorCode.STALE: "A stale Solution Draft cannot perform this review action.",
    SolutionReviewErrorCode.MISSING_REVIEWER: "An eligible Solution reviewer is required.",
    SolutionReviewErrorCode.INVALID_REVIEWER: "The selected Solution reviewer is not eligible.",
    SolutionReviewErrorCode.SELF_REVIEW: "A Presales author cannot review their own Solution version.",
    SolutionReviewErrorCode.NO_PENDING_REVIEW: "No pending Solution review exists.",
}


class SolutionReviewError(Exception):
    def __init__(self, code: SolutionReviewErrorCode):
        self.code = code.value
        self.safe_message = _SAFE_MESSAGES[code]
        super().__init__(self.safe_message)


class SolutionReviewPermissionError(SolutionReviewError):
    pass


class SolutionReviewStateError(SolutionReviewError):
    pass


def submit_solution_draft_for_review(
    solution: SolutionDraftRecord,
    *,
    actor,
    reviewer=None,
) -> SolutionReview:
    """Create one pending review and update the Draft projection atomically."""

    solution_id = _saved_pk(solution, SolutionDraftRecord)
    actor = _saved_user(actor)
    reviewer = _optional_saved_user(reviewer)

    with transaction.atomic():
        locked = (
            SolutionDraftRecord.objects.select_for_update(of=("self",))
            .select_related(
                "opportunity__presales_owner",
                "opportunity__sales_owner",
                "created_by",
            )
            .get(pk=solution_id)
        )
        _require_submitter(locked, actor)
        _require_current(locked)
        if locked.review_status != SolutionReviewStatus.DRAFT:
            raise SolutionReviewStateError(SolutionReviewErrorCode.INVALID_STATE)

        selected_reviewer = _resolve_reviewer(locked, actor, reviewer)
        review = SolutionReview.objects.create(
            solution_draft=locked,
            submitted_by=actor,
            reviewer=selected_reviewer,
        )
        locked.review_status = SolutionReviewStatus.PENDING_REVIEW
        locked.save(update_fields=["review_status"])
        return review


def approve_solution_draft(
    solution: SolutionDraftRecord,
    *,
    actor,
    comment: str = "",
) -> SolutionReview:
    """Approve the current pending review and projection atomically."""

    if not isinstance(comment, str):
        raise SolutionReviewStateError(SolutionReviewErrorCode.INVALID_STATE)
    return _decide_solution_review(
        solution,
        actor=actor,
        status=SolutionReviewDecisionStatus.APPROVED,
        return_reason="",
        comment=comment,
    )


def request_solution_draft_revision(
    solution: SolutionDraftRecord,
    *,
    actor,
    return_reason,
    comment: str,
) -> SolutionReview:
    """Return the current review with one exact business reason."""

    if (
        return_reason not in SolutionReturnReason.values
        or not isinstance(comment, str)
        or not comment.strip()
    ):
        raise SolutionReviewStateError(SolutionReviewErrorCode.INVALID_STATE)
    return _decide_solution_review(
        solution,
        actor=actor,
        status=SolutionReviewDecisionStatus.RETURNED,
        return_reason=return_reason,
        comment=comment,
    )


def recover_completed_solution_review(
    solution: SolutionDraftRecord,
    review: SolutionReview,
    *,
    actor,
    expected_status,
    return_reason: str = "",
    comment: str = "",
) -> SolutionReview:
    """Authorize and validate an exact replay without changing audit history."""

    solution_id = _saved_pk(solution, SolutionDraftRecord)
    review_id = _saved_pk(review, SolutionReview)
    actor = _saved_user(actor)
    current_solution = SolutionDraftRecord.objects.select_related("created_by").get(
        pk=solution_id
    )
    current_review = SolutionReview.objects.get(
        pk=review_id,
        solution_draft_id=solution_id,
    )
    _require_decider(current_solution, current_review, actor)
    if current_review.status != expected_status:
        raise SolutionReviewStateError(SolutionReviewErrorCode.INVALID_STATE)
    if expected_status == SolutionReviewDecisionStatus.APPROVED:
        if current_solution.review_status != SolutionReviewStatus.APPROVED:
            raise SolutionReviewStateError(SolutionReviewErrorCode.INVALID_STATE)
    elif expected_status == SolutionReviewDecisionStatus.RETURNED:
        if (
            current_solution.review_status != SolutionReviewStatus.NEEDS_REVISION
            or current_review.return_reason != return_reason
            or current_review.comment != comment
        ):
            raise SolutionReviewStateError(SolutionReviewErrorCode.INVALID_STATE)
    else:
        raise SolutionReviewStateError(SolutionReviewErrorCode.INVALID_STATE)
    return current_review


def recover_pending_solution_review(
    solution: SolutionDraftRecord,
    *,
    actor,
    expected_reviewer=None,
) -> SolutionReview:
    """Authorize and restore one already-committed submit replay."""

    solution_id = _saved_pk(solution, SolutionDraftRecord)
    actor = _saved_user(actor)
    expected_reviewer = _optional_saved_user(expected_reviewer)
    current_solution = (
        SolutionDraftRecord.objects.select_related(
            "opportunity__presales_owner",
            "opportunity__sales_owner",
            "created_by",
        )
        .get(pk=solution_id)
    )
    _require_submitter(current_solution, actor)
    if current_solution.review_status != SolutionReviewStatus.PENDING_REVIEW:
        raise SolutionReviewStateError(SolutionReviewErrorCode.INVALID_STATE)
    current_review = SolutionReview.objects.filter(
        solution_draft_id=solution_id,
        status=SolutionReviewDecisionStatus.PENDING,
    ).first()
    if current_review is None:
        raise SolutionReviewStateError(SolutionReviewErrorCode.NO_PENDING_REVIEW)
    if current_review.submitted_by_id != actor.pk:
        raise SolutionReviewPermissionError(SolutionReviewErrorCode.PERMISSION_DENIED)
    if (
        expected_reviewer is not None
        and current_review.reviewer_id != expected_reviewer.pk
    ):
        raise SolutionReviewStateError(SolutionReviewErrorCode.INVALID_REVIEWER)
    return current_review


def _decide_solution_review(
    solution: SolutionDraftRecord,
    *,
    actor,
    status: SolutionReviewDecisionStatus,
    return_reason: str,
    comment: str,
) -> SolutionReview:
    solution_id = _saved_pk(solution, SolutionDraftRecord)
    actor = _saved_user(actor)
    with transaction.atomic():
        locked = (
            SolutionDraftRecord.objects.select_for_update(of=("self",))
            .select_related("created_by")
            .get(pk=solution_id)
        )
        if locked.review_status != SolutionReviewStatus.PENDING_REVIEW:
            raise SolutionReviewStateError(SolutionReviewErrorCode.INVALID_STATE)
        review = (
            SolutionReview.objects.select_for_update()
            .filter(
                solution_draft=locked,
                status=SolutionReviewDecisionStatus.PENDING,
            )
            .first()
        )
        if review is None:
            raise SolutionReviewStateError(SolutionReviewErrorCode.NO_PENDING_REVIEW)
        _require_decider(locked, review, actor)
        if status == SolutionReviewDecisionStatus.APPROVED:
            _require_current(locked)

        review.status = status
        review.return_reason = return_reason
        review.comment = comment
        review.decided_at = timezone.now()
        review.save(
            update_fields=["status", "return_reason", "comment", "decided_at"]
        )
        locked.review_status = (
            SolutionReviewStatus.APPROVED
            if status == SolutionReviewDecisionStatus.APPROVED
            else SolutionReviewStatus.NEEDS_REVISION
        )
        locked.save(update_fields=["review_status"])
        return review


def _require_submitter(solution: SolutionDraftRecord, actor) -> None:
    opportunity = solution.opportunity
    allowed = (
        actor.role == UserRole.ADMIN
        or actor.role == UserRole.SALES
        and actor.pk == opportunity.sales_owner_id
        or actor.role == UserRole.PRESALES
        and actor.pk == opportunity.presales_owner_id
    )
    if not allowed:
        raise SolutionReviewPermissionError(SolutionReviewErrorCode.PERMISSION_DENIED)


def _resolve_reviewer(solution: SolutionDraftRecord, actor, reviewer):
    opportunity = solution.opportunity
    if actor.role == UserRole.SALES:
        selected = opportunity.presales_owner
        if selected is None:
            raise SolutionReviewStateError(SolutionReviewErrorCode.MISSING_REVIEWER)
        if reviewer is not None and reviewer.pk != selected.pk:
            raise SolutionReviewStateError(SolutionReviewErrorCode.INVALID_REVIEWER)
    elif actor.role == UserRole.PRESALES:
        if solution.created_by_id == actor.pk and reviewer is None:
            raise SolutionReviewStateError(SolutionReviewErrorCode.MISSING_REVIEWER)
        selected = reviewer or actor
    else:
        selected = reviewer or opportunity.presales_owner or actor

    if (
        not selected.is_active
        or selected.role not in {UserRole.PRESALES, UserRole.ADMIN}
    ):
        raise SolutionReviewStateError(SolutionReviewErrorCode.INVALID_REVIEWER)
    if solution.created_by_id == selected.pk:
        raise SolutionReviewStateError(SolutionReviewErrorCode.SELF_REVIEW)
    return selected


def _require_decider(
    solution: SolutionDraftRecord,
    review: SolutionReview,
    actor,
) -> None:
    if actor.role == UserRole.ADMIN:
        if actor.pk == solution.created_by_id:
            raise SolutionReviewPermissionError(SolutionReviewErrorCode.SELF_REVIEW)
        return
    if (
        actor.role != UserRole.PRESALES
        or actor.pk != review.reviewer_id
    ):
        raise SolutionReviewPermissionError(SolutionReviewErrorCode.PERMISSION_DENIED)
    if actor.pk == solution.created_by_id:
        raise SolutionReviewPermissionError(SolutionReviewErrorCode.SELF_REVIEW)


def _require_current(solution: SolutionDraftRecord) -> None:
    reasons = evaluate_solution_draft_stale_reasons(solution)
    if reasons and not solution.is_stale:
        solution.is_stale = True
        solution.stale_at = timezone.now()
        solution.stale_reasons = [reason.value for reason in reasons]
        solution.save(update_fields=["is_stale", "stale_at", "stale_reasons"])
    if solution.is_stale or reasons:
        raise SolutionReviewStateError(SolutionReviewErrorCode.STALE)


def _saved_pk(instance, model) -> int:
    if not isinstance(instance, model) or instance.pk is None or instance._state.adding:
        raise SolutionReviewStateError(SolutionReviewErrorCode.INVALID_STATE)
    return instance.pk


def _saved_user(user):
    user_model = get_user_model()
    if (
        not isinstance(user, user_model)
        or user.pk is None
        or user._state.adding
        or not user.is_active
    ):
        raise SolutionReviewPermissionError(SolutionReviewErrorCode.PERMISSION_DENIED)
    current = user_model.objects.filter(pk=user.pk, is_active=True).first()
    if current is None:
        raise SolutionReviewPermissionError(SolutionReviewErrorCode.PERMISSION_DENIED)
    return current


def _optional_saved_user(user):
    if user is None:
        return None
    return _saved_user(user)
