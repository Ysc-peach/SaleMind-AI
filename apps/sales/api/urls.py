"""URL routes for Customer APIs."""

from django.urls import path

from .views import CustomerViewSet


customer_create_view = CustomerViewSet.as_view({"post": "create"})
customer_detail_view = CustomerViewSet.as_view({"get": "retrieve"})
customer_search_view = CustomerViewSet.as_view({"get": "search"})


urlpatterns = [
    path("customers/search/", customer_search_view, name="customer-search"),
    path("customers/<int:pk>/", customer_detail_view, name="customer-detail"),
    path("customers/", customer_create_view, name="customer-create"),
]
