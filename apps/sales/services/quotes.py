"""Quotes: priced against one draft version, with the price frozen per line.

Three rules carry the whole module:

* a line copies the unit price at the moment it is added, so the price book can
  change tomorrow without rewriting yesterday's quote;
* a quote is bound to one solution draft, and adding lines to a quote whose
  draft has been superseded is refused — re-pricing is a deliberate act;
* money is Decimal end to end, rounded once, on the cent.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal
from enum import StrEnum

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from apps.accounts.models import UserRole
from apps.sales.models import (
    Opportunity,
    Quote,
    QuoteDiscountApproval,
    QuoteDiscountDecisionStatus,
    QuoteLine,
    SolutionDraftRecord,
)

CENT = Decimal("0.01")


class QuoteErrorCode(StrEnum):
    INVALID_INPUT = "quote_invalid_input"
    FORBIDDEN = "quote_forbidden"
    NO_DRAFT = "quote_no_draft"
    OUTDATED = "quote_outdated"
    DISCOUNT_NOT_APPROVED = "discount_not_approved"
    DISCOUNT_ALREADY_DECIDED = "discount_already_decided"


class QuoteError(Exception):
    def __init__(self, code: QuoteErrorCode):
        super().__init__(code.value)
        self.code = code


def _money(value: Decimal) -> Decimal:
    return Decimal(value).quantize(CENT, rounding=ROUND_HALF_UP)


def _may_edit(quote: Quote, actor) -> bool:
    if actor is None:
        return False
    if actor.role == UserRole.ADMIN:
        return True
    return quote.opportunity.sales_owner_id == actor.pk


def _require_editor(quote: Quote, actor) -> None:
    if not _may_edit(quote, actor):
        raise QuoteError(QuoteErrorCode.FORBIDDEN)


def latest_draft(opportunity) -> SolutionDraftRecord | None:
    return (
        SolutionDraftRecord.objects.filter(opportunity=opportunity)
        .order_by("-version", "-id")
        .first()
    )


def get_quote(opportunity) -> Quote | None:
    return Quote.objects.filter(opportunity=opportunity).first()


def ensure_quote(*, opportunity, actor) -> Quote:
    """Return the opportunity's quote, creating it against the latest draft."""

    existing = get_quote(opportunity)
    if existing is not None:
        return existing
    if not _may_edit_for_opportunity(opportunity, actor):
        raise QuoteError(QuoteErrorCode.FORBIDDEN)
    draft = latest_draft(opportunity)
    if draft is None:
        raise QuoteError(QuoteErrorCode.NO_DRAFT)
    with transaction.atomic():
        return Quote.objects.create(
            opportunity=opportunity,
            solution_draft=draft,
            created_by=actor,
        )


def _may_edit_for_opportunity(opportunity: Opportunity, actor) -> bool:
    if actor is None:
        return False
    if actor.role == UserRole.ADMIN:
        return True
    return opportunity.sales_owner_id == actor.pk


def _require_current_binding(quote: Quote) -> None:
    if quote.solution_draft_id is None:
        raise QuoteError(QuoteErrorCode.NO_DRAFT)
    newest = latest_draft(quote.opportunity)
    if newest is None or newest.pk != quote.solution_draft_id:
        # The solution moved on; the numbers on screen belong to an older version.
        raise QuoteError(QuoteErrorCode.OUTDATED)


def active_lines(quote: Quote):
    return quote.lines.filter(removed_at__isnull=True).order_by("id")


def totals(quote: Quote) -> dict:
    lines = list(active_lines(quote))
    subtotal = _money(
        sum((line.unit_price * line.quantity for line in lines), Decimal("0"))
    )
    discount = _money(subtotal * quote.discount_percent / Decimal("100"))
    currencies = {line.currency for line in lines}
    if not currencies:
        currency = "CNY"
    elif len(currencies) == 1:
        currency = currencies.pop()
    else:
        # A mixed-currency sum would be a meaningless number presented as a
        # total, so the caller is told instead of being given one.
        currency = "MIXED"
    return {
        "line_count": len(lines),
        "subtotal": subtotal,
        "discount_percent": quote.discount_percent,
        "discount_amount": discount,
        "total": _money(subtotal - discount),
        "currency": currency,
    }


def add_line(*, quote: Quote, actor, entry, quantity) -> QuoteLine:
    _require_editor(quote, actor)
    _require_current_binding(quote)
    try:
        amount = Decimal(str(quantity))
    except (ArithmeticError, ValueError):
        raise QuoteError(QuoteErrorCode.INVALID_INPUT) from None
    if amount <= 0:
        raise QuoteError(QuoteErrorCode.INVALID_INPUT)
    with transaction.atomic():
        return QuoteLine.objects.create(
            quote=quote,
            price_book_entry=entry,
            sku=entry.sku,
            name=entry.name,
            unit=entry.unit,
            quantity=amount,
            unit_price=entry.unit_price,
            currency=entry.currency,
            created_by=actor,
        )


