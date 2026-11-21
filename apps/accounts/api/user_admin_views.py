"""Administrator endpoints for managing accounts.

Kept out of Django Admin so a person who runs the sales side can hire, move and
stop colleagues without a developer opening the shell. The lockout rules live in
the service, not here: a view that forgets to check cannot widen them.
"""

from django.contrib.auth import get_user_model
from django.db.models import Q
from rest_framework import status, viewsets
from rest_framework.exceptions import APIException, NotFound, PermissionDenied, ValidationError
from rest_framework.pagination import PageNumberPagination
from rest_framework.parsers import JSONParser
from rest_framework.response import Response

from apps.accounts.api.permissions import IsBusinessAdmin
from apps.accounts.api.user_admin_serializers import (
    CreateUserSerializer,
    ResetPasswordSerializer,
    UpdateUserSerializer,
    UserSummarySerializer,
)
from apps.accounts.models import UserRole
from apps.accounts.services import user_lifecycle as service
from apps.accounts.services.user_lifecycle import UserAdminError, UserAdminErrorCode


class LastAdminRemaining(APIException):
    status_code = 409
    default_detail = "这会移除最后一名有效管理员，系统将无人可管理。请先指定另一位管理员。"
    default_code = "user_last_admin"


class SelfDeactivation(APIException):
    status_code = 409
    default_detail = "不能停用自己的账号；如需离职交接，请让另一位管理员操作。"
    default_code = "user_self_deactivation"


def _translate(error: UserAdminError):
    if error.code == UserAdminErrorCode.FORBIDDEN:
        raise PermissionDenied("只有业务管理员可以管理账号。")
    if error.code == UserAdminErrorCode.LAST_ADMIN:
        raise LastAdminRemaining()
    if error.code == UserAdminErrorCode.SELF_DEACTIVATION:
        raise SelfDeactivation()
    if error.code == UserAdminErrorCode.DUPLICATE:
        raise ValidationError({"detail": "用户名或邮箱已被占用。"})
    raise ValidationError({"detail": error.detail or "账号参数不符合要求。"})


class UserPagination(PageNumberPagination):
    page_size = 20


class UserAdminViewSet(viewsets.GenericViewSet):
    permission_classes = (IsBusinessAdmin,)
    parser_classes = (JSONParser,)
    pagination_class = UserPagination
    http_method_names = ["get", "post", "patch", "head", "options"]

    def list_users(self, request):
        queryset = get_user_model().objects.all().order_by("username")
        role = (request.query_params.get("role") or "").strip()
        if role:
            if role not in UserRole.values:
                raise ValidationError({"role": "Unknown role."})
            queryset = queryset.filter(role=role)
        search = (request.query_params.get("q") or "").strip()
        if search:
            queryset = queryset.filter(
                Q(username__icontains=search)
                | Q(first_name__icontains=search)
                | Q(last_name__icontains=search)
                | Q(email__icontains=search)
            )
        include_inactive = (
            request.query_params.get("include_inactive") or ""
        ).lower() in {"1", "true", "yes"}
        if not include_inactive:
            queryset = queryset.filter(is_active=True)
        page = self.paginate_queryset(queryset)
        return self.get_paginated_response(
            UserSummarySerializer(page, many=True).data
        )

    def create_user(self, request):
        serializer = CreateUserSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            user = service.create_user(actor=request.user, **serializer.validated_data)
        except UserAdminError as error:
            _translate(error)
        return Response(
            UserSummarySerializer(user).data, status=status.HTTP_201_CREATED
        )

    def _target(self):
        user = get_user_model().objects.filter(pk=self.kwargs["pk"]).first()
        if user is None:
            raise NotFound()
        return user

    def partial_update(self, request, *args, **kwargs):
        user = self._target()
        serializer = UpdateUserSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            user = service.update_user(
                user, actor=request.user, **serializer.validated_data
            )
        except UserAdminError as error:
            _translate(error)
        return Response(UserSummarySerializer(user).data)

    def deactivate(self, request, *args, **kwargs):
        return self._set_active(request, False)

    def activate(self, request, *args, **kwargs):
        return self._set_active(request, True)

    def _set_active(self, request, active: bool):
        user = self._target()
        try:
            user = service.set_user_active(
                user, actor=request.user, active=active
            )
        except UserAdminError as error:
            _translate(error)
        return Response(UserSummarySerializer(user).data)

    def reset_password(self, request, *args, **kwargs):
        user = self._target()
        serializer = ResetPasswordSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            service.reset_password(
                user, actor=request.user, password=serializer.validated_data["password"]
            )
        except UserAdminError as error:
            _translate(error)
        return Response(status=status.HTTP_204_NO_CONTENT)
