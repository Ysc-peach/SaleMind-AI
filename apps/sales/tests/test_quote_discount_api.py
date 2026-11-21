"""A discount above the threshold needs an administrator's decision, in writing."""

from datetime import timedelta
from decimal import Decimal

import pytest
from django.utils import timezone

from apps.accounts.models import UserRole
from apps.sales.models import (
    PriceBookEntry,
    Quote,
    QuoteDiscountApproval,
    SolutionDraftRecord,
)
from apps.sales.services import quotes as quote_service
from apps.sales.services.quotes import QuoteError, QuoteErrorCode

pytestmark = pytest.mark.django_db


def _draft(owner, opportunity, analysis):
    return SolutionDraftRecord.objects.create(
        opportunity=opportunity,
        requirement_analysis=analysis,
        version=1,
        title="方案 v1",
        draft_payload={},
        created_by=owner,
    )


def _quote(owner, opportunity, analysis, *, discount="0"):
    draft = _draft(owner, opportunity, analysis)
    entry = PriceBookEntry.objects.create(
        sku="SKU-1",
        name="标准版",
        unit="套",
        unit_price=Decimal("1000.00"),
        effective_from=timezone.localdate() - timedelta(days=1),
        created_by=owner,
    )
    quote = Quote.objects.create(
        opportunity=opportunity,
        solution_draft=draft,
        discount_percent=Decimal(discount),
        created_by=owner,
    )
    quote_service.add_line(quote=quote, actor=owner, entry=entry, quantity=2)
    return quote


def test_a_discount_below_the_threshold_needs_no_decision(
    persistence_context, settings
):
    settings.QUOTE_DISCOUNT_APPROVAL_THRESHOLD_PERCENT = 15
    owner, _customer, opportunity, analysis, _ = persistence_context
    quote = _quote(owner, opportunity, analysis, discount="10")

    state = quote_service.discount_state(quote)

    assert state["required"] is False
    assert state["approved"] is True
    quote_service.ensure_discount_exportable(quote)


def test_a_discount_above_the_threshold_blocks_the_export(
    persistence_context, settings
):
    settings.QUOTE_DISCOUNT_APPROVAL_THRESHOLD_PERCENT = 15
    owner, _customer, opportunity, analysis, _ = persistence_context
    quote = _quote(owner, opportunity, analysis, discount="20")

    assert quote_service.discount_state(quote)["required"] is True
    with pytest.raises(QuoteError) as blocked:
        quote_service.ensure_discount_exportable(quote)
    assert blocked.value.code == QuoteErrorCode.DISCOUNT_NOT_APPROVED


def test_an_admin_decision_unblocks_it(persistence_context, settings, user_factory):
    settings.QUOTE_DISCOUNT_APPROVAL_THRESHOLD_PERCENT = 15
    owner, _customer, opportunity, analysis, _ = persistence_context
    quote = _quote(owner, opportunity, analysis, discount="20")
    admin = user_factory(UserRole.ADMIN, username="discount-admin")

    quote_service.approve_discount(quote, actor=admin, comment="首单让利")

    state = quote_service.discount_state(quote)
    assert state["approved"] is True
    assert state["approved_percent"] == Decimal("20.00")
    quote_service.ensure_discount_exportable(quote)


def test_approving_less_than_asked_is_refused(
    persistence_context, settings, user_factory
):
    settings.QUOTE_DISCOUNT_APPROVAL_THRESHOLD_PERCENT = 15
    owner, _customer, opportunity, analysis, _ = persistence_context
    quote = _quote(owner, opportunity, analysis, discount="25")
    admin = user_factory(UserRole.ADMIN, username="discount-admin")

    # Approving 10% would look like a green light for a 25% quote.
    with pytest.raises(QuoteError) as refused:
        quote_service.approve_discount(quote, actor=admin, percent=10)
    assert refused.value.code == QuoteErrorCode.INVALID_INPUT
    assert QuoteDiscountApproval.objects.count() == 0


def test_only_an_admin_can_decide(persistence_context, settings):
    settings.QUOTE_DISCOUNT_APPROVAL_THRESHOLD_PERCENT = 15
    owner, _customer, opportunity, analysis, _ = persistence_context
    quote = _quote(owner, opportunity, analysis, discount="20")

    with pytest.raises(QuoteError) as refused:
        quote_service.approve_discount(quote, actor=owner)
    assert refused.value.code == QuoteErrorCode.FORBIDDEN