def set_quantity(line: QuoteLine, *, actor, quantity) -> QuoteLine:
    _require_editor(line.quote, actor)
    if line.removed_at is not None:
        raise QuoteError(QuoteErrorCode.INVALID_INPUT)
    try:
        amount = Decimal(str(quantity))
    except (ArithmeticError, ValueError):
        raise QuoteError(QuoteErrorCode.INVALID_INPUT) from None
    if amount <= 0:
        raise QuoteError(QuoteErrorCode.INVALID_INPUT)
    line.quantity = amount
    line.save(update_fields=["quantity"])
    return line


def remove_line(line: QuoteLine, *, actor) -> QuoteLine:
    _require_editor(line.quote, actor)
    if line.removed_at is None:
        line.removed_at = timezone.now()
        line.save(update_fields=["removed_at"])
    return line


def set_discount(
    quote: Quote, *, actor, percent, note: str | None = None
) -> Quote:
    _require_editor(quote, actor)
    try:
        value = Decimal(str(percent))
    except (ArithmeticError, ValueError):
        raise QuoteError(QuoteErrorCode.INVALID_INPUT) from None
    if value < 0 or value > 100:
        raise QuoteError(QuoteErrorCode.INVALID_INPUT)
    quote.discount_percent = value
    fields = ["discount_percent", "updated_at"]
    if note is not None:
        quote.note = note
        fields.append("note")
    quote.save(update_fields=fields)
    return quote


def rebind(quote: Quote, *, actor) -> Quote:
    """Price the same lines against the newest draft version."""

    _require_editor(quote, actor)
    newest = latest_draft(quote.opportunity)
    if newest is None:
        raise QuoteError(QuoteErrorCode.NO_DRAFT)
    if quote.solution_draft_id != newest.pk:
        quote.solution_draft = newest
        quote.save(update_fields=["solution_draft", "updated_at"])
    return quote


def discount_threshold() -> Decimal:
    # Quantised so the API reports "15.00" rather than "15": a percentage and a
    # money amount should not disagree about how many decimals they carry.
    return Decimal(
        str(settings.QUOTE_DISCOUNT_APPROVAL_THRESHOLD_PERCENT)
    ).quantize(CENT)


def _covering_approval(quote: Quote) -> QuoteDiscountApproval | None:
    """An approval covers the current discount only if it authorised at least it."""

    return (
        quote.discount_approvals.filter(
            status=QuoteDiscountDecisionStatus.APPROVED,
            discount_percent__gte=quote.discount_percent,
        )
        .order_by("-decided_at", "-id")
        .first()
    )


def discount_state(quote: Quote) -> dict:
    threshold = discount_threshold()
    required = quote.discount_percent > threshold
    covering = _covering_approval(quote)
    return {
        "threshold_percent": threshold,
        "required": required,
        "approved": (not required) or covering is not None,
        "approved_percent": covering.discount_percent if covering else None,
        "approved_by": covering.decided_by if covering else None,
        "approved_at": covering.decided_at if covering else None,
    }


def approve_discount(
    quote: Quote,
    *,
    actor,
    percent=None,
    comment: str = "",
) -> QuoteDiscountApproval:
    """An administrator authorises a discount level; only upward, never below ask."""

    if actor is None or actor.role != UserRole.ADMIN:
        raise QuoteError(QuoteErrorCode.FORBIDDEN)
    asked = quote.discount_percent
    try:
        authorised = Decimal(str(percent)) if percent is not None else asked
    except (ArithmeticError, ValueError):
        raise QuoteError(QuoteErrorCode.INVALID_INPUT) from None
    if authorised < asked or authorised > 100 or authorised < 0:
        # Approving less than the quote asks for would look like a green light.
        raise QuoteError(QuoteErrorCode.INVALID_INPUT)
    with transaction.atomic():
        return QuoteDiscountApproval.objects.create(
            quote=quote,
            discount_percent=authorised,
            status=QuoteDiscountDecisionStatus.APPROVED,
            comment=(comment or "").strip()[:2000],
            decided_by=actor,
        )


def reject_discount(
    quote: Quote, *, actor, comment: str = ""
) -> QuoteDiscountApproval:
    if actor is None or actor.role != UserRole.ADMIN:
        raise QuoteError(QuoteErrorCode.FORBIDDEN)
    with transaction.atomic():
        return QuoteDiscountApproval.objects.create(
            quote=quote,
            discount_percent=quote.discount_percent,
            status=QuoteDiscountDecisionStatus.REJECTED,
            comment=(comment or "").strip()[:2000],
            decided_by=actor,
        )


def ensure_discount_exportable(quote: Quote) -> dict:
    """The gate: an unapproved discount keeps the quote page inside the company."""

    state = discount_state(quote)
    if not state["approved"]:
        raise QuoteError(QuoteErrorCode.DISCOUNT_NOT_APPROVED)
    return state


def quote_for_export(*, quote: Quote, solution_draft_id: int) -> Quote:
    """Raise unless this quote may be attached to that draft's export."""

    if quote.solution_draft_id != solution_draft_id:
        raise QuoteError(QuoteErrorCode.OUTDATED)
    newest = latest_draft(quote.opportunity)
    if newest is None or newest.pk != solution_draft_id:
        raise QuoteError(QuoteErrorCode.OUTDATED)
    return quote
