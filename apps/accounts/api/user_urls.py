"""URL routes for user APIs."""

from django.urls import path

from .user_admin_views import UserAdminViewSet
from .views import PresalesOptionListView

user_collection_view = UserAdminViewSet.as_view(
    {"get": "list_users", "post": "create_user"}
)
user_detail_view = UserAdminViewSet.as_view({"patch": "partial_update"})
user_deactivate_view = UserAdminViewSet.as_view({"post": "deactivate"})
user_activate_view = UserAdminViewSet.as_view({"post": "activate"})
user_password_view = UserAdminViewSet.as_view({"post": "reset_password"})

urlpatterns = [
    path(
        "presales-options/",
        PresalesOptionListView.as_view(),
        name="user-presales-options",
    ),
    path("", user_collection_view, name="user-list"),
    path("<int:pk>/", user_detail_view, name="user-detail"),
    path(
        "<int:pk>/deactivate/", user_deactivate_view, name="user-deactivate"
    ),
    path("<int:pk>/activate/", user_activate_view, name="user-activate"),
    path("<int:pk>/password/", user_password_view, name="user-password"),
]
