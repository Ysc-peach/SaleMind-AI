"""HTTP adaptation of existing analysis services under Opportunity visibility."""

import logging
from dataclasses import asdict

from rest_framework import viewsets
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.parsers import JSONParser
from rest_framework.response import Response

from config.throttling import ScopedActionThrottleMixin
from apps.llm.exceptions import LLMErrorCode, LLMProviderError, LLMProviderFailureKind
from apps.sales.services.requirement_analysis import (
    RequirementAnalysisContractFailure, RequirementAnalysisError, RequirementAnalysisErrorCode,
)
from apps.sales.services import requirement_analysis_history as history

from .opportunity_access import OpportunityVisibilityMixin
from .pagination import DefaultPageNumberPagination
from .permissions import OpportunityPermission
from .requirement_analysis_errors import HTTP_ERRORS, RequirementAnalysisAPIError
from .requirement_analysis_serializers import (
    EmptyAnalysisRequestSerializer,
    RequirementAnalysisDetailSerializer,
    RequirementAnalysisListSerializer,
)

logger = logging.getLogger(__name__)


class RequirementAnalysisViewSet(
    ScopedActionThrottleMixin,
    OpportunityVisibilityMixin,
    viewsets.GenericViewSet,
):
    """Derived analysis actions use Opportunity read access, not mutation access.

    Action names deliberately differ from Opportunity create/partial_update;
    the existing permission then permits all three valid business roles while
    the shared filtered queryset still enforces object visibility.
    """

    permission_classes = (OpportunityPermission,)
    parser_classes = (JSONParser,)
    http_method_names = ["get", "post", "head", "options"]
    scoped_throttle_actions = {"analyze": "requirement_analysis"}
    lookup_url_kwarg = "opportunity_id"
    serializer_class = RequirementAnalysisDetailSerializer
    pagination_class = DefaultPageNumberPagination

    def get_serializer_class(self):
        if self.action == "history":
            return RequirementAnalysisListSerializer
        return RequirementAnalysisDetailSerializer

    def analyze(self, request, *args, **kwargs):
        opportunity = self.get_object()
        try:
            request_data = request.data
        except RecursionError:
            # JSONParser handles ValueError, but deeply nested input can also
            # exceed the decoder recursion limit. This is still invalid HTTP input.
            raise ValidationError() from None
        serializer = EmptyAnalysisRequestSerializer(data=request_data)
        if not serializer.is_valid():
            raise ValidationError()
        record = history.create_opportunity_requirement_analysis(opportunity, created_by=request.user)
        return Response(self.get_serializer(record).data, status=201)

    def history(self, request, *args, **kwargs):
        records = history.list_opportunity_requirement_analyses(self.get_object())
        page = self.paginate_queryset(records)
        return self.get_paginated_response(self.get_serializer(page, many=True).data)

    def latest(self, request, *args, **kwargs):
        record = history.get_latest_opportunity_requirement_analysis(self.get_object())
        if record is None:
            raise NotFound()
        return Response(self.get_serializer(record).data)

    def retrieve_analysis(self, request, *args, **kwargs):
        # Resolve the authorized parent first, then select only its own history.
        records = history.list_opportunity_requirement_analyses(self.get_object())
        record = next((item for item in records if item.pk == self.kwargs["analysis_id"]), None)
        if record is None:
            raise NotFound()
        return Response(self.get_serializer(record).data)

    def handle_exception(self, exc):
        if isinstance(exc, (RequirementAnalysisError, LLMProviderError)):
            # Fixed categories only: never stringify exceptions or their causes,
            # log tracebacks, or include customer text/provider response bodies.
            if isinstance(exc, RequirementAnalysisError):
                category = (
                    "invalid_analysis_input"
                    if exc.code == RequirementAnalysisErrorCode.INVALID_INPUT
                    else "invalid_analysis_response"
                )
                provider_status = None
            else:
                category = (
                    exc.failure_kind.value
                    if isinstance(exc.failure_kind, LLMProviderFailureKind)
                    else "unknown_provider_error"
                )
                provider_status = exc.http_status
            diagnostic = {
                "stage": "requirement_analysis", "code": exc.code,
                "category": category, "http_status": provider_status,
            }
            logger.warning(
                "Requirement analysis failed: stage=%s code=%s category=%s provider_http_status=%s",
                diagnostic["stage"], diagnostic["code"], category, provider_status,
                extra={"analysis_failure": diagnostic},
            )
            if isinstance(exc, RequirementAnalysisError) and isinstance(
                exc.contract_failure, RequirementAnalysisContractFailure,
            ):
                contract = asdict(exc.contract_failure)
                logger.warning(
                    "Requirement analysis contract rejected: category=%s path=%s expected=%s actual=%s",
                    contract["category"], contract["json_path"], contract["expected"], contract["actual"],
                    extra={"analysis_contract_failure": contract},
                )
        if isinstance(exc, RequirementAnalysisError):
            error_status = 400 if exc.code == RequirementAnalysisErrorCode.INVALID_INPUT else 502
            exc = RequirementAnalysisAPIError(exc.code, exc.safe_message, status_code=error_status)
        elif isinstance(exc, LLMProviderError):
            error_status = 503 if exc.code in (
                LLMErrorCode.LLM_NOT_CONFIGURED, LLMErrorCode.UNSUPPORTED_LLM_PROVIDER,
            ) else 502
            exc = RequirementAnalysisAPIError(exc.code, exc.safe_message, status_code=error_status)
        response = super().handle_exception(exc)
        if not isinstance(exc, RequirementAnalysisAPIError) and response.status_code in HTTP_ERRORS:
            code, message = HTTP_ERRORS[response.status_code]
            response.data = {"code": code, "message": message}
        return response
