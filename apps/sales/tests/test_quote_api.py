"""Quotes freeze their price, bind one draft version, and refuse to drift."""

from datetime import timedelta
from decimal import Decimal

import pytest
from django.utils import timezone

from apps.accounts.models import UserRole
from apps.sales.models import PriceBookEntry, Quote, QuoteLine, SolutionDraftRecord
from apps.sales.services import quotes as quote_service
from apps.sales.services.quotes import QuoteError, QuoteErrorCode
from apps.sales.services.quote_document import build_quote_section

pytestmark = pytest.mark.django_db


def _entry(owner, *, sku="SKU-1", name="标准版", price="1000.00", active=True):
    return PriceBookEntry.objects.create(
        sku=sku,
        name=name,
        unit="套",
        unit_price=Decimal(price),
        effective_from=timezone.localdate() - timedelta(days=1),
        is_active=active,
        created_by=owner,
    )


def _draft(owner, opportunity, analysis, *, version=1):
    return SolutionDraftRecord.objects.create(
        opportunity=opportunity,
        requirement_analysis=analysis,
        version=version,
        title=f"方案 v{version}",
        draft_payload={},
        created_by=owner,
    )


def _quote_url(opportunity):
    return f"/api/opportunities/{opportunity.pk}/quote/"


def _add_line(api_client, opportunity, entry, quantity=1):
    return api_client.post(
        _quote_url(opportunity) + "lines/",
        {"price_book_entry": entry.pk, "quantity": quantity},
        format="json",
    )


def test_adding_a_line_freezes_the_price_at_that_moment(
    api_client, persistence_context
):
    owner, _customer, opportunity, analysis, _ = persistence_context
    _draft(owner, opportunity, analysis)
    entry = _entry(owner, price="1000.00")
    api_client.force_authenticate(user=owner)

    response = _add_line(api_client, opportunity, entry, quantity=2)
    assert response.status_code == 201
    assert response.data["subtotal"] == "2000.00"

    # A later price change must not rewrite the line already quoted.
    entry.unit_price = Decimal("1500.00")
    entry.save(update_fields=["unit_price"])
    refreshed = api_client.get(_quote_url(opportunity)).data

    assert refreshed["lines"][0]["unit_price"] == "1000.00"
    assert refreshed["subtotal"] == "2000.00"


def test_the_quote_needs_a_draft_version_first(api_client, persistence_context):
    owner, _customer, opportunity, _analysis, _ = persistence_context
    entry = _entry(owner)
    api_client.force_authenticate(user=owner)

    response = _add_line(api_client, opportunity, entry)

    assert response.status_code == 409
    assert response.data["code"] == "quote_no_draft"
    assert Quote.objects.count() == 0


def test_a_discount_applies_to_the_subtotal(api_client, persistence_context):
    owner, _customer, opportunity, analysis, _ = persistence_context
    _draft(owner, opportunity, analysis)
    entry = _entry(owner, price="1000.00")
    api_client.force_authenticate(user=owner)
    _add_line(api_client, opportunity, entry, quantity=3)

    response = api_client.patch(
        _quote_url(opportunity), {"discount_percent": "10"}, format="json"
    )

    assert response.status_code == 200
    assert response.data["subtotal"] == "3000.00"
    assert response.data["discount_amount"] == "300.00"
    assert response.data["total"] == "2700.00"


def test_a_discount_outside_the_range_is_refused(api_client, persistence_context):
    owner, _customer, opportunity, analysis, _ = persistence_context
    _draft(owner, opportunity, analysis)
    api_client.force_authenticate(user=owner)
    _add_line(api_client, opportunity, _entry(owner))

    response = api_client.patch(
        _quote_url(opportunity), {"discount_percent": "101"}, format="json"
    )

    assert response.status_code == 400


def test_removing_a_line_keeps_the_row_but_leaves_the_total(
    api_client, persistence_context
):
    owner, _customer, opportunity, analysis, _ = persistence_context
    _draft(owner, opportunity, analysis)
    entry = _entry(owner)
    api_client.force_authenticate(user=owner)
    line_id = _add_line(api_client, opportunity, entry, quantity=2).data["lines"][0]["id"]

    response = api_client.post(f"/api/quote-lines/{line_id}/remove/")

    assert response.status_code == 200
    quote = api_client.get(_quote_url(opportunity)).data
    assert quote["lines"] == []
    assert quote["total"] == "0.00"
    # The row survives for the audit trail: "priced, then withdrawn".
    assert QuoteLine.objects.get(pk=line_id).removed_at is not None


def test_a_new_draft_version_blocks_further_editing(
    api_client, persistence_context
):
    owner, _customer, opportunity, analysis, _ = persistence_context
    _draft(owner, opportunity, analysis, version=1)
    entry = _entry(owner)
    api_client.force_authenticate(user=owner)
    _add_line(api_client, opportunity, entry)
    _draft(owner, opportunity, analysis, version=2)

    added = _add_line(api_client, opportunity, entry)

    # Editing an outdated quote would price the old version without saying so.
    assert added.status_code == 409
    assert added.data["code"] == "quote_outdated"


def test_rebinding_moves_the_quote_to_the_newest_version(
    api_client, persistence_context
):
    owner, _customer, opportunity, analysis, _ = persistence_context
    first = _draft(owner, opportunity, analysis, version=1)
    entry = _entry(owner)
    api_client.force_authenticate(user=owner)
    _add_line(api_client, opportunity, entry)
    second = _draft(owner, opportunity, analysis, version=2)

    response = api_client.post(_quote_url(opportunity) + "rebind/")

    assert response.status_code == 200
    assert response.data["solution_draft"] == second.pk
    assert response.data["lines"][0]["unit_price"] == "1000.00"
    assert first.pk != second.pk


