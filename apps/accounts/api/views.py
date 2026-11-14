"""Views for account APIs."""

from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework import status
from rest_framework.exceptions import ValidationError
from rest_framework.generics import ListAPIView, RetrieveAPIView
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.token_blacklist.models import (
    BlacklistedToken,
    OutstandingToken,
)
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView

from apps.accounts.models import UserRole

from .permissions import IsSales
from .serializers import (
    ChangePasswordSerializer,
    CurrentUserSerializer,
    PresalesOptionSerializer,
)


class LoginView(TokenObtainPairView):
    """Password login is anonymous and must not be brute-forceable."""

    permission_classes = (AllowAny,)
    throttle_classes = (ScopedRateThrottle,)
    throttle_scope = "login"


class RefreshView(TokenRefreshView):
    """Refresh has its own budget so login brute force cannot lock out renewal."""

    permission_classes = (AllowAny,)
    throttle_classes = (ScopedRateThrottle,)
    throttle_scope = "token_refresh"


class LogoutView(APIView):
    """Revoke a refresh token so a logout cannot be undone with a stale copy.

    ``AllowAny`` is intentional: an access token may already have expired when
    the user clicks logout, and the refresh token itself is the credential. The
    endpoint shares the refresh throttle scope and never reveals why a token was
    rejected.
    """

    permission_classes = (AllowAny,)
    throttle_classes = (ScopedRateThrottle,)
    throttle_scope = "token_refresh"

    def post(self, request):
        raw = request.data.get("refresh")
        if not isinstance(raw, str) or not raw.strip():
            raise ValidationError({"refresh": "A refresh token is required."})
        try:
            RefreshToken(raw).blacklist()
        except TokenError:
            raise ValidationError({"refresh": "Invalid refresh token."}) from None
        return Response(status=status.HTTP_204_NO_CONTENT)


class ChangePasswordView(APIView):
    """Rotate the caller's own password and revoke every existing session.

    Revoking matters: without it a password change leaves the seven-day refresh
    tokens of every device valid, which is exactly the case an operator changes
    a password to escape. The caller has to sign in again afterwards.
    """

    permission_classes = (IsAuthenticated,)
    throttle_classes = (ScopedRateThrottle,)
    throttle_scope = "login"

    def post(self, request):
        serializer = ChangePasswordSerializer(
            data=request.data, context={"request": request},
        )
        serializer.is_valid(raise_exception=True)
        user = request.user
        user.set_password(serializer.validated_data["new_password"])
        user.save(update_fields=["password"])
        _revoke_outstanding_tokens(user)
        return Response(status=status.HTTP_204_NO_CONTENT)


def _revoke_outstanding_tokens(user) -> None:
    now = timezone.now()
    outstanding = OutstandingToken.objects.filter(
        user=user, expires_at__gt=now,
    )
    for token in outstanding:
        BlacklistedToken.objects.get_or_create(token=token)


class CurrentUserView(RetrieveAPIView):
    permission_classes = (IsAuthenticated,)
    serializer_class = CurrentUserSerializer

    def get_object(self):
        return self.request.user


class PresalesOptionListView(ListAPIView):
    permission_classes = (IsAuthenticated, IsSales)
    serializer_class = PresalesOptionSerializer

    def get_queryset(self):
        return get_user_model().objects.filter(
            is_active=True,
            role=UserRole.PRESALES,
        ).order_by("username", "id")
