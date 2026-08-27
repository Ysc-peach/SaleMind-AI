"""Business-role permissions for sales-domain APIs."""

from rest_framework.permissions import BasePermission

from apps.accounts.models import UserRole


class CustomerPermission(BasePermission):
    """Allow authenticated Admin and Sales users to use Customer APIs."""

    def has_permission(self, request, view):
        return bool(
            request.user.is_authenticated
            and request.user.role in (UserRole.ADMIN, UserRole.SALES)
        )
