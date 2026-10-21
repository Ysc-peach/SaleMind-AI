"""URL routes for account APIs."""

from django.urls import path

from .views import CurrentUserView, LoginView, RefreshView


urlpatterns = [
    path("login/", LoginView.as_view(), name="auth-login"),
    path("refresh/", RefreshView.as_view(), name="auth-refresh"),
    path("me/", CurrentUserView.as_view(), name="auth-me"),
]
