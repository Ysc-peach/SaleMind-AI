"""Consumer-facing tests for the Opportunity read and create APIs."""

from datetime import timedelta
from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.models import UserRole
from apps.sales.models import Customer, Opportunity, OpportunityStage, OpportunityStatus


pytestmark = pytest.mark.django_db

OPPORTUNITIES_URL = "/api/opportunities/"


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
    def create_customer(name="Acme", *, created_by=None):
        return Customer.objects.create(name=name, created_by=created_by or user_factory())

    return create_customer


@pytest.fixture
def opportunity_factory(user_factory, customer_factory):
    def create_opportunity(
        *,
        customer=None,
        sales_owner=None,
        presales_owner=None,
        project_name="Platform rollout",
        **overrides,
    ):
        sales_owner = sales_owner or user_factory(UserRole.SALES)
        customer = customer or customer_factory(created_by=sales_owner)
        return Opportunity.objects.create(
            project_name=project_name,
            customer=customer,
            sales_owner=sales_owner,
            presales_owner=presales_owner,
            created_by=sales_owner,
            raw_requirement="Shared requirements",
            budget=Decimal("120000.00"),
            **overrides,
        )

    return create_opportunity


def test_unauthenticated_opportunity_list_is_rejected(api_client):
    response = api_client.get(OPPORTUNITIES_URL)

    assert response.status_code == 401


def test_sales_can_create_opportunity_with_automatic_owners_and_defaults(
    api_client, user_factory, customer_factory
):
    actor = user_factory(UserRole.SALES)
    presales = user_factory(UserRole.PRESALES)
    customer = customer_factory(created_by=actor)
    api_client.force_authenticate(user=actor)

    response = api_client.post(
        OPPORTUNITIES_URL,
        {
            "project_name": "New rollout",
            "customer": customer.id,
            "presales_owner": presales.id,
            "raw_requirement": "Need a discovery workshop",
            "budget": "250000.00",
            "expected_launch_date": "2027-01-15",
        },
        format="json",
    )

    assert response.status_code == 201
    opportunity = Opportunity.objects.get(pk=response.data["id"])
    assert opportunity.sales_owner_id == actor.id
    assert opportunity.created_by_id == actor.id
    assert opportunity.presales_owner_id == presales.id
    assert opportunity.stage == OpportunityStage.INITIAL_CONTACT
    assert opportunity.status == OpportunityStatus.ACTIVE


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("sales_owner", 1),
        ("created_by", 1),
        ("stage", OpportunityStage.SOLUTION),
        ("status", OpportunityStatus.WON),
    ],
)
def test_create_rejects_each_server_controlled_field_without_creating_a_record(
    api_client, user_factory, customer_factory, field, value
):
    actor = user_factory(UserRole.SALES)
    customer = customer_factory(created_by=actor)
    api_client.force_authenticate(user=actor)
    count_before = Opportunity.objects.count()

    response = api_client.post(
        OPPORTUNITIES_URL,
        {"project_name": "Protected fields", "customer": customer.id, field: value},
        format="json",
    )

    assert response.status_code == 400
    assert field in response.data
    assert Opportunity.objects.count() == count_before


@pytest.mark.parametrize("field", ["sales_owner", "created_by", "stage", "status"])
def test_create_rejects_null_server_controlled_fields_without_creating_a_record(
    api_client, user_factory, customer_factory, field
):
    actor = user_factory(UserRole.SALES)
    customer = customer_factory(created_by=actor)
    api_client.force_authenticate(user=actor)
    count_before = Opportunity.objects.count()

    response = api_client.post(
        OPPORTUNITIES_URL,
        {"project_name": "Null protected field", "customer": customer.id, field: None},
        format="json",
    )

    assert response.status_code == 400
    assert field in response.data
    assert Opportunity.objects.count() == count_before


