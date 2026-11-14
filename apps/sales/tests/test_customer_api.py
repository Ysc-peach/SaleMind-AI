"""Consumer-facing tests for the Customer APIs."""

from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

from apps.accounts.models import UserRole
from apps.sales.models import Customer, Opportunity, OpportunityStage, OpportunityStatus


pytestmark = pytest.mark.django_db

CUSTOMERS_URL = "/api/customers/"
CUSTOMER_SEARCH_URL = "/api/customers/search/"


@pytest.fixture
def api_client():
    return APIClient()


@pytest.fixture
def user_factory():
    sequence = 0

    def create_user(
        role=UserRole.SALES,
        *,
        username=None,
        is_active=True,
        is_staff=False,
        is_superuser=False,
    ):
        nonlocal sequence
        sequence += 1
        username = username or f"user-{sequence}"
        return get_user_model().objects.create_user(
            username=username,
            email=f"{username}@example.com",
            role=role,
            password="StrongPassword123!",
            is_active=is_active,
            is_staff=is_staff,
            is_superuser=is_superuser,
        )

    return create_user


@pytest.fixture
def customer_factory(user_factory):
    def create_customer(name="Acme", *, created_by=None, **overrides):
        created_by = created_by or user_factory()
        return Customer.objects.create(name=name, created_by=created_by, **overrides)

    return create_customer


@pytest.fixture
def opportunity_factory(user_factory):
    def create_opportunity(
        customer,
        *,
        sales_owner=None,
        project_name="Platform rollout",
        status=OpportunityStatus.ACTIVE,
        stage=OpportunityStage.INITIAL_CONTACT,
        **overrides,
    ):
        sales_owner = sales_owner or user_factory(UserRole.SALES)
        return Opportunity.objects.create(
            project_name=project_name,
            customer=customer,
            sales_owner=sales_owner,
            created_by=sales_owner,
            status=status,
            stage=stage,
            raw_requirement="confidential raw requirement",
            budget=Decimal("120000.00"),
            **overrides,
        )

    return create_opportunity


def test_unauthenticated_customer_search_is_rejected(api_client):
    response = api_client.get(CUSTOMER_SEARCH_URL, {"q": "acme"})

    assert response.status_code == 401


def test_sales_can_create_customer_and_created_by_is_stored_but_hidden(
    api_client, user_factory
):
    actor = user_factory(UserRole.SALES)
    api_client.force_authenticate(user=actor)

    response = api_client.post(
        CUSTOMERS_URL,
        {
            "name": "Acme Corporation",
            "industry": "Software",
            "company_size": "Enterprise",
            "basic_info": "Shared company information",
        },
        format="json",
    )

    assert response.status_code == 201
    customer = Customer.objects.get(pk=response.data["id"])
    assert customer.created_by_id == actor.id
    assert response.data["name"] == "Acme Corporation"
    assert response.data["industry"] == "Software"
    assert response.data["company_size"] == "Enterprise"
    assert response.data["basic_info"] == "Shared company information"
    assert "created_by" not in response.data


def test_admin_can_create_customer(api_client, user_factory):
    actor = user_factory(UserRole.ADMIN)
    api_client.force_authenticate(user=actor)

    response = api_client.post(CUSTOMERS_URL, {"name": "Admin customer"}, format="json")

    assert response.status_code == 201
    assert Customer.objects.get(pk=response.data["id"]).created_by_id == actor.id


def test_presales_cannot_create_search_or_retrieve_customers(
    api_client, user_factory, customer_factory
):
    customer = customer_factory()
    actor = user_factory(UserRole.PRESALES)
    api_client.force_authenticate(user=actor)

    create_response = api_client.post(CUSTOMERS_URL, {"name": "No access"}, format="json")
    retrieve_response = api_client.get(f"{CUSTOMERS_URL}{customer.id}/")
    search_response = api_client.get(CUSTOMER_SEARCH_URL, {"q": "acme"})

    assert create_response.status_code == 403
    assert retrieve_response.status_code == 403
    assert search_response.status_code == 403


def test_duplicate_customer_names_are_allowed_through_the_api(
    api_client, user_factory
):
    actor = user_factory(UserRole.SALES)
    api_client.force_authenticate(user=actor)

    first = api_client.post(CUSTOMERS_URL, {"name": "Same name"}, format="json")
    second = api_client.post(CUSTOMERS_URL, {"name": "Same name"}, format="json")

    assert first.status_code == 201
    assert second.status_code == 201
    assert first.data["id"] != second.data["id"]
    assert Customer.objects.filter(name="Same name").count() == 2


