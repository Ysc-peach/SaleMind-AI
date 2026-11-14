"""URL routes for account APIs."""

from django.urls import path

from .views import (
    ChangePasswordView,
    CurrentUserView,
    LoginView,
    LogoutView,
    RefreshView,
)


urlpatterns = [
    path("login/", LoginView.as_view(), name="auth-login"),
    path("refresh/", RefreshView.as_view(), name="auth-refresh"),
    path("logout/", LogoutView.as_view(), name="auth-logout"),
    path("password/", ChangePasswordView.as_view(), name="auth-password"),
    path("me/", CurrentUserView.as_view(), name="auth-me"),
]
