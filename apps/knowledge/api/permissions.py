"""Business-role permissions for knowledge management APIs."""

from rest_framework.permissions import BasePermission

from apps.accounts.models import UserRole


class IsBusinessAdmin(BasePermission):
    """Allow only authenticated users with the Admin business role."""

    def has_permission(self, request, view):
        return bool(
            request.user.is_authenticated
            and request.user.role == UserRole.ADMIN
        )


class IsKnowledgeSearchUser(BasePermission):
    """Allow only the three authenticated V1 business roles to search."""

    allowed_roles = frozenset(
        {UserRole.ADMIN, UserRole.SALES, UserRole.PRESALES}
    )

    def has_permission(self, request, view):
        return bool(
            request.user.is_authenticated
            and request.user.role in self.allowed_roles
        )
