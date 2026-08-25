"""URL routes for account APIs."""

from django.urls import path
from rest_framework.permissions import AllowAny
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView

from .views import CurrentUserView


urlpatterns = [
    path(
        "login/",
        TokenObtainPairView.as_view(permission_classes=(AllowAny,)),
        name="auth-login",
    ),
    path(
        "refresh/",
        TokenRefreshView.as_view(permission_classes=(AllowAny,)),
        name="auth-refresh",
    ),
    path("me/", CurrentUserView.as_view(), name="auth-me"),
]
