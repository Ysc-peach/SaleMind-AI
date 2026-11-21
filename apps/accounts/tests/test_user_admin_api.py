"""Account management: who may hire, move and stop a colleague, and what stops a lockout."""

from datetime import timedelta
from uuid import uuid4

import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework.test import APIClient
from rest_framework_simplejwt.token_blacklist.models import (
    BlacklistedToken,
    OutstandingToken,
)

from apps.accounts.models import UserRole

pytestmark = pytest.mark.django_db

USERS_URL = "/api/users/"
PASSWORD = "StrongPassword123!"
NEW_PASSWORD = "AnotherStrongPass456!"


def make_user(username, role, *, password=PASSWORD, active=True):
    return get_user_model().objects.create_user(
        username=username,
        email=f"{username}@example.com",
        role=role,
        password=password,
        is_active=active,
    )


def client_for(user):
    client = APIClient()
    client.force_authenticate(user=user)
    return client


def live_token(user):
    return OutstandingToken.objects.create(
        user=user,
        jti=uuid4(),
        token="token-placeholder",
        created_at=timezone.now(),
        expires_at=timezone.now() + timedelta(days=1),
    )


def test_an_admin_can_list_accounts_without_seeing_credentials():
    admin = make_user("boss", UserRole.ADMIN)
    make_user("seller", UserRole.SALES)

    response = client_for(admin).get(USERS_URL)

    assert response.status_code == 200
    rows = response.data["results"]
    assert {row["username"] for row in rows} == {"boss", "seller"}
    # A list that carries a password hash is one screenshot away from an incident.
    assert "password" not in rows[0]


def test_a_non_admin_cannot_reach_account_management():
    seller = make_user("seller", UserRole.SALES)

    client = client_for(seller)
    listing = client.get(USERS_URL)
    creation = client.post(
        USERS_URL,
        {
            "username": "new",
            "email": "new@example.com",
            "role": "sales",
            "password": PASSWORD,
        },
        format="json",
    )

    assert listing.status_code == 403
    assert creation.status_code == 403
    assert get_user_model().objects.filter(username="new").exists() is False


def test_an_admin_creates_a_colleague_who_can_sign_in():
    admin = make_user("boss", UserRole.ADMIN)

    response = client_for(admin).post(
        USERS_URL,
        {
            "username": "newpresales",
            "email": "newpresales@example.com",
            "role": "presales",
            "password": PASSWORD,
            "first_name": "新",
            "last_name": "售前",
        },
        format="json",
    )

    assert response.status_code == 201
    created = get_user_model().objects.get(username="newpresales")
    assert created.role == UserRole.PRESALES
    assert created.check_password(PASSWORD)
    assert response.data["role_label"] == "售前"


def test_a_weak_password_is_refused():
    admin = make_user("boss", UserRole.ADMIN)

    response = client_for(admin).post(
        USERS_URL,
        {
            "username": "weakling",
            "email": "weakling@example.com",
            "role": "sales",
            "password": "12345678",
        },
        format="json",
    )

    assert response.status_code == 400
    assert not get_user_model().objects.filter(username="weakling").exists()


def test_a_duplicate_username_or_email_is_refused():
    admin = make_user("boss", UserRole.ADMIN)
    make_user("taken", UserRole.SALES)
    client = client_for(admin)

    same_username = client.post(
        USERS_URL,
        {
            "username": "taken",
            "email": "other@example.com",
            "role": "sales",
            "password": PASSWORD,
        },
        format="json",
    )
    same_email = client.post(
        USERS_URL,
        {
            "username": "fresh",
            "email": "taken@example.com",
            "role": "sales",
            "password": PASSWORD,
        },
        format="json",
    )

    assert same_username.status_code == 400
    assert same_email.status_code == 400


def test_an_unknown_role_is_refused():
    admin = make_user("boss", UserRole.ADMIN)

    response = client_for(admin).post(
        USERS_URL,
        {
            "username": "ghost",
            "email": "ghost@example.com",
            "role": "intern",
            "password": PASSWORD,
        },
        format="json",
    )

    assert response.status_code == 400


def test_deactivating_a_colleague_ends_their_sessions():
    admin = make_user("boss", UserRole.ADMIN)
    seller = make_user("seller", UserRole.SALES)
    token = live_token(seller)

    response = client_for(admin).post(f"{USERS_URL}{seller.pk}/deactivate/")

    assert response.status_code == 200
    seller.refresh_from_db()
    assert seller.is_active is False
    # The seven-day refresh token must die with the account, or the person keeps
    # working until it expires.
    assert BlacklistedToken.objects.filter(token=token).exists()


