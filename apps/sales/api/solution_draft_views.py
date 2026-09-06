"""Phase 5.6a immutable Solution Draft create/list/detail endpoints."""

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

from .opportunity_access import OpportunityVisibilityMixin, visible_opportunities_for
from .pagination import DefaultPageNumberPagination
from .permissions import SolutionDraftPermission
from .solution_draft_serializers import (
    SolutionDraftCreateSerializer,
    SolutionDraftDetailSerializer,
    SolutionDraftListSerializer,
)


class SolutionDraftAPIError(APIException):
    status_code = 422
    default_code = "solution_draft_not_persisted"
    default_detail = "The Solution Draft could not be persisted."


class SolutionDraftProviderAPIError(APIException):
    status_code = 502
    default_code = "llm_provider_error"
    default_detail = "The language-model provider request failed."


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
    http_method_names = ["get", "head", "options"]
    lookup_field = "pk"
    lookup_url_kwarg = "solution_id"

    def get_queryset(self):
        return (
            SolutionDraftRecord.objects.filter(
                opportunity__in=visible_opportunities_for(self.request.user)
            )
            .select_related("created_by", "requirement_analysis", "opportunity")
            .prefetch_related("provenance_entries")
        )

    def retrieve_draft(self, request, *args, **kwargs):
        record = self.get_object()
        refresh_solution_draft_staleness(record)
        return Response(SolutionDraftDetailSerializer(record).data)
