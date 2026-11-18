"""Views for Customer create, retrieve, and collision search APIs."""

from django.db.models import Prefetch
from rest_framework import mixins, viewsets
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response

from .opportunity_access import OpportunityVisibilityMixin
from .pagination import DefaultPageNumberPagination
from .permissions import CustomerPermission, OpportunityPermission
from .record_state import (
    include_inactive_requested,
    require_active,
    require_admin,
    require_admin_for_archived_view,
)
from .serializers import (
    CustomerCreateSerializer,
    CustomerDetailSerializer,
    CustomerSearchSerializer,
    CustomerUpdateSerializer,
    OpportunityCreateSerializer,
    OpportunityDetailSerializer,
    OpportunityListSerializer,
    OpportunityUpdateSerializer,
)
from ..models import Customer, Opportunity, OpportunityStatus


CUSTOMER_SEARCH_MAX_LENGTH = 200


class CustomerViewSet(
    mixins.CreateModelMixin,
    mixins.RetrieveModelMixin,
    mixins.UpdateModelMixin,
    viewsets.GenericViewSet,
):
    """Expose Customer creation, retrieval, editing, and explicit search.

    There is deliberately no delete: historical solutions and reviews point at
    the customer, so removing the row would either cascade or orphan evidence.
    """

    queryset = Customer.objects.all()
    permission_classes = (CustomerPermission,)
    pagination_class = DefaultPageNumberPagination
    http_method_names = ["get", "post", "patch", "head", "options"]

    def get_serializer_class(self):
        action = getattr(self, "action", None)
        if action == "create":
            return CustomerCreateSerializer
        if action == "partial_update":
            return CustomerUpdateSerializer
        if action == "search":
            return CustomerSearchSerializer
        return CustomerDetailSerializer

    def get_queryset(self):
        queryset = Customer.objects.all()
        action = getattr(self, "action", None)

        if action in ("list", "search"):
            # Archived customers stay readable by id, so drafts and reviews that
            # reference them still open, but they leave the working list.
            if include_inactive_requested(self.request):
                require_admin_for_archived_view(self.request)
            else:
                queryset = queryset.filter(is_active=True)

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
            # Both flags matter: status is the business outcome and is_active is
            # whether the record is still worked on. A page that lists "current
            # work" must respect both, or an archived row reappears here after
            # being hidden from the list.
            active_opportunities = (
                Opportunity.objects.filter(
                    status=OpportunityStatus.ACTIVE, is_active=True
                )
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

    def partial_update(self, request, *args, **kwargs):
        require_active(self.get_object())
        return super().partial_update(request, *args, **kwargs)

    def disable(self, request, *args, **kwargs):
        return self._set_active(request, False)

    def enable(self, request, *args, **kwargs):
        return self._set_active(request, True)

    def _set_active(self, request, active: bool):
        require_admin(request.user)
        record = self.get_object()
        if record.is_active != active:
            record.is_active = active
            record.save(update_fields=["is_active", "updated_at"])
        return Response(self.get_serializer(record).data)

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

    def get_queryset(self):
        queryset = super().get_queryset()
        if getattr(self, "action", None) == "list":
            # Retrieve stays unfiltered on purpose: an archived opportunity is
            # still where its drafts, reviews and provenance live.
            if include_inactive_requested(self.request):
                require_admin_for_archived_view(self.request)
            else:
                queryset = queryset.filter(is_active=True)
        return queryset

    def partial_update(self, request, *args, **kwargs):
        require_active(self.get_object())
        return super().partial_update(request, *args, **kwargs)

    def disable(self, request, *args, **kwargs):
        return self._set_active(request, False)

    def enable(self, request, *args, **kwargs):
        return self._set_active(request, True)

    def _set_active(self, request, active: bool):
        require_admin(request.user)
        record = self.get_object()
        if record.is_active != active:
            record.is_active = active
            record.save(update_fields=["is_active", "updated_at"])
        return Response(self.get_serializer(record).data)
