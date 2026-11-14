"""Read-only operator view of review and generation history.

The business tables already record who submitted, decided and generated; what
was missing was one place to read them together. This endpoint is deliberately
read-only and capped, so it stays a diagnostic view rather than a new source of
truth.
"""

from rest_framework.permissions import BasePermission
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.models import UserRole
from apps.sales.models import SolutionGenerationJob, SolutionReview

from .serializers import user_display_name

_RECENT_LIMIT = 50


class AuditPermission(BasePermission):
    """Only the business Admin role may read the audit trail."""

    def has_permission(self, request, view):
        return bool(
            request.user.is_authenticated
            and request.user.role == UserRole.ADMIN
        )


class AuditEventsAPIView(APIView):
    permission_classes = (AuditPermission,)
    http_method_names = ["get", "head", "options"]

    def get(self, request):
        reviews = SolutionReview.objects.select_related(
            "solution_draft__opportunity",
            "submitted_by",
            "reviewer",
        ).order_by("-submitted_at", "-id")[:_RECENT_LIMIT]
        generations = SolutionGenerationJob.objects.select_related(
            "opportunity",
            "requested_by",
        ).order_by("-created_at", "-id")[:_RECENT_LIMIT]

        return Response(
            {
                "reviews": [
                    {
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
                    for review in reviews
                ],
                "generations": [
                    {
                        "id": job.pk,
                        "opportunity_id": job.opportunity_id,
                        "project_name": job.opportunity.project_name,
                        "requested_by": user_display_name(job.requested_by),
                        "status": job.status.upper(),
                        "error_code": job.error_code,
                        "created_at": job.created_at,
                        "finished_at": job.finished_at,
                    }
                    for job in generations
                ],
                "limit": _RECENT_LIMIT,
            }
        )
