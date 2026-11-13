"""Business-role object visibility, shared by APIs and domain services.

This is a domain rule, not an HTTP-layer rule: Django ``is_staff`` and
``is_superuser`` never widen the visible object set.
"""

from apps.accounts.models import UserRole
from apps.sales.models import Opportunity, SolutionDraftRecord


def visible_opportunities_for(user):
    """Return the business-role visibility boundary; technical flags are irrelevant."""

    queryset = Opportunity.objects.select_related(
        "customer", "sales_owner", "presales_owner", "created_by"
    )
    if user.role == UserRole.SALES:
        queryset = queryset.filter(sales_owner=user)
    elif user.role == UserRole.PRESALES:
        queryset = queryset.filter(presales_owner=user)
    elif user.role != UserRole.ADMIN:
        queryset = queryset.none()
    return queryset.order_by("-updated_at", "-id")


def visible_solution_drafts_for(user):
    """Keep Opportunity visibility and add only explicit version review assignments."""

    queryset = SolutionDraftRecord.objects.filter(
        opportunity__in=visible_opportunities_for(user)
    )
    if user.role == UserRole.PRESALES:
        queryset = queryset | SolutionDraftRecord.objects.filter(
            reviews__reviewer=user
        )
    return queryset.distinct()