@pytest.mark.parametrize(
    "presales_setup",
    [
        pytest.param(
            lambda factory: factory(UserRole.SALES), id="user-with-a-non-presales-role"
        ),
        pytest.param(
            lambda factory: factory(UserRole.PRESALES, is_active=False),
            id="inactive-presales-user",
        ),
    ],
)
def test_create_rejects_non_active_presales_assignment(
    api_client, user_factory, customer_factory, presales_setup
):
    actor = user_factory(UserRole.SALES)
    customer = customer_factory(created_by=actor)
    invalid_presales = presales_setup(user_factory)
    api_client.force_authenticate(user=actor)

    response = api_client.post(
        OPPORTUNITIES_URL,
        {
            "project_name": "Invalid assignment",
            "customer": customer.id,
            "presales_owner": invalid_presales.id,
        },
        format="json",
    )

    assert response.status_code == 400
    assert "presales_owner" in response.data
    assert Opportunity.objects.filter(project_name="Invalid assignment").count() == 0


@pytest.mark.parametrize("role", [UserRole.ADMIN, UserRole.PRESALES])
def test_non_sales_users_cannot_create_opportunities(
    api_client, user_factory, customer_factory, role
):
    actor = user_factory(role)
    customer = customer_factory(created_by=actor)
    api_client.force_authenticate(user=actor)

    response = api_client.post(
        OPPORTUNITIES_URL,
        {"project_name": "Not allowed", "customer": customer.id},
        format="json",
    )

    assert response.status_code == 403
    assert not Opportunity.objects.filter(project_name="Not allowed").exists()


def test_sales_can_list_and_retrieve_only_their_own_opportunities(
    api_client, user_factory, opportunity_factory
):
    actor = user_factory(UserRole.SALES)
    other_sales = user_factory(UserRole.SALES)
    own = opportunity_factory(sales_owner=actor, project_name="Mine")
    other = opportunity_factory(sales_owner=other_sales, project_name="Theirs")
    api_client.force_authenticate(user=actor)

    list_response = api_client.get(OPPORTUNITIES_URL)
    own_detail = api_client.get(f"{OPPORTUNITIES_URL}{own.id}/")
    other_detail = api_client.get(f"{OPPORTUNITIES_URL}{other.id}/")

    assert list_response.status_code == 200
    assert [item["id"] for item in list_response.data["results"]] == [own.id]
    assert own_detail.status_code == 200
    assert own_detail.data["id"] == own.id
    assert other_detail.status_code == 404


def test_presales_can_list_and_retrieve_only_assigned_opportunities(
    api_client, user_factory, opportunity_factory
):
    actor = user_factory(UserRole.PRESALES)
    assigned = opportunity_factory(presales_owner=actor, project_name="Assigned")
    unassigned = opportunity_factory(project_name="Unassigned")
    api_client.force_authenticate(user=actor)

    list_response = api_client.get(OPPORTUNITIES_URL)
    assigned_detail = api_client.get(f"{OPPORTUNITIES_URL}{assigned.id}/")
    unassigned_detail = api_client.get(f"{OPPORTUNITIES_URL}{unassigned.id}/")

    assert list_response.status_code == 200
    assert [item["id"] for item in list_response.data["results"]] == [assigned.id]
    assert assigned_detail.status_code == 200
    assert unassigned_detail.status_code == 404


def test_admin_can_list_and_retrieve_every_opportunity(
    api_client, user_factory, opportunity_factory
):
    actor = user_factory(UserRole.ADMIN)
    first = opportunity_factory(project_name="First")
    second = opportunity_factory(project_name="Second")
    api_client.force_authenticate(user=actor)

    list_response = api_client.get(OPPORTUNITIES_URL)
    detail_response = api_client.get(f"{OPPORTUNITIES_URL}{second.id}/")

    assert list_response.status_code == 200
    assert {item["id"] for item in list_response.data["results"]} == {
        first.id,
        second.id,
    }
    assert detail_response.status_code == 200
    assert detail_response.data["id"] == second.id


