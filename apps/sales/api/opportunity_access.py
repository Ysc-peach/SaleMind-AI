"""Shared object visibility for Opportunity APIs and their derived operations."""

from apps.accounts.models import UserRole
from apps.sales.models import Opportunity


class OpportunityVisibilityMixin:
    """Resolve objects from the same role-filtered queryset everywhere."""

    def get_queryset(self):
        queryset = Opportunity.objects.select_related(
            "customer", "sales_owner", "presales_owner", "created_by"
        )
        role = self.request.user.role
        if role == UserRole.SALES:
            queryset = queryset.filter(sales_owner=self.request.user)
        elif role == UserRole.PRESALES:
            queryset = queryset.filter(presales_owner=self.request.user)
        elif role != UserRole.ADMIN:
            queryset = queryset.none()
        return queryset.order_by("-updated_at", "-id")
