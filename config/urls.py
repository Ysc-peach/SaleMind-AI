"""Root URL configuration for SalesMind AI."""

from django.contrib import admin
from django.urls import include, path


urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/auth/", include("apps.accounts.api.urls")),
]