def test_django_technical_flags_do_not_bypass_opportunity_roles(
    api_client, user_factory, opportunity_factory, customer_factory
):
    privileged_sales = user_factory(
        UserRole.SALES, is_staff=True, is_superuser=True
    )
    other_sales = user_factory(UserRole.SALES)
    own = opportunity_factory(sales_owner=privileged_sales, project_name="Own")
    other = opportunity_factory(sales_owner=other_sales, project_name="Other")
    api_client.force_authenticate(user=privileged_sales)

    list_response = api_client.get(OPPORTUNITIES_URL)
    detail_response = api_client.get(f"{OPPORTUNITIES_URL}{other.id}/")

    assert list_response.status_code == 200
    assert [item["id"] for item in list_response.data["results"]] == [own.id]
    assert detail_response.status_code == 404

    privileged_presales = user_factory(
        UserRole.PRESALES, is_staff=True, is_superuser=True
    )
    customer = customer_factory(created_by=privileged_sales)
    api_client.force_authenticate(user=privileged_presales)

    create_response = api_client.post(
        OPPORTUNITIES_URL,
        {"project_name": "Technical flags", "customer": customer.id},
        format="json",
    )

    assert create_response.status_code == 403


def test_opportunity_list_uses_twenty_item_pages_and_updated_at_id_descending_order(
    api_client, user_factory, opportunity_factory
):
    actor = user_factory(UserRole.SALES)
    older_timestamp = timezone.now() - timedelta(days=2)
    newer_timestamp = older_timestamp + timedelta(days=1)
    newer_opportunities = [
        opportunity_factory(sales_owner=actor, project_name=f"Newer {index:02d}")
        for index in range(5)
    ]
    older_opportunities = [
        opportunity_factory(sales_owner=actor, project_name=f"Older {index:02d}")
        for index in range(16)
    ]
    Opportunity.objects.filter(
        pk__in=[item.id for item in newer_opportunities]
    ).update(updated_at=newer_timestamp)
    Opportunity.objects.filter(
        pk__in=[item.id for item in older_opportunities]
    ).update(updated_at=older_timestamp)
    api_client.force_authenticate(user=actor)

    first_page = api_client.get(OPPORTUNITIES_URL)
    second_page = api_client.get(OPPORTUNITIES_URL, {"page": 2})
    expected_ids = sorted(
        (item.id for item in newer_opportunities), reverse=True
    ) + sorted((item.id for item in older_opportunities), reverse=True)

    assert first_page.status_code == 200
    assert first_page.data["count"] == 21
    assert [item["id"] for item in first_page.data["results"]] == expected_ids[:20]
    assert second_page.status_code == 200
    assert [item["id"] for item in second_page.data["results"]] == expected_ids[20:]


def test_sales_can_patch_every_allowed_opportunity_field(
    api_client, user_factory, opportunity_factory
):
    actor = user_factory(UserRole.SALES)
    presales = user_factory(UserRole.PRESALES)
    opportunity = opportunity_factory(sales_owner=actor)
    api_client.force_authenticate(user=actor)

    response = api_client.patch(
        f"{OPPORTUNITIES_URL}{opportunity.id}/",
        {
            "project_name": "Revised rollout",
            "presales_owner": presales.id,
            "raw_requirement": "Revised discovery requirements",
            "budget": "999999.99",
            "stage": OpportunityStage.SOLUTION,
            "status": OpportunityStatus.WON,
            "expected_launch_date": "2027-03-15",
        },
        format="json",
    )

    assert response.status_code == 200
    opportunity.refresh_from_db()
    assert opportunity.project_name == "Revised rollout"
    assert opportunity.presales_owner_id == presales.id
    assert opportunity.raw_requirement == "Revised discovery requirements"
    assert opportunity.budget == Decimal("999999.99")
    assert opportunity.stage == OpportunityStage.SOLUTION
    assert opportunity.status == OpportunityStatus.WON
    assert str(opportunity.expected_launch_date) == "2027-03-15"