@pytest.mark.parametrize("query", [None, ""])
def test_customer_search_requires_a_nonempty_q(api_client, user_factory, query):
    actor = user_factory(UserRole.SALES)
    api_client.force_authenticate(user=actor)

    params = {} if query is None else {"q": query}
    response = api_client.get(CUSTOMER_SEARCH_URL, params)

    assert response.status_code == 400


def test_customer_search_is_case_insensitive_and_ordered_by_name_then_id(
    api_client, user_factory, customer_factory
):
    actor = user_factory(UserRole.SALES)
    first = customer_factory("Acme", created_by=actor)
    second = customer_factory("Acme", created_by=actor)
    third = customer_factory("Acme Labs", created_by=actor)
    customer_factory("Different", created_by=actor)
    api_client.force_authenticate(user=actor)

    response = api_client.get(CUSTOMER_SEARCH_URL, {"q": "ACME"})

    assert response.status_code == 200
    assert [item["id"] for item in response.data["results"]] == [
        first.id,
        second.id,
        third.id,
    ]
    assert all("created_by" not in item for item in response.data["results"])


def test_customer_search_uses_twenty_item_page_size(
    api_client, user_factory, customer_factory
):
    actor = user_factory(UserRole.SALES)
    for index in range(21):
        customer_factory(f"Paged customer {index:02d}", created_by=actor)
    api_client.force_authenticate(user=actor)

    first_page = api_client.get(CUSTOMER_SEARCH_URL, {"q": "paged"})
    second_page = api_client.get(CUSTOMER_SEARCH_URL, {"q": "paged", "page": 2})

    assert first_page.status_code == 200
    assert first_page.data["count"] == 21
    assert len(first_page.data["results"]) == 20
    assert second_page.status_code == 200
    assert len(second_page.data["results"]) == 1


def test_customer_detail_includes_only_active_safe_opportunity_summaries(
    api_client, user_factory, customer_factory, opportunity_factory
):
    actor = user_factory(UserRole.SALES)
    other_sales = user_factory(UserRole.SALES)
    customer = customer_factory(created_by=actor)
    own_active = opportunity_factory(customer, sales_owner=actor, project_name="Own active")
    other_active = opportunity_factory(
        customer, sales_owner=other_sales, project_name="Other active"
    )
    opportunity_factory(customer, sales_owner=actor, status=OpportunityStatus.WON)
    opportunity_factory(customer, sales_owner=actor, status=OpportunityStatus.LOST)
    opportunity_factory(customer, sales_owner=actor, status=OpportunityStatus.CLOSED)
    api_client.force_authenticate(user=actor)

    response = api_client.get(f"{CUSTOMERS_URL}{customer.id}/")

    assert response.status_code == 200
    assert "created_by" not in response.data
    summaries = response.data["opportunities"]
    assert {item["id"] for item in summaries} == {own_active.id, other_active.id}
    assert all(
        set(item) == {
            "id",
            "project_name",
            "stage",
            "status",
            "is_mine",
            "is_followed_by_other_sales",
        }
        for item in summaries
    )
    own_summary = next(item for item in summaries if item["id"] == own_active.id)
    other_summary = next(item for item in summaries if item["id"] == other_active.id)
    assert own_summary["is_mine"] is True
    assert own_summary["is_followed_by_other_sales"] is False
    assert other_summary["is_mine"] is False
    assert other_summary["is_followed_by_other_sales"] is True
    assert all(
        "raw_requirement" not in item
        and "budget" not in item
        and "sales_owner" not in item
        and "created_by" not in item
        for item in summaries
    )


def test_customer_search_uses_the_same_safe_active_summary_contract(
    api_client, user_factory, customer_factory, opportunity_factory
):
    actor = user_factory(UserRole.SALES)
    customer = customer_factory("Searchable", created_by=actor)
    active = opportunity_factory(customer, sales_owner=actor, project_name="Search active")
    opportunity_factory(customer, sales_owner=actor, status=OpportunityStatus.CLOSED)
    api_client.force_authenticate(user=actor)

    response = api_client.get(CUSTOMER_SEARCH_URL, {"q": "searchable"})

    assert response.status_code == 200
    result = response.data["results"][0]
    assert "created_by" not in result
    assert result["opportunities"] == [
        {
            "id": active.id,
            "project_name": "Search active",
            "stage": OpportunityStage.INITIAL_CONTACT,
            "status": OpportunityStatus.ACTIVE,
            "is_mine": True,
            "is_followed_by_other_sales": False,
        }
    ]


