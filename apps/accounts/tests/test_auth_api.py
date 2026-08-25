"""Consumer-facing tests for JWT authentication endpoints."""

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse
from rest_framework.test import APIClient

from apps.accounts.models import UserRole


pytestmark = pytest.mark.django_db


@pytest.fixture
def api_client():
    return APIClient()


@pytest.fixture
def user(user_data):
    return get_user_model().objects.create_user(
        **user_data,
        first_name="Alice",
        last_name="Seller",
    )


def login(api_client, username="alice", password="StrongPassword123!"):
    return api_client.post(
        reverse("auth-login"),
        {"username": username, "password": password},
        format="json",
    )


def test_login_returns_access_and_refresh_for_valid_credentials(api_client, user):
    response = login(api_client)

    assert response.status_code == 200
    assert set(response.data) == {"access", "refresh"}
    assert all(isinstance(response.data[key], str) for key in ("access", "refresh"))


def test_login_rejects_wrong_password(api_client, user):
    response = login(api_client, password="WrongPassword123!")

    assert response.status_code == 401
    assert set(response.data) == {"detail"}


def test_login_rejects_unknown_username(api_client):
    response = login(api_client, username="unknown")

    assert response.status_code == 401
    assert set(response.data) == {"detail"}


def test_login_rejects_inactive_user(api_client, user):
    user.is_active = False
    user.save(update_fields=["is_active"])

    response = login(api_client)

    assert response.status_code == 401
    assert set(response.data) == {"detail"}


def test_me_rejects_unauthenticated_request(api_client):
    response = api_client.get(reverse("auth-me"))

    assert response.status_code == 401


def test_me_returns_current_user_and_role(api_client, user):
    tokens = login(api_client).data
    api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {tokens['access']}")

    response = api_client.get(reverse("auth-me"))

    assert response.status_code == 200
    assert response.data == {
        "id": user.id,
        "username": "alice",
        "email": "alice@example.com",
        "first_name": "Alice",
        "last_name": "Seller",
        "role": UserRole.SALES,
    }


def test_refresh_returns_new_access_token(api_client, user):
    refresh = login(api_client).data["refresh"]

    response = api_client.post(
        reverse("auth-refresh"),
        {"refresh": refresh},
        format="json",
    )

    assert response.status_code == 200
    assert set(response.data) == {"access"}
    assert isinstance(response.data["access"], str)


def test_refresh_rejects_malformed_token(api_client):
    response = api_client.post(
        reverse("auth-refresh"),
        {"refresh": "not-a-jwt"},
        format="json",
    )

    assert response.status_code == 401
    assert set(response.data) == {"detail", "code"}


def test_refresh_token_cannot_authenticate_me(api_client, user):
    refresh = login(api_client).data["refresh"]
    api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {refresh}")

    response = api_client.get(reverse("auth-me"))

    assert response.status_code == 401


def test_existing_access_token_is_rejected_after_user_deactivation(api_client, user):
    access = login(api_client).data["access"]
    user.is_active = False
    user.save(update_fields=["is_active"])
    api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {access}")

    response = api_client.get(reverse("auth-me"))

    assert response.status_code == 401


def test_existing_refresh_token_is_rejected_after_user_deactivation(api_client, user):
    refresh = login(api_client).data["refresh"]
    user.is_active = False
    user.save(update_fields=["is_active"])

    response = api_client.post(
        reverse("auth-refresh"),
        {"refresh": refresh},
        format="json",
    )

    assert response.status_code == 401


def test_me_returns_updated_database_role_for_existing_access_token(api_client, user):
    access = login(api_client).data["access"]
    user.role = UserRole.PRESALES
    user.save(update_fields=["role"])
    api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {access}")

    response = api_client.get(reverse("auth-me"))

    assert response.status_code == 200
    assert response.data["role"] == UserRole.PRESALES