def test_sales_can_patch_null_presales_owner_to_remove_assignment(
    api_client, user_factory, opportunity_factory
):
    actor = user_factory(UserRole.SALES)
    presales = user_factory(UserRole.PRESALES)
    opportunity = opportunity_factory(sales_owner=actor, presales_owner=presales)
    api_client.force_authenticate(user=actor)

    response = api_client.patch(
        f"{OPPORTUNITIES_URL}{opportunity.id}/",
        {"presales_owner": None},
        format="json",
    )

    assert response.status_code == 200
    opportunity.refresh_from_db()
    assert opportunity.presales_owner is None


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("customer", lambda users, customer: customer.id),
        ("sales_owner", lambda users, customer: users[0].id),
        ("created_by", lambda users, customer: users[1].id),
        ("created_at", lambda users, customer: "2027-01-01T00:00:00Z"),
        ("updated_at", lambda users, customer: "2027-01-02T00:00:00Z"),
    ],
)
def test_patch_rejects_each_server_controlled_field_without_partial_update(
    api_client, user_factory, customer_factory, opportunity_factory, field, value
):
    actor = user_factory(UserRole.SALES)
    other_customer = customer_factory(created_by=actor, name="Other customer")
    opportunity = opportunity_factory(sales_owner=actor)
    before = {
        "project_name": opportunity.project_name,
        "customer_id": opportunity.customer_id,
        "sales_owner_id": opportunity.sales_owner_id,
        "presales_owner_id": opportunity.presales_owner_id,
        "created_by_id": opportunity.created_by_id,
        "raw_requirement": opportunity.raw_requirement,
        "budget": opportunity.budget,
        "stage": opportunity.stage,
        "status": opportunity.status,
        "expected_launch_date": opportunity.expected_launch_date,
        "created_at": opportunity.created_at,
        "updated_at": opportunity.updated_at,
    }
    api_client.force_authenticate(user=actor)

    response = api_client.patch(
        f"{OPPORTUNITIES_URL}{opportunity.id}/",
        {
            "project_name": "This must not persist",
            field: value((user_factory(), user_factory()), other_customer),
        },
        format="json",
    )

    assert response.status_code == 400
    assert field in response.data
    opportunity.refresh_from_db()
    assert opportunity.project_name == before["project_name"]
    assert opportunity.customer_id == before["customer_id"]
    assert opportunity.sales_owner_id == before["sales_owner_id"]
    assert opportunity.presales_owner_id == before["presales_owner_id"]
    assert opportunity.created_by_id == before["created_by_id"]
    assert opportunity.raw_requirement == before["raw_requirement"]
    assert opportunity.budget == before["budget"]
    assert opportunity.stage == before["stage"]
    assert opportunity.status == before["status"]
    assert opportunity.expected_launch_date == before["expected_launch_date"]
    assert opportunity.created_at == before["created_at"]
    assert opportunity.updated_at == before["updated_at"]


@pytest.mark.parametrize(
    "field", ["customer", "sales_owner", "created_by", "created_at", "updated_at"]
)
def test_patch_rejects_null_server_controlled_keys_without_partial_update(
    api_client, user_factory, opportunity_factory, field
):
    actor = user_factory(UserRole.SALES)
    opportunity = opportunity_factory(sales_owner=actor)
    before = {
        "project_name": opportunity.project_name,
        "customer_id": opportunity.customer_id,
        "sales_owner_id": opportunity.sales_owner_id,
        "created_by_id": opportunity.created_by_id,
        "presales_owner_id": opportunity.presales_owner_id,
        "raw_requirement": opportunity.raw_requirement,
        "budget": opportunity.budget,
        "stage": opportunity.stage,
        "status": opportunity.status,
        "expected_launch_date": opportunity.expected_launch_date,
        "created_at": opportunity.created_at,
        "updated_at": opportunity.updated_at,
    }
    api_client.force_authenticate(user=actor)

    response = api_client.patch(
        f"{OPPORTUNITIES_URL}{opportunity.id}/",
        {"project_name": "This must not persist", field: None},
        format="json",
    )

    assert response.status_code == 400
    assert field in response.data
    opportunity.refresh_from_db()
    assert opportunity.project_name == before["project_name"]
    assert opportunity.customer_id == before["customer_id"]
    assert opportunity.sales_owner_id == before["sales_owner_id"]
    assert opportunity.created_by_id == before["created_by_id"]
    assert opportunity.presales_owner_id == before["presales_owner_id"]
    assert opportunity.raw_requirement == before["raw_requirement"]
    assert opportunity.budget == before["budget"]
    assert opportunity.stage == before["stage"]
    assert opportunity.status == before["status"]
    assert opportunity.expected_launch_date == before["expected_launch_date"]
    assert opportunity.created_at == before["created_at"]
    assert opportunity.updated_at == before["updated_at"]


