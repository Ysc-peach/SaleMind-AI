"""Explicit, safe serializers for sales-domain APIs."""

from rest_framework import serializers

from apps.accounts.models import User, UserRole

from ..models import Customer, Opportunity


def user_display_name(user) -> str:
    """Return the smallest useful business display name without exposing profile data."""

    if user is None:
        return ""
    return user.get_full_name().strip() or user.username


class OpportunityDisplaySerializer(serializers.ModelSerializer):
    customer_name = serializers.CharField(source="customer.name", read_only=True)
    sales_owner_name = serializers.SerializerMethodField()
    presales_owner_name = serializers.SerializerMethodField()

    def get_sales_owner_name(self, obj):
        return user_display_name(obj.sales_owner)

    def get_presales_owner_name(self, obj):
        return user_display_name(obj.presales_owner)


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


class RejectForbiddenFieldsMixin:
    """Turn client attempts to set server-controlled fields into 400 errors."""

    forbidden_fields = ()

    def to_internal_value(self, data):
        errors = {
            field: "This field is controlled by the server."
            for field in self.forbidden_fields
            if field in data
        }
        if errors:
            raise serializers.ValidationError(errors)
        return super().to_internal_value(data)


class OpportunityListSerializer(OpportunityDisplaySerializer):
    """Compact safe representation for an Opportunity collection."""

    class Meta:
        model = Opportunity
        fields = (
            "id",
            "project_name",
            "customer",
            "customer_name",
            "sales_owner",
            "sales_owner_name",
            "presales_owner",
            "presales_owner_name",
            "stage",
            "status",
            "budget",
            "expected_launch_date",
            "updated_at",
        )
        read_only_fields = fields


class OpportunityDetailSerializer(OpportunityDisplaySerializer):
    """Full read shape for an Opportunity visible to an authorized user."""

    class Meta:
        model = Opportunity
        fields = (
            "id",
            "project_name",
            "customer",
            "customer_name",
            "sales_owner",
            "sales_owner_name",
            "presales_owner",
            "presales_owner_name",
            "raw_requirement",
            "budget",
            "stage",
            "status",
            "expected_launch_date",
            "created_at",
            "updated_at",
        )
        read_only_fields = fields


class OpportunityCreateSerializer(RejectForbiddenFieldsMixin, serializers.ModelSerializer):
    """Accept only Sales-controlled creation fields for an Opportunity."""

    presales_owner = serializers.PrimaryKeyRelatedField(
        queryset=User.objects.filter(is_active=True, role=UserRole.PRESALES),
        allow_null=True,
        required=False,
    )
    forbidden_fields = ("sales_owner", "created_by", "stage", "status")

    class Meta:
        model = Opportunity
        fields = (
            "id",
            "project_name",
            "customer",
            "presales_owner",
            "raw_requirement",
            "budget",
            "expected_launch_date",
        )
        read_only_fields = ("id",)


class OpportunityUpdateSerializer(RejectForbiddenFieldsMixin, serializers.ModelSerializer):
    """Accept only the Sales-controlled fields of an existing Opportunity."""

    presales_owner = serializers.PrimaryKeyRelatedField(
        queryset=User.objects.filter(is_active=True, role=UserRole.PRESALES),
        allow_null=True,
        required=False,
    )
    forbidden_fields = (
        "customer",
        "sales_owner",
        "created_by",
        "created_at",
        "updated_at",
    )

    class Meta:
        model = Opportunity
        fields = (
            "project_name",
            "presales_owner",
            "raw_requirement",
            "budget",
            "stage",
            "status",
            "expected_launch_date",
        )
