"""URL routes for account APIs."""

from django.urls import path

from .views import CurrentUserView, LoginView, LogoutView, RefreshView


urlpatterns = [
    path("login/", LoginView.as_view(), name="auth-login"),
    path("refresh/", RefreshView.as_view(), name="auth-refresh"),
    path("logout/", LogoutView.as_view(), name="auth-logout"),
    path("me/", CurrentUserView.as_view(), name="auth-me"),
]
