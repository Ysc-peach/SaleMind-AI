"""A user can rotate their own password, and every old session dies with it."""

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse
from rest_framework.test import APIClient


pytestmark = pytest.mark.django_db

OLD = "StrongPassword123!"
NEW = "AnotherStrongPass456!"


@pytest.fixture
def api_client():
    return APIClient()


@pytest.fixture
def tokens(api_client):
    get_user_model().objects.create_user(
        "alice", "alice@example.com", "sales", password=OLD,
    )
    response = api_client.post(
        reverse("auth-login"),
        {"username": "alice", "password": OLD},
        format="json",
    )
    assert response.status_code == 200
    return response.data


def _change(api_client, tokens, *, current=OLD, new=NEW):
    return api_client.post(
        reverse("auth-password"),
        {"current_password": current, "new_password": new},
        format="json",
        HTTP_AUTHORIZATION=f"Bearer {tokens['access']}",
    )


def test_password_change_lets_the_user_sign_in_with_the_new_password(
    api_client, tokens,
):
    response = _change(api_client, tokens)

    assert response.status_code == 204
    old_login = api_client.post(
        reverse("auth-login"),
        {"username": "alice", "password": OLD},
        format="json",
    )
    new_login = api_client.post(
        reverse("auth-login"),
        {"username": "alice", "password": NEW},
        format="json",
    )
    assert old_login.status_code == 401
    assert new_login.status_code == 200


def test_password_change_revokes_every_existing_refresh_token(api_client, tokens):
    _change(api_client, tokens)

    refresh = api_client.post(
        reverse("auth-refresh"), {"refresh": tokens["refresh"]}, format="json",
    )

    assert refresh.status_code == 401


def test_a_wrong_current_password_is_rejected(api_client, tokens):
    response = _change(api_client, tokens, current="NotTheRealOne1!")

    assert response.status_code == 400
    assert "current_password" in response.data
    # The stored password must be untouched after a rejected attempt.
    user = get_user_model().objects.get(username="alice")
    assert user.check_password(OLD)


def test_reusing_the_current_password_is_rejected(api_client, tokens):
    response = _change(api_client, tokens, new=OLD)

    assert response.status_code == 400
    assert "new_password" in response.data


def test_a_weak_password_fails_the_project_validators(api_client, tokens):
    response = _change(api_client, tokens, new="12345678")

    assert response.status_code == 400
    assert "new_password" in response.data


def test_anonymous_callers_cannot_change_a_password(api_client):
    response = api_client.post(
        reverse("auth-password"),
        {"current_password": OLD, "new_password": NEW},
        format="json",
    )

    assert response.status_code == 401
