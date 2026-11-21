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


class IsBusinessAdmin(BasePermission):
    """Allow account management to the business administrator only.

    Deliberately not ``is_staff``: Django staff access controls who may open
    /admin/, while hiring and stopping colleagues is a business decision made by
    the role that already owns reviews and archiving.
    """

    def has_permission(self, request, view):
        return bool(
            request.user.is_authenticated
            and request.user.role == UserRole.ADMIN
        )
