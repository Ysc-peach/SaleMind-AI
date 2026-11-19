"""Shapes for follow-up tasks.

The write serializers only validate what the HTTP layer can know; the service
still re-checks permissions and archived state, because a serializer cannot see
who owns the opportunity.
"""

from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework import serializers

from apps.accounts.models import UserRole
from apps.sales.api.serializers import user_display_name
from apps.sales.models import FollowUpTask

_BUSINESS_ROLES = (UserRole.SALES, UserRole.PRESALES, UserRole.ADMIN)


def _assignable_users():
    return get_user_model().objects.filter(
        is_active=True, role__in=_BUSINESS_ROLES
    )


class FollowUpTaskSerializer(serializers.ModelSerializer):
    owner_name = serializers.SerializerMethodField()
    is_overdue = serializers.SerializerMethodField()

    class Meta:
        model = FollowUpTask
        fields = (
            "id",
            "opportunity",
            "title",
            "due_on",
            "owner",
            "owner_name",
            "status",
            "completed_at",
            "is_overdue",
            "created_at",
            "updated_at",
        )
        read_only_fields = (
            "id",
            "opportunity",
            "owner_name",
            "status",
            "completed_at",
            "is_overdue",
            "created_at",
            "updated_at",
        )

    def get_owner_name(self, obj) -> str:
        return user_display_name(obj.owner)

    def get_is_overdue(self, obj) -> bool:
        # Computed, not stored: "late" is true only while the task is open, and
        # a stored flag would go stale the moment the date passes.
        return obj.status == "open" and obj.due_on < timezone.localdate()


class FollowUpTaskCreateSerializer(serializers.Serializer):
    title = serializers.CharField(max_length=200, allow_blank=False)
    due_on = serializers.DateField()
    owner = serializers.PrimaryKeyRelatedField(
        queryset=_assignable_users(), required=False, allow_null=True
    )


class FollowUpTaskUpdateSerializer(serializers.Serializer):
    title = serializers.CharField(
        max_length=200, allow_blank=False, required=False
    )
    due_on = serializers.DateField(required=False)
    owner = serializers.PrimaryKeyRelatedField(
        queryset=_assignable_users(), required=False, allow_null=True
    )
