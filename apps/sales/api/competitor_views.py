"""Competitor endpoints.

Reading is open to every business role; registering a claim is limited to
presales and administrators, and only an administrator can approve one. The
service enforces all three, so a view that forgets to check cannot widen them.
"""

from rest_framework import status, viewsets
from rest_framework.exceptions import APIException, NotFound, PermissionDenied, ValidationError
from rest_framework.parsers import JSONParser
from rest_framework.response import Response

from config.throttling import ScopedActionThrottleMixin

from apps.accounts.models import UserRole
from apps.sales.models import Competitor, CompetitorDimension, CompetitorStatement
from apps.sales.services import competitors as service
from apps.sales.services.competitors import CompetitorError, CompetitorErrorCode

from .competitor_serializers import (
    CompetitorCreateSerializer,
    CompetitorSerializer,
    CompetitorStatementCreateSerializer,
    CompetitorStatementSerializer,
    CompetitorUpdateSerializer,
)
from .pagination import DefaultPageNumberPagination
from .permissions import SolutionDraftPermission


class CompetitorNegativeClaim(APIException):
    status_code = 400
    default_detail = (
        "不允许登记对第三方的否定断言（例如「不支持」「未提供」）。"
        "请改为引用竞品自己公开宣称的内容，并附来源链接。"
    )
    default_code = "competitor_negative_claim"


def _translate(error: CompetitorError):
    if error.code == CompetitorErrorCode.FORBIDDEN:
        raise PermissionDenied("只有售前或管理员可以维护竞品资料。")
    if error.code == CompetitorErrorCode.NEGATIVE_CLAIM:
        raise CompetitorNegativeClaim()
    if error.code == CompetitorErrorCode.DUPLICATE_NAME:
        raise ValidationError({"name": "同名竞品已存在。"})
    if error.code == CompetitorErrorCode.INVALID_STATE:
        raise ValidationError({"status": "该陈述的当前状态不允许此操作。"})
    raise ValidationError({"detail": "竞品信息不完整或超出长度限制。"})


class CompetitorViewSet(
    ScopedActionThrottleMixin, viewsets.GenericViewSet
):
    permission_classes = (SolutionDraftPermission,)
    parser_classes = (JSONParser,)
    pagination_class = DefaultPageNumberPagination
    http_method_names = ["get", "post", "patch", "head", "options"]

    def list_competitors(self, request, *args, **kwargs):
        queryset = Competitor.objects.all()
        include_inactive = (
            (request.query_params.get("include_inactive") or "").lower()
            in {"1", "true", "yes"}
        )
        if include_inactive:
            if request.user.role != UserRole.ADMIN:
                raise PermissionDenied("只有管理员可以查看已停用的竞品。")
        else:
            queryset = queryset.filter(is_active=True)
        search = (request.query_params.get("q") or "").strip()
        if search:
            queryset = queryset.filter(name__icontains=search)
        page = self.paginate_queryset(queryset)
        return self.get_paginated_response(
            CompetitorSerializer(page, many=True).data
        )

    def create_competitor(self, request, *args, **kwargs):
        serializer = CompetitorCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            competitor = service.create_competitor(
                actor=request.user, **serializer.validated_data
            )
        except CompetitorError as error:
            _translate(error)
        return Response(
            CompetitorSerializer(competitor).data,
            status=status.HTTP_201_CREATED,
        )

    def _competitor(self) -> Competitor:
        competitor = Competitor.objects.filter(pk=self.kwargs["pk"]).first()
        if competitor is None:
            raise NotFound()
        return competitor

    def partial_update(self, request, *args, **kwargs):
        competitor = self._competitor()
        serializer = CompetitorUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            competitor = service.update_competitor(
                competitor, actor=request.user, **serializer.validated_data
            )
        except CompetitorError as error:
            _translate(error)
        return Response(CompetitorSerializer(competitor).data)

    def archive(self, request, *args, **kwargs):
        return self._set_active(request, False)

    def restore(self, request, *args, **kwargs):
        return self._set_active(request, True)

    def _set_active(self, request, active: bool):
        competitor = self._competitor()
        try:
            competitor = service.set_competitor_active(
                competitor, actor=request.user, active=active
            )
        except CompetitorError as error:
            _translate(error)
        return Response(CompetitorSerializer(competitor).data)


class CompetitorStatementViewSet(
    ScopedActionThrottleMixin, viewsets.GenericViewSet
):
    permission_classes = (SolutionDraftPermission,)
    parser_classes = (JSONParser,)
    pagination_class = DefaultPageNumberPagination
    lookup_url_kwarg = "competitor_id"
    http_method_names = ["get", "post", "head", "options"]

    def _competitor(self) -> Competitor:
        competitor = Competitor.objects.filter(
            pk=self.kwargs["competitor_id"]
        ).first()
        if competitor is None:
            raise NotFound()
        return competitor

    def list_statements(self, request, *args, **kwargs):
        competitor = self._competitor()
        dimension = (request.query_params.get("dimension") or "").strip()
        if dimension and dimension not in CompetitorDimension.values:
            raise ValidationError({"dimension": "Unknown dimension."})
        status_filter = (request.query_params.get("status") or "").strip()
        if status_filter and status_filter not in {
            "proposed", "approved", "rejected"
        }:
            raise ValidationError({"status": "Unknown status."})
        queryset = service.list_statements(
            competitor=competitor, dimension=dimension, status=status_filter
        )
        page = self.paginate_queryset(queryset)
        return self.get_paginated_response(
            CompetitorStatementSerializer(page, many=True).data
        )

    def create_statement(self, request, *args, **kwargs):
        competitor = self._competitor()
        serializer = CompetitorStatementCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            statement = service.create_statement(
                actor=request.user, competitor=competitor,
                **serializer.validated_data,
            )
        except CompetitorError as error:
            _translate(error)
        return Response(
            CompetitorStatementSerializer(statement).data,
            status=status.HTTP_201_CREATED,
        )


class CompetitorStatementDecisionViewSet(viewsets.GenericViewSet):
    permission_classes = (SolutionDraftPermission,)
    parser_classes = (JSONParser,)
    http_method_names = ["post", "head", "options"]

    def _statement(self) -> CompetitorStatement:
        statement = (
            CompetitorStatement.objects.select_related("competitor")
            .filter(pk=self.kwargs["pk"])
            .first()
        )
        if statement is None:
            raise NotFound()
        return statement

    def approve(self, request, *args, **kwargs):
        statement = self._statement()
        try:
            statement = service.approve_statement(statement, actor=request.user)
        except CompetitorError as error:
            _translate(error)
        return Response(CompetitorStatementSerializer(statement).data)

    def reject(self, request, *args, **kwargs):
        statement = self._statement()
        try:
            statement = service.reject_statement(statement, actor=request.user)
        except CompetitorError as error:
            _translate(error)
        return Response(CompetitorStatementSerializer(statement).data)
