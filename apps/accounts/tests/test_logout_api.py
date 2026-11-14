"""A logout must revoke the refresh token, not just clear browser state."""

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse
from rest_framework.test import APIClient


pytestmark = pytest.mark.django_db


@pytest.fixture
def api_client():
    return APIClient()


@pytest.fixture
def logged_in(api_client):
    get_user_model().objects.create_user(
        "alice", "alice@example.com", "sales",
        password="StrongPassword123!",
    )
    response = api_client.post(
        reverse("auth-login"),
        {"username": "alice", "password": "StrongPassword123!"},
        format="json",
    )
    assert response.status_code == 200
    return response.data


def test_logout_blacklists_the_refresh_token(api_client, logged_in):
    logout = api_client.post(
        reverse("auth-logout"), {"refresh": logged_in["refresh"]},
        format="json",
    )

    assert logout.status_code == 204
    refresh = api_client.post(
        reverse("auth-refresh"), {"refresh": logged_in["refresh"]},
        format="json",
    )
    assert refresh.status_code == 401


def test_a_revoked_token_cannot_be_presented_again(api_client, logged_in):
    payload = {"refresh": logged_in["refresh"]}

    first = api_client.post(reverse("auth-logout"), payload, format="json")
    second = api_client.post(reverse("auth-logout"), payload, format="json")

    assert first.status_code == 204
    # The blacklisted token fails RefreshToken validation, so a replay is
    # rejected rather than silently treated as a second success.
    assert second.status_code == 400


def test_logout_requires_a_refresh_token(api_client):
    response = api_client.post(reverse("auth-logout"), {}, format="json")

    assert response.status_code == 400
    assert "refresh" in response.data


def test_logout_rejects_a_malformed_token_without_details(api_client):
    response = api_client.post(
        reverse("auth-logout"), {"refresh": "not-a-jwt"}, format="json",
    )

    assert response.status_code == 400
    assert "not-a-jwt" not in str(response.data)