@pytest.mark.parametrize(
    "invalid_presales",
    [
        pytest.param(lambda factory: factory(UserRole.SALES), id="non-presales-user"),
        pytest.param(
            lambda factory: factory(UserRole.PRESALES, is_active=False),
            id="inactive-presales-user",
        ),
    ],
)
def test_patch_rejects_non_active_presales_assignment(
    api_client, user_factory, opportunity_factory, invalid_presales
):
    actor = user_factory(UserRole.SALES)
    opportunity = opportunity_factory(sales_owner=actor)
    invalid_user = invalid_presales(user_factory)
    original_project_name = opportunity.project_name
    original_updated_at = opportunity.updated_at
    api_client.force_authenticate(user=actor)

    response = api_client.patch(
        f"{OPPORTUNITIES_URL}{opportunity.id}/",
        {"project_name": "This must not persist", "presales_owner": invalid_user.id},
        format="json",
    )

    assert response.status_code == 400
    assert "presales_owner" in response.data
    opportunity.refresh_from_db()
    assert opportunity.project_name == original_project_name
    assert opportunity.presales_owner is None
    assert opportunity.updated_at == original_updated_at


def test_other_sales_cannot_patch_an_opportunity_they_do_not_own(
    api_client, user_factory, opportunity_factory
):
    owner = user_factory(UserRole.SALES)
    other_sales = user_factory(UserRole.SALES, is_staff=True, is_superuser=True)
    opportunity = opportunity_factory(sales_owner=owner)
    api_client.force_authenticate(user=other_sales)

    response = api_client.patch(
        f"{OPPORTUNITIES_URL}{opportunity.id}/",
        {"project_name": "Unauthorized change"},
        format="json",
    )

    assert response.status_code == 404
    opportunity.refresh_from_db()
    assert opportunity.project_name == "Platform rollout"


@pytest.mark.parametrize(
    "role", [UserRole.ADMIN, UserRole.PRESALES]
)
def test_admin_and_presales_cannot_patch_opportunities(
    api_client, user_factory, opportunity_factory, role
):
    actor = user_factory(role, is_staff=True, is_superuser=True)
    opportunity = opportunity_factory()
    api_client.force_authenticate(user=actor)

    response = api_client.patch(
        f"{OPPORTUNITIES_URL}{opportunity.id}/",
        {"project_name": "Unauthorized change"},
        format="json",
    )

    assert response.status_code == 403
    opportunity.refresh_from_db()
    assert opportunity.project_name == "Platform rollout"


def test_opportunity_put_and_delete_methods_remain_unavailable(
    api_client, user_factory, opportunity_factory
):
    actor = user_factory(UserRole.SALES)
    opportunity = opportunity_factory(sales_owner=actor)
    api_client.force_authenticate(user=actor)

    put_response = api_client.put(
        f"{OPPORTUNITIES_URL}{opportunity.id}/",
        {"project_name": "Changed"},
        format="json",
    )
    delete_response = api_client.delete(f"{OPPORTUNITIES_URL}{opportunity.id}/")

    assert put_response.status_code == 405
    assert delete_response.status_code == 405
    assert Opportunity.objects.get(pk=opportunity.id).project_name == "Platform rollout"