def test_raising_the_discount_after_approval_needs_a_new_decision(
    persistence_context, settings, user_factory, api_client
):
    settings.QUOTE_DISCOUNT_APPROVAL_THRESHOLD_PERCENT = 15
    owner, _customer, opportunity, analysis, _ = persistence_context
    quote = _quote(owner, opportunity, analysis, discount="20")
    admin = user_factory(UserRole.ADMIN, username="discount-admin")
    quote_service.approve_discount(quote, actor=admin)
    api_client.force_authenticate(user=owner)

    # 20% was authorised; 30% was not.
    api_client.patch(
        f"/api/opportunities/{opportunity.pk}/quote/",
        {"discount_percent": "30"},
        format="json",
    )
    quote.refresh_from_db()

    assert quote_service.discount_state(quote)["approved"] is False


def test_lowering_the_discount_keeps_the_approval(
    persistence_context, settings, user_factory, api_client
):
    settings.QUOTE_DISCOUNT_APPROVAL_THRESHOLD_PERCENT = 15
    owner, _customer, opportunity, analysis, _ = persistence_context
    quote = _quote(owner, opportunity, analysis, discount="20")
    admin = user_factory(UserRole.ADMIN, username="discount-admin")
    quote_service.approve_discount(quote, actor=admin)
    api_client.force_authenticate(user=owner)

    api_client.patch(
        f"/api/opportunities/{opportunity.pk}/quote/",
        {"discount_percent": "12"},
        format="json",
    )
    quote.refresh_from_db()

    # A discount below what was authorised is covered by that authorisation.
    state = quote_service.discount_state(quote)
    assert state["required"] is False
    assert state["approved"] is True


def test_a_rejection_is_recorded_and_leaves_the_quote_blocked(
    persistence_context, settings, user_factory
):
    settings.QUOTE_DISCOUNT_APPROVAL_THRESHOLD_PERCENT = 15
    owner, _customer, opportunity, analysis, _ = persistence_context
    quote = _quote(owner, opportunity, analysis, discount="30")
    admin = user_factory(UserRole.ADMIN, username="discount-admin")

    decision = quote_service.reject_discount(
        quote, actor=admin, comment="超出本季度毛利底线"
    )

    assert decision.status == "rejected"
    assert decision.comment == "超出本季度毛利底线"
    assert quote_service.discount_state(quote)["approved"] is False


def test_the_api_reports_the_gate_and_the_decision(
    persistence_context, settings, user_factory, api_client
):
    settings.QUOTE_DISCOUNT_APPROVAL_THRESHOLD_PERCENT = 15
    owner, _customer, opportunity, analysis, _ = persistence_context
    quote = _quote(owner, opportunity, analysis, discount="20")
    api_client.force_authenticate(user=owner)

    before = api_client.get(f"/api/opportunities/{opportunity.pk}/quote/").data
    assert before["discount_approval"]["required"] is True
    assert before["discount_approval"]["approved"] is False

    api_client.force_authenticate(
        user=user_factory(UserRole.ADMIN, username="discount-admin")
    )
    response = api_client.post(
        f"/api/opportunities/{opportunity.pk}/quote/discount-approval/",
        {"comment": "同意"},
        format="json",
    )

    assert response.status_code == 200
    assert response.data["discount_approval"]["approved"] is True
    assert response.data["discount_approval"]["approved_percent"] == "20.00"
    assert response.data["discount_approval"]["approved_by_name"]
    assert quote.discount_approvals.count() == 1


def test_the_threshold_is_configuration_not_code(
    persistence_context, settings, api_client, user_factory
):
    settings.QUOTE_DISCOUNT_APPROVAL_THRESHOLD_PERCENT = 5
    owner, _customer, opportunity, analysis, _ = persistence_context
    _quote(owner, opportunity, analysis, discount="6")
    api_client.force_authenticate(user=user_factory(UserRole.ADMIN, username="a2"))

    response = api_client.get(f"/api/opportunities/{opportunity.pk}/quote/")

    assert response.data["discount_approval"]["required"] is True
    assert response.data["discount_approval"]["threshold_percent"] == "5.00"
