"""Behavior tests for the custom user model and manager."""

import pytest
from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction

from apps.accounts.models import UserRole


pytestmark = pytest.mark.django_db


def test_create_user_requires_email(user_data):
    user_data["email"] = ""

    with pytest.raises(ValueError, match="email"):
        get_user_model().objects.create_user(**user_data)


def test_create_user_requires_role(user_data):
    user_data["role"] = ""

    with pytest.raises(ValueError, match="role"):
        get_user_model().objects.create_user(**user_data)


def test_create_user_hashes_password(user_data):
    raw_password = user_data["password"]

    user = get_user_model().objects.create_user(**user_data)

    assert user.password != raw_password
    assert user.check_password(raw_password)


def test_email_is_unique(user_data):
    user_model = get_user_model()
    user_model.objects.create_user(**user_data)
    user_data["username"] = "bob"

    with pytest.raises(IntegrityError), transaction.atomic():
        user_model.objects.create_user(**user_data)


def test_database_rejects_invalid_role(user_data):
    user_data["role"] = "manager"

    with pytest.raises(IntegrityError), transaction.atomic():
        get_user_model().objects.create_user(**user_data)


def test_business_admin_role_does_not_grant_django_admin_flags(user_data):
    user_data["role"] = UserRole.ADMIN

    user = get_user_model().objects.create_user(**user_data)

    assert user.is_staff is False
    assert user.is_superuser is False


def test_superuser_flags_do_not_rewrite_business_role(user_data):
    user_data["role"] = UserRole.PRESALES

    user = get_user_model().objects.create_superuser(**user_data)

    assert user.role == UserRole.PRESALES
    assert user.is_staff is True
    assert user.is_superuser is True


def test_createsuperuser_requests_email_and_role():
    assert get_user_model().REQUIRED_FIELDS == ["email", "role"]


@pytest.mark.parametrize("flag", ["is_staff", "is_superuser"])
def test_create_superuser_rejects_disabled_privilege_flag(user_data, flag):
    user_data[flag] = False

    with pytest.raises(ValueError, match=flag):
        get_user_model().objects.create_superuser(**user_data)
