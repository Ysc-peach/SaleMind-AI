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


class OpportunityPermission(BasePermission):
    """Allow read access by business role and creation by Sales only."""

    def has_permission(self, request, view):
        if not request.user.is_authenticated:
            return False

        if request.method == "POST":
            return request.user.role == UserRole.SALES

        return request.user.role in (
            UserRole.ADMIN,
            UserRole.SALES,
            UserRole.PRESALES,
        )