def test_customer_collection_put_and_delete_stay_unavailable(
    api_client, user_factory, customer_factory
):
    actor = user_factory(UserRole.SALES)
    customer = customer_factory(created_by=actor)
    api_client.force_authenticate(user=actor)

    collection_response = api_client.get(CUSTOMERS_URL)
    put_response = api_client.put(
        f"{CUSTOMERS_URL}{customer.id}/", {"name": "Changed"}, format="json"
    )
    delete_response = api_client.delete(f"{CUSTOMERS_URL}{customer.id}/")

    assert collection_response.status_code == 405
    assert put_response.status_code == 405
    assert delete_response.status_code == 405
    assert Customer.objects.get(pk=customer.id).name == "Acme"


def test_the_owner_can_correct_a_customer_record(
    api_client, user_factory, customer_factory
):
    actor = user_factory(UserRole.SALES)
    customer = customer_factory(
        created_by=actor, industry="Manufacturing", company_size="200-500",
    )
    api_client.force_authenticate(user=actor)

    response = api_client.patch(
        f"{CUSTOMERS_URL}{customer.id}/",
        {
            "name": "Acme Industrial",
            "industry": "Industrial equipment",
            "basic_info": "Corrected after the kickoff call.",
        },
        format="json",
    )

    assert response.status_code == 200
    assert response.data["name"] == "Acme Industrial"
    assert response.data["industry"] == "Industrial equipment"
    # Untouched fields keep their previous value on a partial update.
    assert response.data["company_size"] == "200-500"
    customer.refresh_from_db()
    assert customer.name == "Acme Industrial"
    assert customer.created_by_id == actor.pk


def test_another_seller_can_correct_a_shared_customer_record(
    api_client, user_factory, customer_factory
):
    owner = user_factory(UserRole.SALES)
    colleague = user_factory(UserRole.SALES)
    customer = customer_factory(created_by=owner)
    api_client.force_authenticate(user=colleague)

    response = api_client.patch(
        f"{CUSTOMERS_URL}{customer.id}/", {"industry": "Finance"}, format="json",
    )

    assert response.status_code == 200
    customer.refresh_from_db()
    assert customer.industry == "Finance"
    # Correction does not transfer ownership.
    assert customer.created_by_id == owner.pk


def test_an_admin_can_correct_any_customer(
    api_client, user_factory, customer_factory
):
    owner = user_factory(UserRole.SALES)
    admin = user_factory(UserRole.ADMIN)
    customer = customer_factory(created_by=owner)
    api_client.force_authenticate(user=admin)

    response = api_client.patch(
        f"{CUSTOMERS_URL}{customer.id}/", {"industry": "Public sector"}, format="json",
    )

    assert response.status_code == 200
    assert response.data["industry"] == "Public sector"


def test_customer_ownership_and_timestamps_cannot_be_rewritten(
    api_client, user_factory, customer_factory
):
    actor = user_factory(UserRole.SALES)
    other = user_factory(UserRole.SALES)
    customer = customer_factory(created_by=actor)
    original_created_at = customer.created_at
    api_client.force_authenticate(user=actor)

    response = api_client.patch(
        f"{CUSTOMERS_URL}{customer.id}/",
        {"created_by": other.pk, "created_at": "2020-01-01T00:00:00Z"},
        format="json",
    )

    assert response.status_code == 400
    assert set(response.data) == {"created_by", "created_at"}
    customer.refresh_from_db()
    assert customer.created_by_id == actor.pk
    assert customer.created_at == original_created_at


def test_a_presales_user_cannot_edit_a_customer(
    api_client, user_factory, customer_factory
):
    owner = user_factory(UserRole.SALES)
    presales = user_factory(UserRole.PRESALES)
    customer = customer_factory(created_by=owner)
    api_client.force_authenticate(user=presales)

    response = api_client.patch(
        f"{CUSTOMERS_URL}{customer.id}/", {"name": "Changed"}, format="json",
    )

    assert response.status_code == 403
    assert Customer.objects.get(pk=customer.id).name == "Acme"
