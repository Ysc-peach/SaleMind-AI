"""Case library endpoints.

Reads are open to every business role; writes are refused for sellers inside the
service, so the rule holds even if a future view forgets to check.
"""

from rest_framework import status, viewsets
from rest_framework.exceptions import NotFound, PermissionDenied, ValidationError
from rest_framework.parsers import JSONParser
from rest_framework.response import Response
from rest_framework.views import APIView

from config.throttling import ScopedActionThrottleMixin

from apps.accounts.models import UserRole
from apps.sales.models import CaseStudy, CaseStudySizeBand
from apps.sales.services import case_studies as service
from apps.sales.services.case_studies import CaseStudyError, CaseStudyErrorCode

from .case_study_serializers import (
    CaseStudyCreateSerializer,
    CaseStudySerializer,
    CaseStudyUpdateSerializer,
)
from .pagination import DefaultPageNumberPagination
from .permissions import SolutionDraftPermission


def _translate(error: CaseStudyError):
    if error.code == CaseStudyErrorCode.FORBIDDEN:
        raise PermissionDenied("只有售前或管理员可以维护案例库。")
    raise ValidationError({"detail": "案例信息不完整或超出长度限制。"})


def _boolean(params, name: str) -> bool | None:
    raw = (params.get(name) or "").strip().lower()
    if raw in {"", "all"}:
        return None
    if raw in {"1", "true", "yes"}:
        return True
    if raw in {"0", "false", "no"}:
        return False
    raise ValidationError({name: "Expected true or false."})


class CaseStudyViewSet(
    ScopedActionThrottleMixin, viewsets.GenericViewSet
):
    permission_classes = (SolutionDraftPermission,)
    parser_classes = (JSONParser,)
    pagination_class = DefaultPageNumberPagination
    http_method_names = ["get", "post", "patch", "head", "options"]

    def list_cases(self, request, *args, **kwargs):
        params = request.query_params
        size_band = (params.get("size_band") or "").strip()
        if size_band and size_band not in CaseStudySizeBand.values:
            raise ValidationError({"size_band": "Unknown size band."})
        include_inactive = _boolean(params, "include_inactive") is True
        if include_inactive and request.user.role != UserRole.ADMIN:
            raise PermissionDenied("只有管理员可以查看已停用的案例。")
        queryset = service.list_cases(
            industry=(params.get("industry") or "").strip(),
            size_band=size_band,
            referenceable=_boolean(params, "referenceable"),
            search=(params.get("q") or "").strip(),
            include_inactive=include_inactive,
        )
        page = self.paginate_queryset(queryset)
        return self.get_paginated_response(
            CaseStudySerializer(page, many=True).data
        )

    def create_case(self, request, *args, **kwargs):
        serializer = CaseStudyCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            case = service.create_case(
                actor=request.user, **serializer.validated_data
            )
        except CaseStudyError as error:
            _translate(error)
        return Response(
            CaseStudySerializer(case).data, status=status.HTTP_201_CREATED
        )

    def _case(self) -> CaseStudy:
        case = CaseStudy.objects.filter(pk=self.kwargs["pk"]).first()
        if case is None:
            raise NotFound()
        return case

    def partial_update(self, request, *args, **kwargs):
        case = self._case()
        serializer = CaseStudyUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            case = service.update_case(
                case, actor=request.user, **serializer.validated_data
            )
        except CaseStudyError as error:
            _translate(error)
        return Response(CaseStudySerializer(case).data)

    def archive(self, request, *args, **kwargs):
        return self._set_active(request, False)

    def restore(self, request, *args, **kwargs):
        return self._set_active(request, True)

    def _set_active(self, request, active: bool):
        case = self._case()
        try:
            case = service.set_case_active(
                case, actor=request.user, active=active
            )
        except CaseStudyError as error:
            _translate(error)
        return Response(CaseStudySerializer(case).data)


class CaseStudyMatchAPIView(APIView):
    """Cases ordered by resemblance, not filtered by it."""

    permission_classes = (SolutionDraftPermission,)
    http_method_names = ["get", "head", "options"]

    def get(self, request):
        params = request.query_params
        size_band = (params.get("size_band") or "").strip()
        if size_band and size_band not in CaseStudySizeBand.values:
            raise ValidationError({"size_band": "Unknown size band."})
        raw_limit = (params.get("limit") or "").strip()
        try:
            limit = int(raw_limit) if raw_limit else service.DEFAULT_MATCH_LIMIT
        except ValueError:
            raise ValidationError({"limit": "Expected an integer."}) from None
        if limit < 1 or limit > 20:
            raise ValidationError({"limit": "Must be between 1 and 20."})
        cases = service.match_cases(
            industry=(params.get("industry") or "").strip(),
            size_band=size_band,
            limit=limit,
        )
        return Response({"results": CaseStudySerializer(cases, many=True).data})
