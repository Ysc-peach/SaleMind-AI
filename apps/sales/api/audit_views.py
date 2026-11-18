"""Read-only operator view of review and generation history.

The business tables already record who submitted, decided and generated; what
was missing was one place to read them together. The endpoint stays read-only
and bounded: it serves one page at a time and never writes, so it remains a
diagnostic view rather than a second source of truth.
"""

from django.db.models import Q
from django.utils.dateparse import parse_date
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import BasePermission
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.models import UserRole
from apps.sales.models import (
    SolutionGenerationJob,
    SolutionGenerationJobStatus,
    SolutionReview,
    SolutionReviewDecisionStatus,
)

from .serializers import user_display_name

DEFAULT_PAGE_SIZE = 20
MAX_PAGE_SIZE = 100

_REVIEW_STATUSES = {value.upper() for value in SolutionReviewDecisionStatus.values}
_JOB_STATUSES = {value.upper() for value in SolutionGenerationJobStatus.values}
_ALL_STATUSES = _REVIEW_STATUSES | _JOB_STATUSES


class AuditPermission(BasePermission):
    """Only the business Admin role may read the audit trail."""

    def has_permission(self, request, view):
        return bool(
            request.user.is_authenticated
            and request.user.role == UserRole.ADMIN
        )


def _positive_int(params, name: str, default: int, maximum: int | None = None) -> int:
    raw = params.get(name)
    if raw in (None, ""):
        return default
    try:
        value = int(raw)
    except (TypeError, ValueError):
        raise ValidationError({name: "Expected a positive integer."}) from None
    if value < 1:
        raise ValidationError({name: "Expected a positive integer."})
    if maximum is not None and value > maximum:
        raise ValidationError({name: f"Must be at most {maximum}."})
    return value


def _optional_date(params, name: str):
    raw = params.get(name)
    if raw in (None, ""):
        return None
    value = parse_date(raw)
    if value is None:
        raise ValidationError({name: "Expected an ISO date (YYYY-MM-DD)."})
    return value


def _actor_q(prefix: str, actor: str) -> Q:
    """Match one person exactly, by username or either part of their name.

    Substring matching on the username made `zhangsan` also return
    `zhangsanfeng`, which turns an audit answer into a guess, and it never
    matched the Chinese name the table actually displays.
    """

    return (
        Q(**{f"{prefix}__username__iexact": actor})
        | Q(**{f"{prefix}__first_name": actor})
        | Q(**{f"{prefix}__last_name": actor})
    )


def _reviews(*, actor: str, status: str, start, end):
    queryset = SolutionReview.objects.select_related(
        "solution_draft__opportunity",
        "submitted_by",
        "reviewer",
    )
    if actor:
        # Either side of the review counts as the actor, so an operator can ask
        # "what did this person submit or decide".
        queryset = queryset.filter(
            _actor_q("submitted_by", actor) | _actor_q("reviewer", actor)
        )
    if status:
        queryset = queryset.filter(status=status.lower())
    if start is not None:
        queryset = queryset.filter(submitted_at__date__gte=start)
    if end is not None:
        queryset = queryset.filter(submitted_at__date__lte=end)
    return queryset.order_by("-submitted_at", "-id")


def _generations(*, actor: str, status: str, start, end):
    queryset = SolutionGenerationJob.objects.select_related(
        "opportunity",
        "requested_by",
    )
    if actor:
        queryset = queryset.filter(_actor_q("requested_by", actor))
    if status:
        queryset = queryset.filter(status=status.lower())
    if start is not None:
        queryset = queryset.filter(created_at__date__gte=start)
    if end is not None:
        queryset = queryset.filter(created_at__date__lte=end)
    return queryset.order_by("-created_at", "-id")


def _review_row(review) -> dict:
    return {
        "id": review.pk,
        "opportunity_id": review.solution_draft.opportunity_id,
        "project_name": review.solution_draft.opportunity.project_name,
        "submitted_by": user_display_name(review.submitted_by),
        "reviewer": user_display_name(review.reviewer),
        "status": review.status.upper(),
        "return_reason": review.return_reason,
        "submitted_at": review.submitted_at,
        "decided_at": review.decided_at,
    }


def _generation_row(job) -> dict:
    return {
        "id": job.pk,
        "opportunity_id": job.opportunity_id,
        "project_name": job.opportunity.project_name,
        "requested_by": user_display_name(job.requested_by),
        "status": job.status.upper(),
        "error_code": job.error_code,
        "created_at": job.created_at,
        "finished_at": job.finished_at,
    }


class AuditEventsAPIView(APIView):
    permission_classes = (AuditPermission,)
    http_method_names = ["get", "head", "options"]

    def get(self, request):
        params = request.query_params
        page = _positive_int(params, "page", 1)
        page_size = _positive_int(
            params, "page_size", DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE
        )
        actor = (params.get("actor") or "").strip()
        status = (params.get("status") or "").strip().upper()
        if status and status not in _ALL_STATUSES:
            raise ValidationError({"status": "Unknown audit status."})
        start = _optional_date(params, "date_from")
        end = _optional_date(params, "date_to")
        if start and end and start > end:
            raise ValidationError({"date_to": "Must not be before date_from."})

        offset = (page - 1) * page_size
        reviews = _reviews(actor=actor, status=status, start=start, end=end)
        generations = _generations(
            actor=actor, status=status, start=start, end=end
        )

        return Response(
            {
                "page": page,
                "page_size": page_size,
                "filters": {
                    "actor": actor,
                    "status": status,
                    "date_from": start.isoformat() if start else None,
                    "date_to": end.isoformat() if end else None,
                },
                # Two independent histories are paged with one cursor: each list
                # reports its own total so the caller can show "3 of 17".
                "reviews": {
                    "count": reviews.count(),
                    "results": [
                        _review_row(review)
                        for review in reviews[offset:offset + page_size]
                    ],
                },
                "generations": {
                    "count": generations.count(),
                    "results": [
                        _generation_row(job)
                        for job in generations[offset:offset + page_size]
                    ],
                },
            }
        )