def test_an_admin_cannot_deactivate_themselves():
    admin = make_user("boss", UserRole.ADMIN)
    make_user("deputy", UserRole.ADMIN)

    response = client_for(admin).post(f"{USERS_URL}{admin.pk}/deactivate/")

    assert response.status_code == 409
    assert response.data["code"] == "user_self_deactivation"
    admin.refresh_from_db()
    assert admin.is_active is True


def test_the_last_administrator_cannot_be_demoted():
    admin = make_user("boss", UserRole.ADMIN)

    response = client_for(admin).patch(
        f"{USERS_URL}{admin.pk}/", {"role": "sales"}, format="json"
    )

    # Demoting yourself is allowed only when someone else can promote you back.
    assert response.status_code == 409
    assert response.data["code"] == "user_last_admin"
    admin.refresh_from_db()
    assert admin.role == UserRole.ADMIN


def test_demoting_a_colleague_when_another_admin_remains_is_allowed():
    admin = make_user("boss", UserRole.ADMIN)
    deputy = make_user("deputy", UserRole.ADMIN)

    response = client_for(admin).patch(
        f"{USERS_URL}{deputy.pk}/", {"role": "presales"}, format="json"
    )

    assert response.status_code == 200
    deputy.refresh_from_db()
    assert deputy.role == UserRole.PRESALES


def test_a_role_change_revokes_the_sessions_issued_under_the_old_role():
    admin = make_user("boss", UserRole.ADMIN)
    seller = make_user("seller", UserRole.SALES)
    token = live_token(seller)

    response = client_for(admin).patch(
        f"{USERS_URL}{seller.pk}/", {"role": "presales"}, format="json"
    )

    assert response.status_code == 200
    assert BlacklistedToken.objects.filter(token=token).exists()


def test_an_admin_resets_a_password_and_the_old_sessions_end():
    admin = make_user("boss", UserRole.ADMIN)
    seller = make_user("seller", UserRole.SALES)
    token = live_token(seller)

    response = client_for(admin).post(
        f"{USERS_URL}{seller.pk}/password/",
        {"password": NEW_PASSWORD},
        format="json",
    )

    assert response.status_code == 204
    seller.refresh_from_db()
    assert seller.check_password(NEW_PASSWORD)
    assert BlacklistedToken.objects.filter(token=token).exists()


def test_a_reset_still_enforces_the_password_policy():
    admin = make_user("boss", UserRole.ADMIN)
    seller = make_user("seller", UserRole.SALES)

    response = client_for(admin).post(
        f"{USERS_URL}{seller.pk}/password/",
        {"password": "12345678"},
        format="json",
    )

    assert response.status_code == 400
    seller.refresh_from_db()
    assert seller.check_password(PASSWORD)


def test_a_deactivated_account_cannot_sign_in():
    admin = make_user("boss", UserRole.ADMIN)
    seller = make_user("seller", UserRole.SALES)
    client_for(admin).post(f"{USERS_URL}{seller.pk}/deactivate/")

    response = APIClient().post(
        "/api/auth/login/", {"username": "seller", "password": PASSWORD}, format="json"
    )

    assert response.status_code == 401


def test_the_list_filters_by_role_text_and_archive_state():
    admin = make_user("boss", UserRole.ADMIN)
    make_user("alice", UserRole.SALES)
    make_user("bob", UserRole.PRESALES)
    make_user("gone", UserRole.SALES, active=False)
    client = client_for(admin)

    by_role = client.get(USERS_URL, {"role": "presales"}).data
    by_text = client.get(USERS_URL, {"q": "ali"}).data
    with_archived = client.get(USERS_URL, {"include_inactive": "1"}).data
    bad_role = client.get(USERS_URL, {"role": "intern"})

    assert [row["username"] for row in by_role["results"]] == ["bob"]
    assert [row["username"] for row in by_text["results"]] == ["alice"]
    assert "gone" in {row["username"] for row in with_archived["results"]}
    assert bad_role.status_code == 400


def test_reactivating_an_account_restores_access():
    admin = make_user("boss", UserRole.ADMIN)
    seller = make_user("seller", UserRole.SALES, active=False)

    response = client_for(admin).post(f"{USERS_URL}{seller.pk}/activate/")

    assert response.status_code == 200
    seller.refresh_from_db()
    assert seller.is_active is True
