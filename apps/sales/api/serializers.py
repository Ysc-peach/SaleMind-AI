"""Explicit, safe serializers for Customer APIs."""

from rest_framework import serializers

from apps.accounts.models import UserRole

from ..models import Customer, Opportunity


class OpportunitySummarySerializer(serializers.ModelSerializer):
    """Expose only the non-sensitive fields needed for collision search."""

    is_mine = serializers.SerializerMethodField()
    is_followed_by_other_sales = serializers.SerializerMethodField()

    class Meta:
        model = Opportunity
        fields = (
            "id",
            "project_name",
            "stage",
            "status",
            "is_mine",
            "is_followed_by_other_sales",
        )
        read_only_fields = fields

    def _request_user(self):
        request = self.context.get("request")
        return getattr(request, "user", None)

    def get_is_mine(self, obj):
        user = self._request_user()
        return bool(user and user.is_authenticated and obj.sales_owner_id == user.id)

    def get_is_followed_by_other_sales(self, obj):
        user = self._request_user()
        return bool(
            user
            and user.is_authenticated
            and user.role == UserRole.SALES
            and obj.sales_owner_id != user.id
        )


class CustomerCreateSerializer(serializers.ModelSerializer):
    """Accept only shared Customer fields; the view supplies created_by."""

    class Meta:
        model = Customer
        fields = ("id", "name", "industry", "company_size", "basic_info")
        read_only_fields = ("id",)


class _CustomerReadSerializer(serializers.ModelSerializer):
    """Shared read shape for detail and search responses."""

    opportunities = OpportunitySummarySerializer(
        source="active_opportunity_summaries", many=True, read_only=True
    )

    class Meta:
        model = Customer
        fields = (
            "id",
            "name",
            "industry",
            "company_size",
            "basic_info",
            "opportunities",
        )
        read_only_fields = fields


class CustomerSearchSerializer(_CustomerReadSerializer):
    """Safe Customer shape returned from collision search."""


class CustomerDetailSerializer(_CustomerReadSerializer):
    """Safe Customer shape returned from retrieve."""