def test_export_refuses_a_quote_priced_for_another_version(
    persistence_context,
):
    owner, _customer, opportunity, analysis, _ = persistence_context
    first = _draft(owner, opportunity, analysis, version=1)
    quote = Quote.objects.create(
        opportunity=opportunity, solution_draft=first, created_by=owner
    )
    quote_service.add_line(
        quote=quote, actor=owner, entry=_entry(owner), quantity=1
    )
    second = _draft(owner, opportunity, analysis, version=2)

    with pytest.raises(QuoteError) as outdated:
        quote_service.quote_for_export(quote=quote, solution_draft_id=second.pk)
    assert outdated.value.code == QuoteErrorCode.OUTDATED

    with pytest.raises(QuoteError):
        quote_service.quote_for_export(quote=quote, solution_draft_id=first.pk)

    quote_service.rebind(quote, actor=owner)
    assert (
        quote_service.quote_for_export(quote=quote, solution_draft_id=second.pk)
        is quote
    )


def test_only_the_owner_or_an_admin_may_edit(
    api_client, persistence_context, user_factory
):
    owner, _customer, opportunity, analysis, _ = persistence_context
    _draft(owner, opportunity, analysis)
    entry = _entry(owner)
    api_client.force_authenticate(
        user=user_factory(UserRole.SALES, username="quote-stranger")
    )

    refused = _add_line(api_client, opportunity, entry)

    api_client.force_authenticate(
        user=user_factory(UserRole.ADMIN, username="quote-admin")
    )
    allowed = _add_line(api_client, opportunity, entry)

    # Invisible opportunity: not even a 403, so ids cannot be probed.
    assert refused.status_code == 404
    assert allowed.status_code == 201


def test_a_retired_price_entry_cannot_be_quoted(
    api_client, persistence_context
):
    owner, _customer, opportunity, analysis, _ = persistence_context
    _draft(owner, opportunity, analysis)
    retired = _entry(owner, sku="SKU-OLD", active=False)
    api_client.force_authenticate(user=owner)

    assert _add_line(api_client, opportunity, retired).status_code == 404


def test_a_quantity_must_be_positive(api_client, persistence_context):
    owner, _customer, opportunity, analysis, _ = persistence_context
    _draft(owner, opportunity, analysis)
    entry = _entry(owner)
    api_client.force_authenticate(user=owner)

    assert _add_line(api_client, opportunity, entry, quantity=0).status_code == 400


def test_the_quote_page_totals_the_lines_and_says_it_is_untaxed(
    persistence_context,
):
    owner, _customer, opportunity, analysis, _ = persistence_context
    draft = _draft(owner, opportunity, analysis)
    quote = Quote.objects.create(
        opportunity=opportunity,
        solution_draft=draft,
        discount_percent=Decimal("10"),
        created_by=owner,
    )
    quote_service.add_line(
        quote=quote, actor=owner, entry=_entry(owner, price="1000.00"), quantity=2
    )

    section = build_quote_section(quote)[0]
    table = next(block for block in section.blocks if block.kind == "table")
    text = " ".join(block.text for block in section.blocks)

    assert section.title == "报价（未含税）"
    assert table.rows[1][0] == "SKU-1"
    assert table.rows[1][5] == "2000.00"
    assert "合计 1800.00 CNY（未含税）" in text
    assert "正式报价以商务合同为准" in text


def test_an_empty_quote_produces_no_page(persistence_context):
    owner, _customer, opportunity, analysis, _ = persistence_context
    draft = _draft(owner, opportunity, analysis)
    quote = Quote.objects.create(
        opportunity=opportunity, solution_draft=draft, created_by=owner
    )

    assert build_quote_section(quote) == ()


def test_a_sample_price_marks_the_quote_and_blocks_the_export(
    api_client, persistence_context
):
    owner, _customer, opportunity, analysis, _ = persistence_context
    _draft(owner, opportunity, analysis)
    sample = PriceBookEntry.objects.create(
        sku="DEMO-PLATFORM",
        name="平台基础版",
        unit="套",
        unit_price=Decimal("380000.00"),
        effective_from=timezone.localdate() - timedelta(days=1),
        is_sample=True,
        created_by=owner,
    )
    api_client.force_authenticate(user=owner)
    _add_line(api_client, opportunity, sample, quantity=1)

    payload = api_client.get(_quote_url(opportunity)).data
    quote = Quote.objects.get(opportunity=opportunity)

    # The screen must be able to say "this is a sample" without guessing from
    # the SKU text.
    assert payload["contains_sample_data"] is True
    with pytest.raises(QuoteError) as blocked:
        quote_service.ensure_quote_exportable(quote)
    assert blocked.value.code == QuoteErrorCode.SAMPLE_DATA


def test_a_real_row_is_exportable(api_client, persistence_context):
    owner, _customer, opportunity, analysis, _ = persistence_context
    _draft(owner, opportunity, analysis)
    api_client.force_authenticate(user=owner)
    _add_line(api_client, opportunity, _entry(owner), quantity=1)
    quote = Quote.objects.get(opportunity=opportunity)

    payload = api_client.get(_quote_url(opportunity)).data

    assert payload["contains_sample_data"] is False
    # Discount is 0, below the threshold, so the only remaining gate passes.
    quote_service.ensure_quote_exportable(quote)
