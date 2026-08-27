"""Permission classes for account APIs."""

from rest_framework.permissions import BasePermission

from apps.accounts.models import UserRole


class IsSales(BasePermission):
    """Allow requests made by users with the Sales business role."""

    def has_permission(self, request, view):
        return bool(
            request.user.is_authenticated
            and request.user.role == UserRole.SALES
        )
