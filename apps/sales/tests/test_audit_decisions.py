"""Archiving and discount approvals are decisions, so the audit must show them."""

from decimal import Decimal

import pytest

from apps.accounts.models import UserRole
from apps.sales.models import (
    Quote,
    QuoteDiscountApproval,
    RecordStateChange,
)

pytestmark = pytest.mark.django_db

AUDIT_URL = "/api/audit/events/"


def _archive(api_client, record, action: str) -> None:
    response = api_client.post(f"/api/{record}/{action}/")
    assert response.status_code == 200, response.data


def test_archiving_a_customer_records_who_did_it(
    api_client, user_factory, customer_factory
):
    admin = user_factory(UserRole.ADMIN, username="audit-admin")
    customer = customer_factory(name="Archived Co")
    api_client.force_authenticate(user=admin)

    _archive(api_client, f"customers/{customer.id}", "disable")

    event = RecordStateChange.objects.get()
    assert event.kind == "customer"
    assert event.record_id == customer.id
    assert event.record_name == "Archived Co"
    assert event.is_active is False
    assert event.actor_id == admin.pk


def test_restoring_records_a_second_entry(api_client, user_factory, customer_factory):
    admin = user_factory(UserRole.ADMIN)
    customer = customer_factory(name="Back Co")
    api_client.force_authenticate(user=admin)

    _archive(api_client, f"customers/{customer.id}", "disable")
    _archive(api_client, f"customers/{customer.id}", "enable")

    assert list(
        RecordStateChange.objects.order_by("id").values_list("is_active", flat=True)
    ) == [False, True]


def test_archiving_twice_records_one_decision(
    api_client, user_factory, customer_factory
):
    admin = user_factory(UserRole.ADMIN)
    customer = customer_factory(name="Once Only")
    api_client.force_authenticate(user=admin)

    _archive(api_client, f"customers/{customer.id}", "disable")
    _archive(api_client, f"customers/{customer.id}", "disable")

    # Re-archiving an archived record is not a new decision.
    assert RecordStateChange.objects.count() == 1


def test_the_snapshot_survives_a_rename(api_client, user_factory, customer_factory):
    admin = user_factory(UserRole.ADMIN)
    customer = customer_factory(name="Old Name")
    api_client.force_authenticate(user=admin)
    _archive(api_client, f"customers/{customer.id}", "disable")

    customer.name = "New Name"
    customer.save(update_fields=["name"])

    # The audit answers "what did the person see at the time", so a rename must
    # not rewrite it.
    assert RecordStateChange.objects.get().record_name == "Old Name"


def test_an_opportunity_archive_is_labelled_as_such(
    api_client, user_factory, customer_factory, opportunity_factory
):
    admin = user_factory(UserRole.ADMIN)
    opportunity = opportunity_factory(
        customer_factory(name="Acme"), project_name="Doomed deal"
    )
    api_client.force_authenticate(user=admin)

    _archive(api_client, f"opportunities/{opportunity.id}", "disable")

    event = RecordStateChange.objects.get()
    assert event.kind == "opportunity"
    assert event.record_name == "Doomed deal"


def test_the_audit_payload_carries_the_archive_section(
    api_client, user_factory, customer_factory
):
    admin = user_factory(UserRole.ADMIN, username="audit-admin")
    customer = customer_factory(name="Archived Co")
    api_client.force_authenticate(user=admin)
    _archive(api_client, f"customers/{customer.id}", "disable")

    payload = api_client.get(AUDIT_URL).data

    assert payload["archives"]["count"] == 1
    row = payload["archives"]["results"][0]
    assert row["kind_label"] == "客户"
    assert row["record_name"] == "Archived Co"
    assert row["is_active"] is False
    assert row["actor"]


def test_the_actor_filter_finds_an_archive_by_display_name(
    api_client, user_factory, customer_factory
):
    admin = user_factory(UserRole.ADMIN, username="audit-admin")
    admin.first_name = "审计管理员"
    admin.save(update_fields=["first_name"])
    other = user_factory(UserRole.ADMIN, username="other-admin")
    customer = customer_factory(name="Archived Co")
    api_client.force_authenticate(user=admin)
    _archive(api_client, f"customers/{customer.id}", "disable")

    by_name = api_client.get(AUDIT_URL, {"actor": "审计管理员"}).data
    by_stranger = api_client.get(AUDIT_URL, {"actor": "not-a-person"}).data

    assert by_name["archives"]["count"] == 1
    assert by_stranger["archives"]["count"] == 0
    assert other.pk != admin.pk


def test_a_discount_decision_appears_in_the_audit(
    api_client, user_factory, customer_factory, opportunity_factory
):
    admin = user_factory(UserRole.ADMIN, username="audit-admin")
    opportunity = opportunity_factory(
        customer_factory(name="Acme"), project_name="Big deal"
    )
    quote = Quote.objects.create(opportunity=opportunity, created_by=admin)
    QuoteDiscountApproval.objects.create(
        quote=quote,
        discount_percent=Decimal("20.00"),
        status="approved",
        comment="首单让利",
        decided_by=admin,
    )
    api_client.force_authenticate(user=admin)

    payload = api_client.get(AUDIT_URL).data

    assert payload["discount_decisions"]["count"] == 1
    row = payload["discount_decisions"]["results"][0]
    assert row["project_name"] == "Big deal"
    assert row["discount_percent"] == "20.00"
    assert row["status"] == "APPROVED"
    assert row["comment"] == "首单让利"


def test_a_status_filter_does_not_hide_archives(
    api_client, user_factory, customer_factory
):
    admin = user_factory(UserRole.ADMIN)
    customer = customer_factory(name="Archived Co")
    api_client.force_authenticate(user=admin)
    _archive(api_client, f"customers/{customer.id}", "disable")

    payload = api_client.get(AUDIT_URL, {"status": "APPROVED"}).data

    # Archives have a state, not a review decision, so the status filter does not
    # apply to them — and the response must still show the row.
    assert payload["archives"]["count"] == 1
