"""Consumer-facing tests for the active Presales options endpoint."""

import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

from apps.accounts.api.views import PresalesOptionListView
from apps.accounts.models import UserRole


pytestmark = pytest.mark.django_db

PRESALES_OPTIONS_URL = "/api/users/presales-options/"


@pytest.fixture
def api_client():
    return APIClient()


@pytest.fixture
def user_factory():
    def create_user(
        username,
        role=UserRole.SALES,
        *,
        first_name="",
        last_name="",
        is_active=True,
    ):
        return get_user_model().objects.create_user(
            username=username,
            email=f"{username}@example.com",
            role=role,
            password="StrongPassword123!",
            first_name=first_name,
            last_name=last_name,
            is_active=is_active,
        )

    return create_user


def test_unauthenticated_request_is_rejected(api_client):
    response = api_client.get(PRESALES_OPTIONS_URL)

    assert response.status_code == 401


def test_sales_can_list_only_active_presales_with_exact_fields_and_stable_order(
    api_client, user_factory
):
    actor = user_factory("sales-actor", first_name="Sales", last_name="Actor")
    later_username = user_factory(
        "zoe",
        UserRole.PRESALES,
        first_name="Zoe",
        last_name="Presales",
    )
    earlier_username = user_factory(
        "alice",
        UserRole.PRESALES,
        first_name="Alice",
        last_name="Presales",
    )
    user_factory("inactive", UserRole.PRESALES, is_active=False)
    user_factory("another-sales", UserRole.SALES)
    user_factory("an-admin", UserRole.ADMIN)
    api_client.force_authenticate(user=actor)

    response = api_client.get(PRESALES_OPTIONS_URL)

    assert response.status_code == 200
    assert response.data == [
        {
            "id": earlier_username.id,
            "username": "alice",
            "first_name": "Alice",
            "last_name": "Presales",
        },
        {
            "id": later_username.id,
            "username": "zoe",
            "first_name": "Zoe",
            "last_name": "Presales",
        },
    ]


def test_presales_options_query_orders_by_username_then_id():
    queryset = PresalesOptionListView().get_queryset()

    assert queryset.query.order_by == ("username", "id")


@pytest.mark.parametrize("role", [UserRole.ADMIN, UserRole.PRESALES])
def test_admin_and_presales_cannot_list_presales_options(api_client, user_factory, role):
    actor = user_factory(f"{role}-actor", role)
    api_client.force_authenticate(user=actor)

    response = api_client.get(PRESALES_OPTIONS_URL)

    assert response.status_code == 403
