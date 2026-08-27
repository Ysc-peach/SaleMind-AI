"""URL routes for user option APIs."""

from django.urls import path

from .views import PresalesOptionListView


urlpatterns = [
    path(
        "presales-options/",
        PresalesOptionListView.as_view(),
        name="user-presales-options",
    ),
]
