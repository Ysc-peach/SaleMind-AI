"""Immutable Solution Draft persistence and review workflow endpoints."""

from django.contrib.auth import get_user_model
from rest_framework import status, viewsets
from rest_framework.exceptions import APIException, ValidationError
from rest_framework.parsers import JSONParser
from rest_framework.response import Response

from apps.llm.exceptions import LLMProviderError
from apps.sales.models import OpportunityRequirementAnalysis, SolutionDraftRecord
from apps.sales.services.solution_errors import SolutionDraftError
from apps.sales.services.solution_persistence import (
    SolutionPersistenceError,
    generate_and_persist_solution_draft,
    refresh_solution_draft_staleness,
)
from apps.sales.services.solution_review import (
    SolutionReviewPermissionError,
    SolutionReviewStateError,
    approve_solution_draft,
    request_solution_draft_revision,
    submit_solution_draft_for_review,
)

from .opportunity_access import OpportunityVisibilityMixin, visible_solution_drafts_for
from .pagination import DefaultPageNumberPagination
from .permissions import SolutionDraftPermission
from .solution_draft_serializers import (
    SolutionDraftCreateSerializer,
    SolutionDraftDetailSerializer,
    SolutionDraftListSerializer,
    SolutionReviewApproveSerializer,
    SolutionReviewReturnSerializer,
    SolutionReviewSerializer,
    SolutionReviewSubmitSerializer,
)


class SolutionDraftAPIError(APIException):
    status_code = 422
    default_code = "solution_draft_not_persisted"
    default_detail = "The Solution Draft could not be persisted."


class SolutionDraftProviderAPIError(APIException):
    status_code = 502
    default_code = "llm_provider_error"
    default_detail = "The language-model provider request failed."


class SolutionReviewActionAPIError(APIException):
    def __init__(self, error):
        self.status_code = (
            403 if isinstance(error, SolutionReviewPermissionError) else 409
        )
        super().__init__({"code": error.code, "message": error.safe_message})


class SolutionDraftCollectionViewSet(OpportunityVisibilityMixin, viewsets.GenericViewSet):
    permission_classes = (SolutionDraftPermission,)
    parser_classes = (JSONParser,)
    pagination_class = DefaultPageNumberPagination
    lookup_url_kwarg = "opportunity_id"
    http_method_names = ["get", "post", "head", "options"]

    def list_drafts(self, request, *args, **kwargs):
        opportunity = self.get_object()
        records = list(
            SolutionDraftRecord.objects.filter(opportunity=opportunity)
            .select_related("created_by", "requirement_analysis")
            .order_by("-version", "-id")
        )
        for record in records:
            refresh_solution_draft_staleness(record)
        page = self.paginate_queryset(records)
        serializer = SolutionDraftListSerializer(page, many=True)
        return self.get_paginated_response(serializer.data)

    def create_draft(self, request, *args, **kwargs):
        opportunity = self.get_object()
        serializer = SolutionDraftCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        analysis = OpportunityRequirementAnalysis.objects.filter(
            pk=serializer.validated_data["analysis_id"],
            opportunity=opportunity,
        ).first()
        if analysis is None:
            raise ValidationError({"analysis_id": "The analysis does not belong to this opportunity."})
        try:
            record = generate_and_persist_solution_draft(
                opportunity,
                analysis,
                created_by=request.user,
            )
        except SolutionPersistenceError as exc:
            raise SolutionDraftAPIError() from exc
        except SolutionDraftError as exc:
            raise SolutionDraftAPIError(
                detail={"code": exc.code, "message": exc.safe_message}
            ) from exc
        except LLMProviderError as exc:
            raise SolutionDraftProviderAPIError(
                detail={"code": exc.code, "message": exc.safe_message}
            ) from exc
        return Response(
            SolutionDraftDetailSerializer(record).data,
            status=status.HTTP_201_CREATED,
        )


class SolutionDraftDetailViewSet(viewsets.GenericViewSet):
    permission_classes = (SolutionDraftPermission,)
    parser_classes = (JSONParser,)
    http_method_names = ["get", "post", "head", "options"]
    lookup_field = "pk"
    lookup_url_kwarg = "solution_id"

    def get_queryset(self):
        return (
            visible_solution_drafts_for(self.request.user)
            .select_related("created_by", "requirement_analysis", "opportunity")
            .prefetch_related("provenance_entries")
        )

    def retrieve_draft(self, request, *args, **kwargs):
        record = self.get_object()
        refresh_solution_draft_staleness(record)
        return Response(SolutionDraftDetailSerializer(record).data)

    def submit_review(self, request, *args, **kwargs):
        record = self.get_object()
        serializer = SolutionReviewSubmitSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        reviewer = None
        reviewer_id = serializer.validated_data.get("reviewer_id")
        if reviewer_id is not None:
            reviewer = get_user_model().objects.filter(pk=reviewer_id).first()
            if reviewer is None:
                raise ValidationError({"reviewer_id": "The reviewer does not exist."})
        try:
            review = submit_solution_draft_for_review(
                record,
                actor=request.user,
                reviewer=reviewer,
            )
        except (SolutionReviewPermissionError, SolutionReviewStateError) as exc:
            raise SolutionReviewActionAPIError(exc) from exc
        return Response(SolutionReviewSerializer(review).data, status=status.HTTP_201_CREATED)

    def approve_review(self, request, *args, **kwargs):
        record = self.get_object()
        serializer = SolutionReviewApproveSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            review = approve_solution_draft(
                record,
                actor=request.user,
                comment=serializer.validated_data["comment"],
            )
        except (SolutionReviewPermissionError, SolutionReviewStateError) as exc:
            raise SolutionReviewActionAPIError(exc) from exc
        return Response(SolutionReviewSerializer(review).data)

    def request_revision(self, request, *args, **kwargs):
        record = self.get_object()
        serializer = SolutionReviewReturnSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            review = request_solution_draft_revision(
                record,
                actor=request.user,
                return_reason=serializer.validated_data["return_reason"],
                comment=serializer.validated_data["comment"],
            )
        except (SolutionReviewPermissionError, SolutionReviewStateError) as exc:
            raise SolutionReviewActionAPIError(exc) from exc
        return Response(SolutionReviewSerializer(review).data)

    def review_history(self, request, *args, **kwargs):
        record = self.get_object()
        reviews = record.reviews.select_related("submitted_by", "reviewer").all()
        return Response({"results": SolutionReviewSerializer(reviews, many=True).data})
