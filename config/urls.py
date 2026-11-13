"""Root URL configuration for SalesMind AI."""

from django.contrib import admin
from django.urls import include, path

from config.health import health


urlpatterns = [
    path("healthz", health, name="health"),
    path("admin/", admin.site.urls),
    path("api/auth/", include("apps.accounts.api.urls")),
    path("api/users/", include("apps.accounts.api.user_urls")),
    path("api/", include("apps.knowledge.api.urls")),
    path("api/", include("apps.rag.api.urls")),
    path("api/", include("apps.sales.api.urls")),
]
