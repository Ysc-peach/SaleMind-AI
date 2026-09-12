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
    """Allow reads by business role and writes by the owning Sales user only."""

    def has_permission(self, request, view):
        if not request.user.is_authenticated:
            return False

        if getattr(view, "action", None) in ("create", "partial_update"):
            return request.user.role == UserRole.SALES

        return request.user.role in (
            UserRole.ADMIN,
            UserRole.SALES,
            UserRole.PRESALES,
        )


class SolutionDraftPermission(BasePermission):
    """Business roles may use drafts only through role-filtered Opportunities."""

    def has_permission(self, request, view):
        return bool(
            request.user.is_authenticated
            and request.user.role
            in (UserRole.ADMIN, UserRole.SALES, UserRole.PRESALES)
        )


class SalesWorkspacePermission(BasePermission):
    """The Sales workspace is an owning-Sales projection, not a staff console."""

    def has_permission(self, request, view):
        return bool(
            request.user.is_authenticated and request.user.role == UserRole.SALES
        )


class ReviewerInboxPermission(BasePermission):
    """Only business reviewers can open their own version-scoped inbox."""

    def has_permission(self, request, view):
        return bool(
            request.user.is_authenticated
            and request.user.role in (UserRole.PRESALES, UserRole.ADMIN)
        )
