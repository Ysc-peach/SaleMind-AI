"""Price book reads.

Append-only rows mean "the current price" is not a column but a question: the
newest row for a SKU whose effective date has already arrived. Keeping that
question in one place means a quote, an export and an API all answer it the same
way.
"""

from __future__ import annotations

from datetime import date

from django.db.models import Q
from django.utils import timezone

from apps.sales.models import PriceBookEntry


def current_entries(
    *,
    as_of: date | None = None,
    sku: str = "",
    search: str = "",
    include_inactive: bool = False,
):
    """One row per SKU: the newest that has started by ``as_of``."""

    as_of = as_of or timezone.localdate()
    queryset = PriceBookEntry.objects.filter(effective_from__lte=as_of)
    if not include_inactive:
        queryset = queryset.filter(is_active=True)
    if sku:
        queryset = queryset.filter(sku__iexact=sku)
    if search:
        queryset = queryset.filter(
            Q(sku__icontains=search) | Q(name__icontains=search)
        )
    # DISTINCT ON needs its expression to lead the ordering; that ordering also
    # happens to be what a reader wants.
    return queryset.order_by("sku", "-effective_from").distinct("sku")


def current_price(sku: str, *, as_of: date | None = None) -> PriceBookEntry | None:
    return current_entries(as_of=as_of, sku=sku).first()
