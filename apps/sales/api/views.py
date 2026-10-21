"""Views for Customer create, retrieve, and collision search APIs."""

from django.db.models import Prefetch
from rest_framework import mixins, viewsets
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response

from .opportunity_access import OpportunityVisibilityMixin
from .pagination import DefaultPageNumberPagination
from .permissions import CustomerPermission, OpportunityPermission
from .serializers import (
    CustomerCreateSerializer,
    CustomerDetailSerializer,
    CustomerSearchSerializer,
    OpportunityCreateSerializer,
    OpportunityDetailSerializer,
    OpportunityListSerializer,
    OpportunityUpdateSerializer,
)
from ..models import Customer, Opportunity, OpportunityStatus


CUSTOMER_SEARCH_MAX_LENGTH = 200


class CustomerViewSet(
    mixins.CreateModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet
):
    """Expose only Customer creation, retrieval, and explicit search."""

    queryset = Customer.objects.all()
    permission_classes = (CustomerPermission,)
    pagination_class = DefaultPageNumberPagination
    http_method_names = ["get", "post", "head", "options"]

    def get_serializer_class(self):
        action = getattr(self, "action", None)
        if action == "create":
            return CustomerCreateSerializer
        if action == "search":
            return CustomerSearchSerializer
        return CustomerDetailSerializer

    def get_queryset(self):
        queryset = Customer.objects.all()
        action = getattr(self, "action", None)

        if action == "search":
            query = self.request.query_params.get("q", "").strip()
            if not query:
                raise ValidationError({"q": "This query parameter is required."})
            if len(query) > CUSTOMER_SEARCH_MAX_LENGTH:
                raise ValidationError({
                    "code": "customer_search_query_too_long",
                    "q": "客户搜索最多 200 个字符，请缩短后重试。",
                })
            queryset = queryset.filter(name__icontains=query)

        if action in ("search", "retrieve"):
            active_opportunities = (
                Opportunity.objects.filter(status=OpportunityStatus.ACTIVE)
                .only(
                    "id",
                    "project_name",
                    "stage",
                    "status",
                    "sales_owner_id",
                    "customer_id",
                )
                .order_by("id")
            )
            queryset = queryset.prefetch_related(
                Prefetch(
                    "opportunities",
                    queryset=active_opportunities,
                    to_attr="active_opportunity_summaries",
                )
            )

        return queryset.order_by("name", "id")

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)

    def search(self, request, *args, **kwargs):
        queryset = self.filter_queryset(self.get_queryset())
        page = self.paginate_queryset(queryset)
        if page is not None:
            serializer = self.get_serializer(page, many=True)
            return self.get_paginated_response(serializer.data)
        serializer = self.get_serializer(queryset, many=True)
        return Response(serializer.data)


class OpportunityViewSet(
    OpportunityVisibilityMixin,
    mixins.ListModelMixin,
    mixins.CreateModelMixin,
    mixins.RetrieveModelMixin,
    mixins.UpdateModelMixin,
    viewsets.GenericViewSet,
):
    """Expose only role-filtered Opportunity reads and Sales creation."""

    queryset = Opportunity.objects.all()
    permission_classes = (OpportunityPermission,)
    pagination_class = DefaultPageNumberPagination
    http_method_names = ["get", "post", "patch", "head", "options"]

    def get_serializer_class(self):
        action = getattr(self, "action", None)
        if action == "create":
            return OpportunityCreateSerializer
        if action == "partial_update":
            return OpportunityUpdateSerializer
        if action == "list":
            return OpportunityListSerializer
        return OpportunityDetailSerializer

    def perform_create(self, serializer):
        serializer.save(sales_owner=self.request.user, created_by=self.request.user)
