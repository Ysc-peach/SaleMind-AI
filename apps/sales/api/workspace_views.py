"""Small read-only projections that make role work discoverable."""

from django.db.models import OuterRef, Subquery
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.sales.models import (
    SolutionDraftRecord,
    SolutionReturnReason,
    SolutionReview,
    SolutionReviewDecisionStatus,
    SolutionReviewStatus,
)

from apps.sales.services.visibility import visible_opportunities_for
from .permissions import ReviewerInboxPermission, SalesWorkspacePermission
from .serializers import OpportunityListSerializer, user_display_name


_SECTION_LIMIT = 10


def _drafts_with_latest_review():
    latest = SolutionReview.objects.filter(solution_draft_id=OuterRef("pk")).order_by(
        "-submitted_at", "-id"
    )
    return SolutionDraftRecord.objects.select_related(
        "opportunity__customer",
        "opportunity__sales_owner",
        "opportunity__presales_owner",
    ).annotate(
        latest_review_id=Subquery(latest.values("id")[:1]),
        latest_return_reason=Subquery(latest.values("return_reason")[:1]),
        latest_review_at=Subquery(latest.values("decided_at")[:1]),
    )


def _draft_task(draft, status):
    opportunity = draft.opportunity
    return {
        "solution_draft_id": draft.pk,
        "opportunity_id": opportunity.pk,
        "project_name": opportunity.project_name,
        "customer_name": opportunity.customer.name,
        "solution_version": draft.version,
        "workflow_id": (
            str(draft.generation_idempotency_key)
            if draft.generation_idempotency_key
            else None
        ),
        "status": status,
        "updated_at": draft.latest_review_at or draft.created_at,
    }


def _review_item(review, status):
    draft = review.solution_draft
    opportunity = draft.opportunity
    return {
        "review_id": review.pk,
        "solution_draft_id": draft.pk,
        "opportunity_id": opportunity.pk,
        "project_name": opportunity.project_name,
        "customer_name": opportunity.customer.name,
        "solution_version": draft.version,
        "sales_owner_name": user_display_name(opportunity.sales_owner),
        "status": status,
        "return_reason": review.return_reason,
        "comment": review.comment,
        "submitted_at": review.submitted_at,
        "decided_at": review.decided_at,
    }


class SalesWorkspaceAPIView(APIView):
    permission_classes = (SalesWorkspacePermission,)
    http_method_names = ["get", "head", "options"]

    def get(self, request):
        opportunities = list(visible_opportunities_for(request.user)[:_SECTION_LIMIT])
        drafts = _drafts_with_latest_review().filter(
            opportunity__sales_owner=request.user
        )
        waiting_confirmation = drafts.filter(
            review_status=SolutionReviewStatus.DRAFT,
            generation_idempotency_key__isnull=False,
        ).order_by("-created_at", "-id")[:_SECTION_LIMIT]
        waiting_review = drafts.filter(
            review_status=SolutionReviewStatus.PENDING_REVIEW
        ).order_by("-created_at", "-id")[:_SECTION_LIMIT]
        customer_info = drafts.filter(
            review_status=SolutionReviewStatus.NEEDS_REVISION,
            latest_return_reason=SolutionReturnReason.CUSTOMER_INFO_REQUIRED,
        ).order_by("-latest_review_at", "-id")[:_SECTION_LIMIT]
        serialized = OpportunityListSerializer(
            opportunities,
            many=True,
            context={"request": request},
        ).data
        return Response(
            {
                "my_opportunities": serialized,
                "tasks": {
                    "customer_info_required": [
                        _draft_task(item, "CUSTOMER_INFO_REQUIRED")
                        for item in customer_info
                    ],
                    "waiting_for_sales_confirmation": [
                        _draft_task(item, "WAITING_FOR_SALES_CONFIRMATION")
                        for item in waiting_confirmation
                    ],
                    "waiting_for_presales_review": [
                        _draft_task(item, "WAITING_FOR_PRESALES_REVIEW")
                        for item in waiting_review
                    ],
                },
                "recently_updated": serialized,
            }
        )


class ReviewerInboxAPIView(APIView):
    permission_classes = (ReviewerInboxPermission,)
    http_method_names = ["get", "head", "options"]

    def get(self, request):
        reviews = SolutionReview.objects.select_related(
            "solution_draft__opportunity__customer",
            "solution_draft__opportunity__sales_owner",
        )
        pending = reviews.filter(
            reviewer=request.user,
            status=SolutionReviewDecisionStatus.PENDING,
        ).order_by("submitted_at", "id")[:_SECTION_LIMIT]
        recent = reviews.filter(reviewer=request.user).exclude(
            status=SolutionReviewDecisionStatus.PENDING
        ).order_by("-decided_at", "-id")[:_SECTION_LIMIT]

        revision_drafts = _drafts_with_latest_review().filter(
            opportunity__presales_owner=request.user,
            review_status=SolutionReviewStatus.NEEDS_REVISION,
            latest_return_reason=SolutionReturnReason.TECHNICAL_REVISION_REQUIRED,
        ).order_by("-latest_review_at", "-id")[:_SECTION_LIMIT]
        revision_review_ids = [draft.latest_review_id for draft in revision_drafts]
        revision_reviews = {
            review.pk: review
            for review in reviews.filter(pk__in=revision_review_ids)
        }

        return Response(
            {
                "pending_reviews": [
                    _review_item(item, "WAITING_FOR_PRESALES_REVIEW")
                    for item in pending
                ],
                "technical_revisions": [
                    _review_item(
                        revision_reviews[draft.latest_review_id],
                        "TECHNICAL_REVISION_REQUIRED",
                    )
                    for draft in revision_drafts
                ],
                "recent_reviews": [
                    _review_item(item, item.status.upper()) for item in recent
                ],
            }
        )


class ReviewSummaryAPIView(APIView):
    """Counters for the navigation badge.

    The inbox caps every section at ten items, so its length cannot answer "how
    many are waiting". This endpoint runs two COUNT queries and returns nothing
    the caller would otherwise have to download.
    """

    permission_classes = (ReviewerInboxPermission,)
    http_method_names = ["get", "head", "options"]

    def get(self, request):
        pending = SolutionReview.objects.filter(
            reviewer=request.user,
            status=SolutionReviewDecisionStatus.PENDING,
        ).count()
        revisions = _drafts_with_latest_review().filter(
            opportunity__presales_owner=request.user,
            review_status=SolutionReviewStatus.NEEDS_REVISION,
            latest_return_reason=SolutionReturnReason.TECHNICAL_REVISION_REQUIRED,
        ).count()
        return Response(
            {
                "pending_reviews": pending,
                "technical_revisions": revisions,
                "total": pending + revisions,
            }
        )
