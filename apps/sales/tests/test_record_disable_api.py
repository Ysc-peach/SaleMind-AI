"""Archiving a customer or an opportunity: hidden from lists, still readable."""

import pytest

from apps.accounts.models import UserRole
from apps.sales.models import Customer, Opportunity

pytestmark = pytest.mark.django_db

CUSTOMERS_URL = "/api/customers/"
CUSTOMER_SEARCH_URL = "/api/customers/search/"
OPPORTUNITIES_URL = "/api/opportunities/"


def _customer_action(pk, action):
    return f"{CUSTOMERS_URL}{pk}/{action}/"


def _opportunity_action(pk, action):
    return f"{OPPORTUNITIES_URL}{pk}/{action}/"


def _names(payload):
    return [item["name"] for item in payload["results"]]


def test_an_admin_can_archive_a_customer_and_it_leaves_the_working_list(
    api_client, user_factory, customer_factory
):
    admin = user_factory(UserRole.ADMIN)
    customer = customer_factory(name="Archived Co")
    api_client.force_authenticate(user=admin)

    response = api_client.post(_customer_action(customer.id, "disable"))

    assert response.status_code == 200
    assert response.data["is_active"] is False
    customer.refresh_from_db()
    assert customer.is_active is False
    # Customers are only reachable through search (there is no collection GET),
    # so that is the surface that must stop offering an archived record.
    search = api_client.get(CUSTOMER_SEARCH_URL, {"q": "Archived"})
    assert search.status_code == 200
    assert "Archived Co" not in _names(search.data)


def test_an_archived_customer_stays_readable_by_id(
    api_client, user_factory, customer_factory
):
    admin = user_factory(UserRole.ADMIN)
    customer = customer_factory(name="Old Co", is_active=False)
    api_client.force_authenticate(user=admin)

    response = api_client.get(f"{CUSTOMERS_URL}{customer.id}/")

    # Drafts, reviews and provenance still point here, so the row must open.
    assert response.status_code == 200
    assert response.data["is_active"] is False


def test_an_admin_can_search_archived_customers_explicitly(
    api_client, user_factory, customer_factory
):
    admin = user_factory(UserRole.ADMIN)
    customer_factory(name="Archived Co", is_active=False)
    api_client.force_authenticate(user=admin)

    response = api_client.get(
        CUSTOMER_SEARCH_URL, {"q": "Archived", "include_inactive": "1"}
    )

    assert response.status_code == 200
    assert "Archived Co" in _names(response.data)


def test_a_seller_cannot_archive_nor_ask_for_archived_rows(
    api_client, user_factory, customer_factory
):
    seller = user_factory(UserRole.SALES)
    customer = customer_factory(name="Mine")
    api_client.force_authenticate(user=seller)

    disable = api_client.post(_customer_action(customer.id, "disable"))
    listing = api_client.get(
        CUSTOMER_SEARCH_URL, {"q": "Mine", "include_inactive": "1"}
    )

    assert disable.status_code == 403
    assert listing.status_code == 403
    customer.refresh_from_db()
    assert customer.is_active is True


def test_editing_an_archived_customer_is_refused(
    api_client, user_factory, customer_factory
):
    seller = user_factory(UserRole.SALES)
    customer = customer_factory(name="Frozen", created_by=seller, is_active=False)
    api_client.force_authenticate(user=seller)

    response = api_client.patch(
        f"{CUSTOMERS_URL}{customer.id}/", {"name": "Renamed"}, format="json"
    )

    assert response.status_code == 409
    assert response.data["code"] == "record_inactive"
    customer.refresh_from_db()
    assert customer.name == "Frozen"


def test_the_archive_flag_cannot_be_flipped_through_a_patch(
    api_client, user_factory, customer_factory
):
    seller = user_factory(UserRole.SALES)
    customer = customer_factory(name="Mine", created_by=seller)
    api_client.force_authenticate(user=seller)

    response = api_client.patch(
        f"{CUSTOMERS_URL}{customer.id}/", {"is_active": False}, format="json"
    )

    assert response.status_code == 400
    assert "is_active" in response.data
    customer.refresh_from_db()
    assert customer.is_active is True


def test_a_new_opportunity_cannot_be_filed_under_an_archived_customer(
    api_client, user_factory, customer_factory
):
    seller = user_factory(UserRole.SALES)
    customer = customer_factory(name="Archived Co", is_active=False)
    api_client.force_authenticate(user=seller)

    response = api_client.post(
        OPPORTUNITIES_URL,
        {"project_name": "New deal", "customer": customer.id},
        format="json",
    )

    assert response.status_code == 400
    assert "customer" in response.data


def test_an_archived_opportunity_leaves_the_list_but_keeps_its_pages(
    api_client, user_factory, customer_factory, opportunity_factory
):
    seller = user_factory(UserRole.SALES)
    admin = user_factory(UserRole.ADMIN)
    customer = customer_factory(name="Acme")
    opportunity = opportunity_factory(customer, sales_owner=seller)
    api_client.force_authenticate(user=admin)

    assert api_client.post(
        _opportunity_action(opportunity.id, "disable")
    ).status_code == 200

    api_client.force_authenticate(user=seller)
    assert opportunity.project_name not in [
        item["project_name"] for item in api_client.get(OPPORTUNITIES_URL).data["results"]
    ]
    # Its own page, drafts and reviews stay reachable: history is not deleted.
    detail = api_client.get(f"{OPPORTUNITIES_URL}{opportunity.id}/")
    assert detail.status_code == 200
    assert detail.data["is_active"] is False
    drafts = api_client.get(f"{OPPORTUNITIES_URL}{opportunity.id}/solution-drafts/")
    assert drafts.status_code == 200


def test_new_work_is_refused_on_an_archived_opportunity(
    api_client, user_factory, customer_factory, opportunity_factory
):
    seller = user_factory(UserRole.SALES)
    customer = customer_factory(name="Acme")
    opportunity = opportunity_factory(
        customer, sales_owner=seller, is_active=False
    )
    api_client.force_authenticate(user=seller)

    analysis = api_client.post(
        f"{OPPORTUNITIES_URL}{opportunity.id}/ai/requirement-analyses/",
        {},
        format="json",
    )
    generation = api_client.post(
        f"{OPPORTUNITIES_URL}{opportunity.id}/solution-workflows/",
        {"analysis_id": 999999},
        format="json",
    )

    # 409 rather than 400: the request is well formed, the record is archived.
    assert analysis.status_code == 409
    assert generation.status_code == 409
    assert analysis.data["code"] == "record_inactive"


def test_re_enabling_restores_the_record(
    api_client, user_factory, customer_factory, opportunity_factory
):
    admin = user_factory(UserRole.ADMIN)
    seller = user_factory(UserRole.SALES)
    customer = customer_factory(name="Back Co")
    opportunity = opportunity_factory(customer, sales_owner=seller)
    api_client.force_authenticate(user=admin)

    api_client.post(_customer_action(customer.id, "disable"))
    api_client.post(_opportunity_action(opportunity.id, "disable"))
    api_client.post(_customer_action(customer.id, "enable"))
    api_client.post(_opportunity_action(opportunity.id, "enable"))

    api_client.force_authenticate(user=seller)
    restored = api_client.get(CUSTOMER_SEARCH_URL, {"q": "Back"})
    assert "Back Co" in _names(restored.data)
    assert opportunity.project_name in [
        item["project_name"] for item in api_client.get(OPPORTUNITIES_URL).data["results"]
    ]
    assert Customer.objects.get(pk=customer.pk).is_active is True
    assert Opportunity.objects.get(pk=opportunity.pk).is_active is True
