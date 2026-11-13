"""HTTP-layer adapter for the domain visibility rules."""

from apps.sales.services.visibility import visible_opportunities_for


class OpportunityVisibilityMixin:
    """Resolve objects from the same role-filtered queryset everywhere."""

    def get_queryset(self):
        return visible_opportunities_for(self.request.user)
